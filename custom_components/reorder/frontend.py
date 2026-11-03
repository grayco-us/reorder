"""Bundled sidebar interface and a deliberately credential-free local data API."""
from copy import deepcopy
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, callback
from homeassistant.loader import async_get_integration

from .batch import batch_status_label, preview, review_batch
from .const import DOMAIN
from .core import norm
from .fulfillment import mapped_item, receipt_eligible, item_delivery_confirmed
from .shopping import shopping_items
from .review import review_token
from .notifications import settings_for, destinations, async_deliver
from .product_config import PRODUCT_SCHEMA, PREFERENCES_SCHEMA, NOTIFICATION_SCHEMA, CART_EDIT_SCHEMA

PANEL_PATH = "reorder-app"
ASSET_PATH = "/reorder-assets"
_STATIC_KEY = "reorder_static_registered"
_WS_KEY = "reorder_panel_ws_registered"
_PANEL_KEY = "reorder_sidebar_owner"


def panel_data(engine, entry):
    """Copy only fields the app needs; never expose options or provider responses."""
    key = entry.options.get("zinc_api_key", "")
    mode = ("Sandbox" if key.startswith("zn_test_") else
            "Live enabled" if key.startswith("zn_live_") and entry.options.get("zinc_live_enabled", False) else
            "Live disabled" if key.startswith("zn_live_") else
            "Not configured" if not key else "Invalid key")
    environment = "sandbox" if mode == "Sandbox" else "live" if mode in ("Live enabled", "Live disabled") else None
    batches = []
    current_items = shopping_items(engine.hass)
    current_by_id = {str(item["id"]): item for item in current_items or []}
    fields = ("id", "status", "created_at", "max_price", "zinc_environment",
              "zinc_order_id", "last_refreshed_at", "canceled_at", "invalidated_at", "fulfillment", "receipt_results", "submission_error_code", "refresh_error", "list_sync_error")
    for batch in sorted(engine.store.data.get("batches", {}).values(),
                        key=lambda item: item["created_at"], reverse=True):
        item = {field: deepcopy(batch[field]) for field in fields if field in batch}
        item["status_label"] = batch_status_label(batch["status"])
        try:
            report = review_batch(engine.store.data, batch["id"])
            item["orders"] = report["orders"]
            item["review_error"] = None
        except (ValueError, KeyError, TypeError):
            item["orders"] = []
            item["review_error"] = "Saved product details are incomplete. No order was changed."
        members = [engine.store.data["orders"].get(order_id) for order_id in batch["order_ids"]]
        members_unsubmitted = bool(members) and all(
            member is not None and member.get("status") in ("queued", "approved")
            and "zinc_environment" not in member and not member.get("zinc_order_id")
            for member in members
        )
        item["can_cancel"] = (members_unsubmitted and batch["status"] == "ready" and "zinc_environment" not in batch
                              and not batch.get("zinc_order_id") and not item["review_error"])
        item["can_refresh"] = bool(environment and batch.get("zinc_order_id")
                                    and batch.get("zinc_environment") == environment)
        item["can_submit_sandbox"] = bool(mode == "Sandbox" and item["can_cancel"])
        item["can_submit_live"] = bool(mode == "Live enabled" and item["can_cancel"])
        if item["can_submit_live"]:
            item["review_token"] = review_token(engine, entry, batch["id"])
        item["receivable_order_ids"] = []
        raw_orders = [member for member in members if member is not None]
        for order in item["orders"]:
            original = engine.store.data["orders"].get(order["id"])
            if original is None:
                continue
            provider = mapped_item(original, batch.get("fulfillment", {}), raw_orders)
            order["provider_item"] = deepcopy(provider)
            order["delivery_confirmed"] = item_delivery_confirmed(provider, batch.get("fulfillment", {}))
            current = current_by_id.get(original.get("shopping_item_id"))
            labels = {norm(original["name"]), norm(original.get("shopping_item_name", original["name"]))}
            list_status = ("not_linked" if not original.get("shopping_item_id") else "unavailable" if current_items is None
                           else "removed" if current is None else "renamed" if norm(current.get("name") or "") not in labels
                           else "complete" if current.get("complete") else "pending")
            order["shopping_list_status"] = list_status
            order["receipt_result"] = deepcopy(batch.get("receipt_results", {}).get(order["id"]))
            order["receipt_recorded"] = bool(original.get("shopping_list_completed_at"))
            if (mode in ("Sandbox", "Live enabled") and environment == batch.get("zinc_environment") and list_status == "pending"
                    and receipt_eligible(original, batch, raw_orders)):
                item["receivable_order_ids"].append(order["id"])
        item["item_mapping_incomplete"] = batch["status"] in ("order_placed", "order_failed", "failed") and any(order.get("provider_item") is None for order in item["orders"])
        reasons = []
        if item["review_error"]:
            reasons.append("saved_details")
        if batch["status"] == "submission_unknown":
            reasons.append("unknown_with_id" if batch.get("zinc_order_id") else "unknown_without_id")
        if batch.get("refresh_error"):
            reasons.append("refresh_failed")
        if batch.get("list_sync_error"):
            reasons.append("list_sync_failed")
        if batch.get("zinc_order_id") and batch.get("zinc_environment") != environment:
            reasons.append("environment_mismatch")
        details = batch.get("fulfillment", {})
        if batch["status"] in ("failed", "order_failed") or details.get("outcome") in ("partial", "failed"):
            reasons.append("partial_failure" if details.get("outcome") == "partial" else "order_failed")
        if item["item_mapping_incomplete"]:
            reasons.append("item_mapping")
        if any((order.get("receipt_result") or {}).get("status") in ("skipped_missing", "skipped_renamed") for order in item["orders"]):
            reasons.append("source_changed")
        shipments = details.get("shipments", [])
        if shipments and all(shipment.get("status") == "delivered" for shipment in shipments) and any(
                order.get("provider_item") and order["provider_item"]["status"] in ("ordered", "shipped", "available_for_pickup")
                and not order["delivery_confirmed"] for order in item["orders"]):
            reasons.append("delivery_mapping")
        if (not engine.store.data.get("preferences", {}).get("auto_complete_delivered", True)
                and any(order["delivery_confirmed"] and order["shopping_list_status"] == "pending" and not order["receipt_recorded"] for order in item["orders"])):
            reasons.append("manual_receipt")
        item["attention_reasons"] = reasons
        item["needs_attention"] = bool(reasons)
        item["progress"] = {"total": len(item["orders"]),
            "delivered": sum(bool(order.get("delivery_confirmed")) for order in item["orders"]),
            "failed": sum((order.get("provider_item") or {}).get("status") in ("failed", "skipped", "cancelled") for order in item["orders"]),
            "list_complete": sum(order.get("shopping_list_status") == "complete" for order in item["orders"])}
        if item["progress"]["total"] and batch["status"] == "order_placed":
            if item["progress"]["delivered"] == item["progress"]["total"]:
                item["status_label"] = "Delivered"
            elif item["progress"]["delivered"]:
                item["status_label"] = "Partially delivered"
        batches.append(item)
    cart = preview(engine.store.data)
    for line in cart["orders"]:
        original = engine.store.data["orders"][line["id"]]
        line["can_edit"] = (not original.get("batch_id") and "zinc_environment" not in original and not original.get("zinc_order_id"))
    return {
        "mode": mode, "batches": batches, "queue": cart,
        "product_count": sum(bool(product["enabled"]) for product in engine.store.data["products"].values()),
        "shopping_list_ready": any(source.state is ConfigEntryState.LOADED for source in
                                   engine.hass.config_entries.async_entries("shopping_list")),
        "intake_events": deepcopy(engine.intake_events),
        "preferences": {**engine.store.data.get("batch_settings", {}),
                        "sync_shopping_list": engine.store.data.get("preferences", {}).get("sync_shopping_list", True),
                        "auto_complete_delivered": engine.store.data.get("preferences", {}).get("auto_complete_delivered", True),
                        "notification_settings": settings_for(engine)},
        "notification_destinations": destinations(engine.hass),
        "notification_delivery": deepcopy(engine.notification_delivery),
        "catalog": [{**{field: product.get(field, [] if field in ("aliases", "substitutes") else None)
                         for field in ("name", "aliases", "retailer", "product_id", "quantity", "max_price", "cooldown_hours", "enabled", "substitutes")},
                     "can_rename": not any(order["product_key"] == key for order in engine.store.data["orders"].values())}
                    for key, product in engine.store.data["products"].items()],
    }


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/panel",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def websocket_panel(hass, connection, msg):
    """Authenticated admin-only local snapshots; reading never contacts Zinc."""
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(msg["id"], "unauthorized", "Administrator access is required")
        return
    engine = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if engine is None or entry is None:
        connection.send_error(msg["id"], "not_found", "Reorder is not loaded")
        return
    async with engine.lock:
        data = panel_data(engine, entry)
    connection.send_result(msg["id"], data)


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/product_save",
    vol.Required("entry_id"): str,
    vol.Required("product"): PRODUCT_SCHEMA,
    vol.Optional("original_name"): str,
})
@websocket_api.async_response
async def websocket_product_save(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    data = dict(msg["product"])
    data.pop("create_only", None)
    data.pop("original_name", None)
    try:
        await engine.upsert_product(**data, original_name=msg.get("original_name"), create_only="original_name" not in msg)
    except (ValueError, vol.Invalid) as err:
        connection.send_error(msg["id"], "invalid_product", str(err))
        return
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/product_remove",
    vol.Required("entry_id"): str,
    vol.Required("name"): str,
})
@websocket_api.async_response
async def websocket_product_remove(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    await engine.remove_product(msg["name"])
    connection.send_result(msg["id"], {"removed": True})


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/preferences_save",
    vol.Required("entry_id"): str,
    vol.Required("preferences"): PREFERENCES_SCHEMA,
})
@websocket_api.async_response
async def websocket_preferences_save(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    try:
        result = await engine.update_preferences(**msg["preferences"])
    except (ValueError, vol.Invalid) as err:
        connection.send_error(msg["id"], "invalid_preferences", str(err))
        return
    connection.send_result(msg["id"], result)


def _manage_engine(hass, connection, msg):
    if connection.user is None or not connection.user.is_admin:
        connection.send_error(msg["id"], "unauthorized", "Administrator access is required")
        return None
    engine = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if engine is None:
        connection.send_error(msg["id"], "not_found", "Reorder is not loaded")
    return engine


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/cart_edit",
    vol.Required("entry_id"): str,
    vol.Required("item"): CART_EDIT_SCHEMA,
    vol.Optional("remove", default=False): bool,
})
@websocket_api.async_response
async def websocket_cart_edit(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    try:
        result = await engine.edit_cart(msg["item"], remove=msg["remove"])
    except (ValueError, vol.Invalid) as err:
        connection.send_error(msg["id"], "cart_changed", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/notifications_save",
    vol.Required("entry_id"): str,
    vol.Required("settings"): NOTIFICATION_SCHEMA,
})
@websocket_api.async_response
async def websocket_notifications_save(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    await engine.update_notifications(msg["settings"])
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/notification_test",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def websocket_notification_test(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    result = await async_deliver(engine, "cart_added",
        "This is a test of your saved notification destinations. No cart, batch, Shopping List item or purchase was changed.", test=True)
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/live_submit",
    vol.Required("entry_id"): str,
    vol.Required("batch_id"): str,
    vol.Required("confirmation"): vol.In(["PLACE LIVE ORDER"]),
    vol.Required("review_token"): str,
})
@websocket_api.async_response
async def websocket_live_submit(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if (entry is None or not entry.options.get("zinc_api_key", "").startswith("zn_live_")
            or not entry.options.get("zinc_live_enabled", False)):
        connection.send_error(msg["id"], "live_disabled", "Enable live purchasing with a live key before reviewing this order")
        return
    # Native service revalidates the seal after dispatch, before capturing the client.
    result = await hass.services.async_call(DOMAIN, "submit_batch_zinc",
        {"batch_id": msg["batch_id"], "confirmation": msg["confirmation"], "review_token": msg["review_token"]},
        blocking=True, return_response=True, context=Context(user_id=getattr(connection.user, "id", None)))
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/sandbox_submit",
    vol.Required("entry_id"): str,
    vol.Required("batch_id"): str,
    vol.Required("confirmation"): vol.In(["SANDBOX"]),
})
@websocket_api.async_response
async def websocket_sandbox_submit(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or not entry.options.get("zinc_api_key", "").startswith("zn_test_"):
        connection.send_error(msg["id"], "sandbox_required", "This app only submits sandbox orders. Configure a zn_test_ key.")
        return
    result = await hass.services.async_call(DOMAIN, "submit_batch_zinc",
        {"batch_id": msg["batch_id"], "confirmation": msg["confirmation"]}, blocking=True,
        return_response=True, context=Context(user_id=getattr(connection.user, "id", None)))
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "reorder/receive_items",
    vol.Required("entry_id"): str,
    vol.Required("batch_id"): str,
    vol.Required("order_ids"): [str],
    vol.Required("confirmation"): str,
})
@websocket_api.async_response
async def websocket_receive_items(hass, connection, msg):
    engine = _manage_engine(hass, connection, msg)
    if engine is None:
        return
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    key = entry.options.get("zinc_api_key", "") if entry else ""
    simulation = key.startswith("zn_test_")
    if not simulation and not (key.startswith("zn_live_") and entry.options.get("zinc_live_enabled", False)):
        connection.send_error(msg["id"], "mode_required", "Configure the matching sandbox/live environment before updating list items")
        return
    if msg["confirmation"] != ("SIMULATE RECEIPT" if simulation else "ITEMS RECEIVED"):
        connection.send_error(msg["id"], "confirmation_required", "Explicit receipt confirmation is required")
        return
    try:
        result = await engine.complete_received_items(msg["batch_id"], msg["order_ids"], simulation,
            context=Context(user_id=getattr(connection.user, "id", None)))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_receipt", str(err))
        return
    connection.send_result(msg["id"], result)


