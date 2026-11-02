"""Catalog matching and safe, simulated order queue."""
from copy import deepcopy
import asyncio
import logging
from datetime import timedelta
from uuid import uuid4
from urllib.parse import urlparse
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from .fulfillment import fulfillment_snapshot, mapped_item, receipt_eligible, safe_code, item_delivery_confirmed
from .batch import review_batch
from .shopping import shopping_items, shopping_entity_for_item
from .notifications import emit
from .product_config import PREFERENCES_SCHEMA, NOTIFICATION_SCHEMA, product_values
from .const import ACTIVE_PURCHASE_STATUSES, EVENT_UPDATED

_LOGGER = logging.getLogger(__name__)

def validated_substitutes(primary, substitutes):
    """Only accept explicit HTTPS alternatives, at most two, no duplicates."""
    result = []
    for raw in (substitutes or []):
        value = raw.strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Each substitute must be an HTTPS product URL")
        if value not in result and value != primary:
            result.append(value)
    if len(result) > 2:
        raise ValueError("At most two substitutes are allowed")
    return result

def norm(value: str) -> str:
    return " ".join(value.casefold().split())

class ReorderEngine:
    def __init__(self, hass, store):
        self.hass, self.store = hass, store
        self.lock = asyncio.Lock()
        self.shopping_lock = asyncio.Lock()
        self.refresh_lock = asyncio.Lock()
        self._refresh_cursor = 0
        self.selected_batch_id = None
        self.intake_events = []
        self.notification_delivery = None

    def publish(self):
        self.hass.bus.async_fire(EVENT_UPDATED)

    async def upsert_product(self, name, aliases, retailer, product_id, quantity, max_price, cooldown_hours, enabled, substitutes=None, original_name=None, create_only=False):
        values = product_values(dict(name=name, aliases=aliases, retailer=retailer,
            product_id=product_id, quantity=quantity, max_price=max_price,
            cooldown_hours=cooldown_hours, enabled=enabled, substitutes=substitutes or []))
        key = norm(values["name"])
        old_key = norm(original_name) if original_name is not None else key
        replacements = validated_substitutes(values["product_id"], values["substitutes"])
        if replacements and retailer != "zinc":
            raise ValueError("Substitutions currently require Zinc products")
        async with self.lock:
            products = self.store.data["products"]
            if create_only and key in products:
                raise ValueError("A product with this name already exists")
            if original_name is not None and old_key not in products:
                raise ValueError("The product no longer exists; reload before saving")
            if old_key != key:
                if key in products:
                    raise ValueError("A product with this name already exists")
                if any(order["product_key"] == old_key for order in self.store.data["orders"].values()):
                    raise ValueError("A product with order history cannot be renamed; edit its aliases instead")
            record = {"name": values["name"], "aliases": sorted(set(norm(alias) for alias in aliases if norm(alias))),
                "retailer": retailer, "product_id": values["product_id"], "quantity": values["quantity"],
                "max_price": values["max_price"], "cooldown_hours": values["cooldown_hours"],
                "enabled": values["enabled"], "substitutes": replacements}
            if record["enabled"]:
                labels = {key, *record["aliases"]}
                for other_key, other in products.items():
                    if other_key != old_key and other["enabled"] and labels.intersection({other_key, *other["aliases"]}):
                        raise ValueError(f"A name or alias already matches enabled product {other['name']}; make matches unique")
            previous = deepcopy(products)
            products.pop(old_key, None)
            products[key] = record
            try:
                await self.store.save()
            except Exception:
                products.clear()
                products.update(previous)
                raise
        self.publish()

    async def remove_product(self, name):
        async with self.lock:
            products = self.store.data["products"]
            previous = deepcopy(products)
            products.pop(norm(name), None)
            try:
                await self.store.save()
            except Exception:
                products.clear()
                products.update(previous)
                raise
        self.publish()

    async def update_preferences(self, **values):
        settings = PREFERENCES_SCHEMA(values)
        sync = settings.pop("sync_shopping_list")
        automatic = settings.pop("auto_complete_delivered", None)
        notifications = settings.pop("notification_settings", None)
        if notifications is not None:
            for key in ("events", "notify_services", "notify_entities", "kiosk_services"):
                notifications[key] = list(dict.fromkeys(notifications[key]))
        async with self.lock:
            previous = deepcopy(self.store.data.get("batch_settings", {}))
            previous_preferences = deepcopy(self.store.data.get("preferences", {}))
            changed = any(previous.get(key) != value for key, value in settings.items())
            self.store.data["batch_settings"] = {**previous, **settings,
                "last_scheduled_date": None if changed else previous.get("last_scheduled_date")}
            self.store.data["preferences"] = {**previous_preferences, "sync_shopping_list": sync}
            if notifications is not None:
                self.store.data["preferences"]["notification_settings"] = notifications
            if automatic is not None:
                self.store.data["preferences"]["auto_complete_delivered"] = automatic
            try:
                await self.store.save()
            except Exception:
                self.store.data["batch_settings"] = previous
                self.store.data["preferences"] = previous_preferences
                raise
        self.publish()
        return {**self.store.data["batch_settings"], "sync_shopping_list": sync}

    async def update_notifications(self, values):
        settings = NOTIFICATION_SCHEMA(values)
        for key in ("events", "notify_services", "notify_entities", "kiosk_services"):
            settings[key] = list(dict.fromkeys(settings[key]))
        async with self.lock:
            previous = deepcopy(self.store.data.get("preferences", {}))
            self.store.data.setdefault("preferences", {})["notification_settings"] = settings
            try:
                await self.store.save()
            except Exception:
                self.store.data["preferences"] = previous
                raise
        self.publish()

    def _record_intake(self, item, reason, message, order_id=None):
        """Bounded, per-run diagnostics; never store entire Shopping List payloads."""
        event = {"name": item.get("name", ""), "reason": reason, "message": message,
                 "created_at": dt_util.utcnow().isoformat(), "order_id": order_id}
        self.intake_events.insert(0, event)
        del self.intake_events[20:]
        self.publish()
        return event

    @staticmethod
    def _receipt_recorded(order):
        return bool(order.get("delivery_confirmed_at") or (order.get("shopping_list_completed_at") and order.get("receipt_mode") in ("sandbox_simulation", "delivered_item")))

    def _active_purchase(self, order):
        return (order["status"] in ACTIVE_PURCHASE_STATUSES
                and not (order["status"] == "order_placed" and self._receipt_recorded(order)))

    def _purchase_blocker(self, previous, requesting):
        if self._active_purchase(previous):
            return True
        if self._receipt_recorded(previous):
            hours = requesting.get("cooldown_hours", self.store.data["products"].get(requesting["product_key"], {}).get("cooldown_hours", 168))
            return previous.get("delivery_confirmed_at", previous.get("shopping_list_completed_at")) >= (dt_util.utcnow() - timedelta(hours=hours)).isoformat()
        return False

    def _shopping_sync_enabled(self):
        return self.store.data.get("preferences", {}).get("sync_shopping_list", True)

    def _check_shopping_items_before_submission(self, orders):
        """Also guard against a list edit whose event has not finished processing."""
        linked = [order for order in orders if order.get("shopping_item_id")]
        if not linked or not self._shopping_sync_enabled():
            return
        items = shopping_items(self.hass)
        if items is None:
            raise ValueError("Shopping List state is unavailable; review it before submitting")
        indexed = {str(item["id"]): item for item in items}
        for order in linked:
            item = indexed.get(order["shopping_item_id"])
            if item is None or item.get("complete"):
                raise ValueError("A Shopping List item was removed or completed; review the queue before submitting")
            label = norm(item.get("name") or "")
            labels = {norm(order.get("shopping_item_name", order["name"])), norm(order["name"])}
            matches = [key for key, product in self.store.data["products"].items()
                       if product["enabled"] and label in {key, *product["aliases"]}]
            if label not in labels and not (len(matches) == 1 and matches[0] == order["product_key"]):
                raise ValueError("A Shopping List item was renamed; review the queue before submitting")

    async def _cancel_list_item(self, item, change):
        """Cancel local lines and invalidate ready batches atomically under one lock."""
        item_id = str(item.get("id") or "")
        async with self.lock:
            linked = [order for order in self.store.data["orders"].values()
                      if order.get("shopping_item_id") == item_id]
            if any("zinc_environment" in order or order.get("zinc_order_id") for order in linked):
                self._record_intake(item, "submitted_unchanged", "This item has submitted work. The Shopping List change did not cancel or alter a retailer order.")
                return False
            active = [order for order in linked if order["status"] in ("queued", "approved")]
            if not active:
                return True
            batches = {}
            touched = {order["id"]: order for order in active}
            for order in active:
                batch_id = order.get("batch_id")
                if not batch_id:
                    continue
                batch = self.store.data.get("batches", {}).get(batch_id)
                if (batch is None or batch["status"] != "ready" or "zinc_environment" in batch
                        or batch.get("zinc_order_id")):
                    self._record_intake(item, "sync_blocked", "The batch is not safely editable locally. Review its status before making changes.")
                    return False
                members = [self.store.data["orders"].get(key) for key in batch["order_ids"]]
                if any(member is None or member.get("batch_id") != batch_id
                       or member["status"] not in ("queued", "approved")
                       or "zinc_environment" in member or member.get("zinc_order_id") for member in members):
                    self._record_intake(item, "sync_blocked", "The batch contains changed or attempted work; it was left untouched.")
                    return False
                batches[batch_id] = batch
                touched.update({member["id"]: member for member in members})
            old_orders = {key: deepcopy(order) for key, order in touched.items()}
            old_batches = {key: deepcopy(batch) for key, batch in batches.items()}
            active_ids = {order["id"] for order in active}
            now = dt_util.utcnow().isoformat()
            snapshots_by_batch = {key: review_batch(self.store.data, key)["orders"] for key in batches}
            for batch_id, batch in batches.items():
                snapshots = snapshots_by_batch[batch_id]
                for snapshot in snapshots:
                    snapshot["status"] = "canceled" if snapshot["id"] in active_ids else "returned_to_queue"
                batch.update(status="invalidated", invalidated_at=now, snapshot_orders=snapshots,
                    note="Shopping List changed. Batch invalidated; unaffected lines returned to the queue for fresh review.")
                for order_id in batch["order_ids"]:
                    if order_id not in active_ids:
                        survivor = touched[order_id]
                        survivor.pop("batch_id", None)
                        survivor["note"] = "Returned to queue after a Shopping List change; prepare a new batch for review."
            for order in active:
                order.update(status="canceled", canceled_at=now, shopping_list_change=change,
                    note=f"Canceled locally after Shopping List {change}; no purchase was made.")
            try:
                await self.store.save()
            except Exception:
                for key, previous in old_orders.items():
                    touched[key].clear()
                    touched[key].update(previous)
                for key, previous in old_batches.items():
                    batches[key].clear()
                    batches[key].update(previous)
                self._record_intake(item, "storage_error", "Shopping List changes could not be saved. Review local work before submitting; no retailer request was made.")
                raise
            message = "Unsubmitted order canceled locally after the Shopping List change."
            if batches:
                message += " Its prepared batch was invalidated; other lines returned to the queue for fresh review."
            self._record_intake(item, "list_change", message)
            emit(self, "list_change", message + " No retailer purchase was canceled.")
            return True

    async def _handle_item_change(self, action, item):
        if not isinstance(item, dict) or not item.get("id"):
            return
        if action == "remove" or action == "complete" or item.get("complete"):
            return await self._cancel_list_item(item, "remove" if action == "remove" else "complete")
        item_id = str(item["id"])
        async with self.lock:
            linked = [order for order in self.store.data["orders"].values()
                      if order.get("shopping_item_id") == item_id]
            if any("zinc_environment" in order or order.get("zinc_order_id") for order in linked):
                self._record_intake(item, "submitted_unchanged", "Submitted work is unchanged. Add a separate new item for a new request; list edits never cancel a purchase.")
                return
            active = [order for order in linked if order["status"] in ("queued", "approved")]
            label = norm(item.get("name") or "")
            matches = [key for key, product in self.store.data["products"].items()
                       if product["enabled"] and label in {key, *product["aliases"]}]
            same_label = active and all(norm(order.get("shopping_item_name", order["name"])) == label for order in active)
            if active and (same_label or (len(matches) == 1 and all(order["product_key"] == matches[0] for order in active))):
                previous_names = {order["id"]: order.get("shopping_item_name") for order in active}
                changed = any(order.get("shopping_item_name") != item["name"] for order in active)
                if changed:
                    for order in active:
                        order["shopping_item_name"] = item["name"]
                    try:
                        await self.store.save()
                    except Exception:
                        for order in active:
                            old_name = previous_names[order["id"]]
                            if old_name is None:
                                order.pop("shopping_item_name", None)
                            else:
                                order["shopping_item_name"] = old_name
                        raise
                self._record_intake(item, "unchanged", "The edited name still matches the same product; saved quantities, prices, and batch were left unchanged.")
                return
        if active and not await self._cancel_list_item(item, "rename"):
            return
        async with self.lock:
            history = [order for order in self.store.data["orders"].values() if order.get("shopping_item_id") == item_id]
            latest = max(history, key=lambda order: order["created_at"], default=None)
            resumable = (latest is not None and latest["status"] == "canceled"
                         and latest.get("shopping_list_change") in ("rename", "complete")
                         and "zinc_environment" not in latest and not latest.get("zinc_order_id"))
            previous_seen = list(self.store.data["seen_items"])
            if resumable:
                self.store.data["seen_items"] = [key for key in previous_seen if key != item_id]
                try:
                    await self.store.save()
                except Exception:
                    self.store.data["seen_items"] = previous_seen
                    self._record_intake(item, "storage_error", "The edited item could not be requeued. Existing canceled work was not revived; check logs and retry the list edit after storage is repaired.")
                    raise
        return await self.match_new_item(item)

    async def handle_shopping_event(self, action, item=None, items=None):
        """Serialize source events so rapid edits cannot reorder queue mutations."""
        async with self.shopping_lock:
            if action == "add":
                return await self.match_new_item(item)
            if not self._shopping_sync_enabled():
                if isinstance(item, dict):
                    self._record_intake(item, "sync_disabled", "Shopping List synchronization is off; existing orders were left unchanged.")
                return
            if action in ("update", "complete", "remove"):
                return await self._handle_item_change(action, item)
            if action not in ("clear", "update_list"):
                return
            if items is None:
                self._record_intake({"name": "Shopping List"}, "sync_unavailable", "The current list could not be read. No orders were changed.")
                return
            if action == "update_list":
                for current in items:
                    await self._handle_item_change("update", current)
            if action in ("clear", "update_list"):
                ids = {str(current["id"]) for current in items}
                async with self.lock:
                    missing = {order["shopping_item_id"]: {"id": order["shopping_item_id"], "name": order["name"]}
                               for order in self.store.data["orders"].values()
                               if order.get("shopping_item_id") and order["shopping_item_id"] not in ids
                               and order["status"] in ("queued", "approved")}
                for current in missing.values():
                    await self._handle_item_change("remove", current)

    async def match_new_item(self, item):
        if not isinstance(item, dict):
            return
        if not isinstance(item.get("name"), str) or not item["name"].strip() or item.get("complete"):
            return self._record_intake(item, "ignored", "The item is empty or already complete.")
        label = norm(item["name"])
        item_id = str(item.get("id") or "")
        if not item_id:
            _LOGGER.warning("Ignoring shopping-list item missing id")
            return self._record_intake(item, "invalid_item", "The Shopping List item has no ID.")
        async with self.lock:
            if item_id in self.store.data["seen_items"]:
                return self._record_intake(item, "already_seen", "This Shopping List item was already queued; no duplicate was created.")
            candidates = [product for key, product in self.store.data["products"].items()
                          if label in {key, *product["aliases"]}]
            matches = [product for product in candidates if product["enabled"]]
            if not matches:
                if candidates:
                    return self._record_intake(item, "disabled", "The matching catalog product is disabled. Enable it in Reorder settings.")
                return self._record_intake(item, "no_match", "No enabled catalog name or alias matches this item. Add its exact name or alias in Reorder settings.")
            if len(matches) != 1:
                return self._record_intake(item, "ambiguous", "More than one enabled product matches this name or alias. Make the catalog aliases unique.")
            product = matches[0]
            now = dt_util.utcnow()
            prior = [order for order in self.store.data["orders"].values()
                     if order["product_key"] == norm(product["name"])]
            active = next((order for order in prior if order["status"] in ("queued", "approved") or self._active_purchase(order)), None)
            if active:
                return self._record_intake(item, "existing_order", f"Existing order {active['id']} has status {active['status']}. Review it before creating another.", active["id"])
            cutoff = now - timedelta(hours=product["cooldown_hours"])
            # A never-submitted local cancellation must not start a purchase cooldown.
            recent = next((order for order in prior if order.get("delivery_confirmed_at", order.get("shopping_list_completed_at", order.get("submitted_at", order["created_at"]))) >= cutoff.isoformat()
                           and not (order["status"] == "canceled" and "zinc_environment" not in order
                                    and not order.get("zinc_order_id"))), None)
            if recent:
                return self._record_intake(item, "cooldown", f"The product's {product['cooldown_hours']}-hour cooldown is still active after order {recent['id']}.", recent["id"])
            order_id = uuid4().hex[:12]
            self.store.data["orders"][order_id] = {
                "id": order_id, "product_key": norm(product["name"]),
                "name": product["name"], "retailer": product["retailer"],
                "product_id": product["product_id"], "quantity": product["quantity"],
                "max_price": product["max_price"], "status": "queued",
                "substitutes": list(product.get("substitutes", [])), "substitution_index": 0,
                "shopping_item_id": item_id, "shopping_item_name": item["name"], "created_at": now.isoformat(), "cooldown_hours": product["cooldown_hours"],
                "note": "Queued locally; no retailer API was called.",
            }
            previous_seen = list(self.store.data["seen_items"])
            self.store.data["seen_items"].append(item_id)
            self.store.data["seen_items"] = self.store.data["seen_items"][-2000:]
            try:
                await self.store.save()
            except Exception:
                self.store.data["orders"].pop(order_id, None)
                self.store.data["seen_items"] = previous_seen
                self._record_intake(item, "storage_error", "The queued order could not be saved. Check Home Assistant logs; no purchase was attempted.")
                raise
        message = f"Queued locally as {order_id}. No purchase was made."
        if product["retailer"] != "zinc":
            message += f" This product uses {product['retailer']} and is not eligible for Zinc batches."
        result = self._record_intake(item, "queued", message, order_id)
        strategy = self.store.data.get("batch_settings", {}).get("strategy", "manual")
        next_step = ("Review your cart and prepare a batch when ready."
                     if strategy == "manual" else "Your schedule will prepare a batch for review; it never places orders.")
        if product["retailer"] != "zinc":
            next_step = "This catalog provider is not eligible for Zinc batches."
        emit(self, "cart_added", f"Added {product['name']} × {product['quantity']} to your cart. "
             f"Saved allowance ${product['max_price']:.2f}. {next_step} No purchase has been made.", order_id=order_id)
        return result

    async def queue_next_substitution(self, order_id):
        """Prepare a replacement only for a confirmed out-of-stock order.

        Never auto-purchase or replay a request after an unknown network response.
        """
        async with self.lock:
            original = self.store.data["orders"].get(order_id)
            if not original:
                raise ValueError("Order not found")
            if original.get("status") != "out_of_stock":
                raise ValueError("Original order must be confirmed out of stock")
            if original.get("replacement_order_id"):
                raise ValueError("A replacement has already been queued")
            alternatives = original.get("substitutes", [])
            index = int(original.get("substitution_index", 0))
            if index >= len(alternatives):
                raise ValueError("No remaining approved substitutions")
            next_id = uuid4().hex[:12]
            replacement = {**original,
                "id": next_id, "product_id": alternatives[index],
                "substitution_index": index + 1, "status": "queued",
                "created_at": dt_util.utcnow().isoformat(),
                "note": "Replacement queued, not purchased; explicit confirmation required.",
                "replaces_order_id": order_id,
            }
            for key in ("zinc_order_id", "zinc_environment", "replacement_order_id"):
                replacement.pop(key, None)
            original["replacement_order_id"] = next_id
            self.store.data["orders"][next_id] = replacement
            await self.store.save()
        self.publish()
        return next_id

    async def change_status(self, order_id, status):
        async with self.lock:
            order = self.store.data["orders"].get(order_id)
            if order is None:
                raise ValueError("Order ID not found")
            if order.get("batch_id"):
                raise ValueError("Order belongs to a batch; manage its batch instead")
            if order["status"] != "queued":
                raise ValueError("Only queued orders can be modified")
            order["status"] = status
            order["note"] = "Approved locally; no purchase was made." if status == "approved" else "Canceled; no purchase was made."
            await self.store.save()
        self.publish()

    async def submit_zinc(self, order_id: str, client, address, sandbox: bool):
        """Persist submitted state BEFORE network I/O to prevent accidental retries."""
        async with self.lock:
            order = self.store.data["orders"].get(order_id)
            if order is None or order["status"] not in ("queued", "approved") or order.get("batch_id") or "zinc_environment" in order:
                raise ValueError("Order must be queued or approved")
            if order["retailer"] != "zinc":
                raise ValueError("Order is not assigned to Zinc")
            if not order["product_id"].startswith("https://"):
                raise ValueError("Zinc requires a full HTTPS product URL")
            if any(o["product_key"] == order["product_key"] and self._purchase_blocker(o, order) for o in self.store.data["orders"].values() if o["id"] != order_id):
                raise ValueError("Another order for this product is already active")
            self._check_shopping_items_before_submission([order])
            order["status"] = "submitting"
            order["submitted_at"] = dt_util.utcnow().isoformat()
            order["note"] = "Submission started; do not retry blindly if the connection fails."
            order["zinc_environment"] = "sandbox" if sandbox else "live"
            await self.store.save()
        self.publish()
        try:
            response = await client.create_order(order, address)
            if not isinstance(response, dict) or not (response.get("id") or response.get("order_id")):
                raise ValueError("Zinc response missing order ID; reconcile before retrying")
        except Exception:
            async with self.lock:
                order["status"] = "submission_unknown"
                order["note"] = "Check Zinc dashboard before retrying. Same idempotency key required."
                await self.store.save()
            self.publish()
            raise
        async with self.lock:
            order["zinc_order_id"] = response.get("id") or response.get("order_id")
            order["status"] = response.get("status", "submitted")
            order["note"] = "Zinc accepted request; retailer purchase may still be pending."
            await self.store.save()
        self.publish()

    async def refresh_zinc(self, order_id: str, client):
        async with self.lock:
            order = self.store.data["orders"].get(order_id)
            if not order or not order.get("zinc_order_id"):
                raise ValueError("Order has no Zinc order ID")
            zinc_id = order["zinc_order_id"]
        result = await client.get_order(zinc_id)
        async with self.lock:
            status = result.get("status", order["status"])
            error = result.get("error") or {}
            code = (error.get("code") if isinstance(error, dict) else None) or result.get("error_code")
            # Only an explicitly failed order with Zinc's documented stock error
            # can enter replacement workflow. Never infer this from an HTTP error.
            if status in ("failed", "order_failed") and code in ("out_of_stock", "product_out_of_stock"):
                order["status"] = "out_of_stock"
                order["note"] = "Zinc confirmed out_of_stock; approved replacement can be queued."
            else:
                order["status"] = status
                order["note"] = "Latest status checked with Zinc."
            await self.store.save()
        self.publish()

    async def submit_batch_zinc(self, batch_id, client, address, sandbox):
        """Explicit-only submission; ambiguous responses never cause automatic retries."""
        async with self.lock:
            batch = self.store.data.get("batches", {}).get(batch_id)
            if not batch or batch["status"] != "ready" or "zinc_environment" in batch:
                raise ValueError("Batch must be ready for submission")
            orders = [self.store.data["orders"].get(i) for i in batch["order_ids"]]
            if any(o is None or o.get("status") not in ("queued", "approved") or
                   o.get("batch_id") != batch_id or "zinc_environment" in o for o in orders):
                raise ValueError("Batch contains an invalid or changed order")
            if not 1 <= len(orders) <= 10 or len({o["product_key"] for o in orders}) != len(orders):
                raise ValueError("Batch must contain 1–10 distinct catalog products")
            product_keys = {o["product_key"] for o in orders}
            if any(o["product_key"] in product_keys and o["id"] not in batch["order_ids"]
                   and any(self._purchase_blocker(o, member) for member in orders if member["product_key"] == o["product_key"])
                   for o in self.store.data["orders"].values()):
                raise ValueError("Another order for a batch product is active or uncertain")
            self._check_shopping_items_before_submission(orders)
            batch["status"] = "submitting"
            batch["submitted_at"] = dt_util.utcnow().isoformat()
            batch["zinc_environment"] = "sandbox" if sandbox else "live"
            for order in orders:
                order["status"] = "submitting"
                order["submitted_at"] = batch["submitted_at"]
                order["zinc_environment"] = batch["zinc_environment"]
            await self.store.save()
        self.publish()
        response = None
        try:
            response = await client.create_batch_order(batch, orders, address)
            if not isinstance(response, dict) or not (response.get("id") or response.get("order_id")):
                raise ValueError("Zinc response missing order ID; reconcile before retrying")
            details = fulfillment_snapshot(response)
        except Exception as err:
            async with self.lock:
                batch["status"] = "submission_unknown"
                if isinstance(response, dict) and isinstance(response.get("id"), str):
                    batch["zinc_order_id"] = response["id"]
                if safe_code(getattr(err, "code", None)):
                    batch["submission_error_code"] = safe_code(err.code)
                batch["note"] = "Reconcile with Zinc before retrying. Never resubmit blindly."
                for order in orders:
                    order["status"] = "submission_unknown"
                await self.store.save()
            self.publish()
            emit(self, "attention", f"Batch {batch_id} needs reconciliation. An order may already exist. Check Zinc before any new purchase; do not submit again or clear saved history.", batch_id=batch_id)
            raise
        async with self.lock:
            batch["fulfillment"] = details
            batch["zinc_order_id"] = response.get("id") or response.get("order_id")
            batch["status"] = response.get("status", "submitted")
            batch["note"] = "Zinc accepted batch request; fulfillment may still be pending."
            for order in orders:
                order["status"] = batch["status"]
                order["zinc_order_id"] = batch.get("zinc_order_id")
                order["zinc_environment"] = batch["zinc_environment"]
            await self.store.save()
            report = dict(batch)
        self.publish()
        emit(self, "order_status", f"{'Sandbox simulation' if sandbox else 'Live order'}: batch {batch_id} is {report['status']}. Placement is not delivery.", batch_id=batch_id)
        return report

    async def reconcile_shopping_list(self):
        """Recover missed source events and retry still-open, previously blocked requests."""
        items = shopping_items(self.hass)
        if items is not None:
            await self.handle_shopping_event("update_list", items=items)

    async def refresh_pending_batches(self, client, environment):
        """Bounded, serialized GET-only polling; failures never trigger a submission."""
        if self.refresh_lock.locked():
            return
        async with self.refresh_lock:
            async with self.lock:
                candidates = []
                for batch in self.store.data.get("batches", {}).values():
                    if not batch.get("zinc_order_id") or batch.get("zinc_environment") != environment:
                        continue
                    orders = [self.store.data["orders"].get(key) for key in batch["order_ids"]]
                    terminal = True
                    for order in orders:
                        item = mapped_item(order, batch.get("fulfillment", {}), orders) if order else None
                        delivered = item_delivery_confirmed(item, batch.get("fulfillment", {}))
                        if not item or (not delivered and item["status"] not in ("failed", "skipped", "cancelled")):
                            terminal = False
                        elif delivered and not order.get("shopping_list_completed_at"):
                            terminal = False
                    if not terminal:
                        candidates.append(batch["id"])
            if not candidates:
                return
            start = self._refresh_cursor % len(candidates)
            selected = (candidates[start:] + candidates[:start])[:10]
            self._refresh_cursor = start + len(selected)
            for batch_id in selected:
                try:
                    await self.refresh_batch_zinc(batch_id, client)
                except Exception:
                    # Provider errors may contain private data; retain only a safe indicator.
                    async with self.lock:
                        had_error = self.store.data["batches"][batch_id].get("refresh_error", False)
                        self.store.data["batches"][batch_id]["refresh_error"] = True
                        try:
                            await self.store.save()
                        except Exception:
                            _LOGGER.warning("Could not persist Zinc refresh failure indicator")
                    self.publish()
                    if not had_error:
                        emit(self, "attention", f"Status refresh failed for batch {batch_id}. The saved order remains protected and tracking will retry. Do not place another order to resolve a tracking error.", batch_id=batch_id)
                    _LOGGER.warning("Zinc status refresh failed; saved order remains protected")

    async def refresh_batch_zinc(self, batch_id, client):
        async with self.lock:
            batch = self.store.data.get("batches", {}).get(batch_id)
            if not batch or not batch.get("zinc_order_id"):
                raise ValueError("Batch has no Zinc order ID")
            zinc_id = batch["zinc_order_id"]
        result = await client.get_order(zinc_id)
        if not isinstance(result, dict) or not isinstance(result.get("status"), str) or not result["status"]:
            raise ValueError("Zinc refresh response missing status; saved batch unchanged")
        if result.get("id") is not None and result["id"] != zinc_id:
            raise ValueError("Zinc refresh returned a different order ID; saved batch unchanged")
        status = result["status"]
        async with self.lock:
            old_status = batch["status"]
            old_outcome = batch.get("fulfillment", {}).get("outcome")
            delivered_before = {member_id for member_id in batch["order_ids"] if self.store.data["orders"][member_id].get("delivery_confirmed_at")}
            details = fulfillment_snapshot(result, batch.get("fulfillment"))
            previous_batch = deepcopy(batch)
            previous_orders = {key: deepcopy(self.store.data["orders"][key]) for key in batch["order_ids"]}
            batch["fulfillment"] = details
            batch.pop("refresh_error", None)
            batch["status"] = status
            batch["note"] = "Refreshed with Zinc; inspect retailer status for partial failures."
            batch["last_refreshed_at"] = dt_util.utcnow().isoformat()
            members = [self.store.data["orders"][key] for key in batch["order_ids"]]
            for member in members:
                member["status"] = status
                member["zinc_order_id"] = zinc_id
                member["zinc_environment"] = batch["zinc_environment"]
                provider = mapped_item(member, details, members)
                if item_delivery_confirmed(provider, details):
                    member.setdefault("delivery_confirmed_at", dt_util.utcnow().isoformat())
            try:
                await self.store.save()
            except Exception:
                batch.clear()
                batch.update(previous_batch)
                for key, previous in previous_orders.items():
                    self.store.data["orders"][key].clear()
                    self.store.data["orders"][key].update(previous)
                raise
        self.publish()
        if self.store.data.get("preferences", {}).get("auto_complete_delivered", True):
            async with self.lock:
                eligible = [order["id"] for order in members
                            if not order.get("shopping_list_completed_at")
                            and receipt_eligible(order, batch, members, delivered_only=True)]
            if eligible:
                try:
                    await self.complete_received_items(batch_id, eligible,
                        simulation=batch["zinc_environment"] == "sandbox", automatic=True)
                except Exception:
                    # Delivery was already saved. A list failure must not obscure that fact.
                    async with self.lock:
                        batch["list_sync_error"] = True
                        try:
                            await self.store.save()
                        except Exception:
                            _LOGGER.warning("Could not persist Shopping List synchronization failure")
                    self.publish()
                    _LOGGER.warning("Delivery saved; Shopping List synchronization needs retry")
        newly_delivered = [member for member in members if member.get("delivery_confirmed_at") and member["id"] not in delivered_before]
        mode = "Sandbox simulation" if batch["zinc_environment"] == "sandbox" else "Live order"
        if newly_delivered:
            names = ", ".join(member["name"] for member in newly_delivered)
            emit(self, "delivery", f"{mode}: delivery confirmed for {names}. Check the saved Shopping List result; failed or unmatched entries stay open.", batch_id=batch_id)
        elif old_status != status or (old_outcome != batch.get("fulfillment", {}).get("outcome") and batch.get("fulfillment", {}).get("outcome") in ("partial", "failed")):
            event = "attention" if status in ("failed", "order_failed", "submission_unknown") or batch.get("fulfillment", {}).get("outcome") in ("partial", "failed") else "order_status"
            emit(self, event, f"{mode}: batch {batch_id} is {status}. Order placed does not mean delivered. No failed line will be repurchased automatically.", batch_id=batch_id)
        return deepcopy(batch)

    async def complete_received_items(self, batch_id, order_ids, simulation, context=None, automatic=False):
        """Complete exact source IDs after delivery, or an explicit test receipt."""
        if not order_ids or len(order_ids) != len(set(order_ids)) or len(order_ids) > 10:
            raise ValueError("Select 1–10 distinct order lines")
        async with self.shopping_lock:
            async with self.lock:
                batch = self.store.data.get("batches", {}).get(batch_id)
                expected = "sandbox" if simulation else "live"
                if not batch or batch.get("zinc_environment") != expected:
                    raise ValueError("Batch environment does not match receipt mode")
                orders = [self.store.data["orders"][key] for key in batch["order_ids"]]
                selected = [self.store.data["orders"].get(key) for key in order_ids]
                if any(order is None or order["id"] not in batch["order_ids"]
                       or not receipt_eligible(order, batch, orders, delivered_only=automatic) for order in selected):
                    raise ValueError("A selected line is not confirmed successful/delivered, or its product mapping is ambiguous")
            results = []
            for order in selected:
                if automatic and order.get("shopping_list_completed_at"):
                    results.append({"order_id": order["id"], "status": "already_recorded"})
                    continue
                items = shopping_items(self.hass)
                current = next((item for item in items or [] if str(item["id"]) == order["shopping_item_id"]), None)
                result = {"order_id": order["id"], "status": "skipped_missing"}
                if items is None:
                    result["status"] = "source_unavailable"
                elif current is not None:
                    labels = {norm(order["name"]), norm(order.get("shopping_item_name", order["name"]))}
                    if norm(current.get("name") or "") not in labels:
                        result["status"] = "skipped_renamed"
                    elif current.get("complete"):
                        result["status"] = "already_complete"
                    else:
                        entity_id = shopping_entity_for_item(self.hass, order["shopping_item_id"])
                        if entity_id is None:
                            result["status"] = "source_unavailable"
                        else:
                            try:
                                await self.hass.services.async_call("todo", "update_item",
                                    {"item": order["shopping_item_id"], "status": "completed"},
                                    target={"entity_id": entity_id}, blocking=True, context=context)
                                result["status"] = "completed"
                            except Exception:
                                # Do not retain arbitrary integration error text or list payloads.
                                result["status"] = "list_update_failed"
                results.append(result)
            async with self.lock:
                previous_error = batch.get("list_sync_error")
                previous = deepcopy(batch.get("receipt_results"))
                previous_meta = {order["id"]: {key: order.get(key) for key in ("shopping_list_completed_at", "receipt_mode")} for order in selected}
                now = dt_util.utcnow().isoformat()
                merged = dict(batch.get("receipt_results", {}))
                for result in results:
                    merged[result["order_id"]] = {**result, "updated_at": now,
                        "mode": "automatic_delivery" if automatic else "sandbox_simulation" if simulation else "delivered_item"}
                    if result["status"] in ("completed", "already_complete"):
                        completed = self.store.data["orders"][result["order_id"]]
                        completed.setdefault("shopping_list_completed_at", now)
                        completed["receipt_mode"] = "sandbox_simulation" if simulation else "delivered_item"
                batch["receipt_results"] = merged
                batch["list_sync_error"] = any(result["status"] in ("source_unavailable", "list_update_failed") for result in merged.values())
                try:
                    await self.store.save()
                except Exception as err:
                    if previous_error is None:
                        batch.pop("list_sync_error", None)
                    else:
                        batch["list_sync_error"] = previous_error
                    if previous is None:
                        batch.pop("receipt_results", None)
                    else:
                        batch["receipt_results"] = previous
                    for order in selected:
                        for key, value in previous_meta[order["id"]].items():
                            if value is None:
                                order.pop(key, None)
                            else:
                                order[key] = value
                    raise ValueError("Shopping List items may already be complete, but receipt metadata could not be saved. Reload before retrying; no purchase was submitted.") from err
            self.publish()
            return {"batch_id": batch_id, "simulation": simulation, "results": results}
