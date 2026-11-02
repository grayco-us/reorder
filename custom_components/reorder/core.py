"""Catalog matching and safe, simulated order queue."""
import asyncio
import logging
from datetime import timedelta
from uuid import uuid4
from urllib.parse import urlparse
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from .notifications import async_notify
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

    def publish(self):
        self.hass.bus.async_fire(EVENT_UPDATED)

    async def upsert_product(self, name, aliases, retailer, product_id, quantity, max_price, cooldown_hours, enabled, substitutes=None):
        key = norm(name)
        substitutes = validated_substitutes(product_id.strip(), substitutes)
        if substitutes and retailer != "zinc":
            raise ValueError("Substitutions currently require Zinc products")
        async with self.lock:
            self.store.data["products"][key] = {
                "name": name.strip(), "aliases": sorted(set(norm(s) for s in aliases if norm(s))),
                "retailer": retailer, "product_id": product_id.strip(), "quantity": quantity,
                "max_price": max_price, "cooldown_hours": cooldown_hours, "enabled": enabled,
                "substitutes": substitutes,
            }
            await self.store.save()
        self.publish()

    async def remove_product(self, name):
        async with self.lock:
            self.store.data["products"].pop(norm(name), None)
            await self.store.save()
        self.publish()

    async def match_new_item(self, item):
        if not isinstance(item, dict) or not item.get("name") or item.get("complete"):
            return
        label = norm(item["name"])
        item_id = str(item.get("id") or "")
        if not item_id:
            _LOGGER.warning("Ignoring shopping-list item missing id")
            return
        async with self.lock:
            if item_id in self.store.data["seen_items"]:
                return
            matches = [p for key, p in self.store.data["products"].items()
                       if p["enabled"] and label in {key, *p["aliases"]}]
            # Avoid ambiguity if aliases overlap between products.
            if len(matches) != 1:
                return
            product = matches[0]
            now = dt_util.utcnow()
            prior = [o for o in self.store.data["orders"].values() if o["product_key"] == norm(product["name"])]
            blocked = any(o["status"] in ({"queued", "approved"} | ACTIVE_PURCHASE_STATUSES) for o in prior)
            if not blocked:
                cutoff = now - timedelta(hours=product["cooldown_hours"])
                blocked = any(o["created_at"] >= cutoff.isoformat() for o in prior)
            if blocked:
                _LOGGER.info("Skipped duplicate/cooldown order for %s", product["name"])
                return
            order_id = uuid4().hex[:12]
            self.store.data["orders"][order_id] = {
                "id": order_id, "product_key": norm(product["name"]),
                "name": product["name"], "retailer": product["retailer"],
                "product_id": product["product_id"], "quantity": product["quantity"],
                "max_price": product["max_price"], "status": "queued",
                "substitutes": list(product.get("substitutes", [])), "substitution_index": 0,
                "shopping_item_id": item_id, "created_at": now.isoformat(),
                "note": "Queued locally; no retailer API was called.",
            }
            self.store.data["seen_items"].append(item_id)
            self.store.data["seen_items"] = self.store.data["seen_items"][-2000:]
            await self.store.save()
        self.publish()
        async_notify(
            self.hass,
            f"{product['name']} matched your auto-reorder catalog. "
            f"Queued as {order_id}; no purchase was made.",
            title="Reorder — test order", notification_id=f"reorder_{order_id}")

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
            if any(o["product_key"] == order["product_key"] and o["status"] in ACTIVE_PURCHASE_STATUSES for o in self.store.data["orders"].values() if o["id"] != order_id):
                raise ValueError("Another order for this product is already active")
            order["status"] = "submitting"
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
                   and o["status"] in ACTIVE_PURCHASE_STATUSES
                   for o in self.store.data["orders"].values()):
                raise ValueError("Another order for a batch product is active or uncertain")
            batch["status"] = "submitting"
            batch["zinc_environment"] = "sandbox" if sandbox else "live"
            for order in orders:
                order["status"] = "submitting"
                order["zinc_environment"] = batch["zinc_environment"]
            await self.store.save()
        self.publish()
        try:
            response = await client.create_batch_order(batch, orders, address)
            if not isinstance(response, dict) or not (response.get("id") or response.get("order_id")):
                raise ValueError("Zinc response missing order ID; reconcile before retrying")
        except Exception:
            async with self.lock:
                batch["status"] = "submission_unknown"
                batch["note"] = "Reconcile with Zinc before retrying. Never resubmit blindly."
                for order in orders:
                    order["status"] = "submission_unknown"
                await self.store.save()
            self.publish()
            raise
        async with self.lock:
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
        return report

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
            batch["status"] = status
            batch["note"] = "Refreshed with Zinc; inspect retailer status for partial failures."
            batch["last_refreshed_at"] = dt_util.utcnow().isoformat()
            for item_id in batch["order_ids"]:
                self.store.data["orders"][item_id]["status"] = status
            await self.store.save()
            report = dict(batch)
        self.publish()
        return report