async def async_setup_panel(hass, entry):
    """Register assets once, with a cache-busted, integration-owned sidebar panel."""
    if not hass.data.get(_STATIC_KEY):
        await hass.http.async_register_static_paths([
            StaticPathConfig(ASSET_PATH, str(Path(__file__).parent / "www"), cache_headers=True)
        ])
        hass.data[_STATIC_KEY] = True
    if not hass.data.get(_WS_KEY):
        for handler in (websocket_panel, websocket_product_save, websocket_product_remove, websocket_preferences_save, websocket_sandbox_submit, websocket_receive_items, websocket_notification_test, websocket_notifications_save, websocket_live_submit, websocket_cart_edit):
            websocket_api.async_register_command(hass, handler)
        hass.data[_WS_KEY] = True
    if PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        raise ValueError("A panel already uses /reorder-app; Reorder will not replace it")
    integration = await async_get_integration(hass, DOMAIN)
    await panel_custom.async_register_panel(
        hass, frontend_url_path=PANEL_PATH, webcomponent_name="reorder-panel",
        sidebar_title="Reorder", sidebar_icon="mdi:cart-outline", require_admin=True,
        module_url=f"{ASSET_PATH}/reorder-panel.js?v={integration.version}",
        config={"entry_id": entry.entry_id},
    )
    hass.data[_PANEL_KEY] = entry.entry_id


@callback
def async_remove_panel(hass, entry):
    """Remove only the panel owned by this entry; keep static routes for reloads."""
    if hass.data.get(_PANEL_KEY) == entry.entry_id:
        panel = hass.data.get(frontend.DATA_PANELS, {}).get(PANEL_PATH)
        config = panel.config if panel is not None else {}
        if (config and config.get("entry_id") == entry.entry_id
                and config.get("_panel_custom", {}).get("name") == "reorder-panel"):
            frontend.async_remove_panel(hass, PANEL_PATH, warn_if_unknown=False)
        hass.data.pop(_PANEL_KEY, None)
