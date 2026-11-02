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
from .fulfillment import mapped_item, receipt_eligible
from .shopping import shopping_items
from .product_config import PRODUCT_SCHEMA, PREFERENCES_SCHEMA

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
    environment = "sandbox" if mode == "Sandbox" else "live" if mode == "Live enabled" else None
    batches = []
    current_items = shopping_items(engine.hass)
    current_by_id = {str(item["id"]): item for item in current_items or []}
    fields = ("id", "status", "created_at", "max_price", "zinc_environment",
              "zinc_order_id", "last_refreshed_at", "canceled_at", "invalidated_at", "fulfillment", "receipt_results", "submission_error_code")
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
        item["receivable_order_ids"] = []
        raw_orders = [member for member in members if member is not None]
        for order in item["orders"]:
            original = engine.store.data["orders"].get(order["id"])
            if original is None:
                continue
            provider = mapped_item(original, batch.get("fulfillment", {}), raw_orders)
            order["provider_item"] = deepcopy(provider)
            current = current_by_id.get(original.get("shopping_item_id"))
            labels = {norm(original["name"]), norm(original.get("shopping_item_name", original["name"]))}
            list_status = ("not_linked" if not original.get("shopping_item_id") else "unavailable" if current_items is None
                           else "removed" if current is None else "renamed" if norm(current.get("name") or "") not in labels
                           else "complete" if current.get("complete") else "pending")
            order["shopping_list_status"] = list_status
            if (environment == batch.get("zinc_environment") and list_status == "pending"
                    and receipt_eligible(original, batch, raw_orders)):
                item["receivable_order_ids"].append(order["id"])
        item["item_mapping_incomplete"] = batch["status"] in ("order_placed", "order_failed", "failed") and any(order.get("provider_item") is None for order in item["orders"])
        batches.append(item)
    return {
        "mode": mode, "batches": batches, "queue": preview(engine.store.data),
        "product_count": sum(bool(product["enabled"]) for product in engine.store.data["products"].values()),
        "shopping_list_ready": any(source.state is ConfigEntryState.LOADED for source in
                                   engine.hass.config_entries.async_entries("shopping_list")),
        "intake_events": deepcopy(engine.intake_events),
        "preferences": {**engine.store.data.get("batch_settings", {}),
                        "sync_shopping_list": engine.store.data.get("preferences", {}).get("sync_shopping_list", True)},
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
        for handler in (websocket_panel, websocket_product_save, websocket_product_remove, websocket_preferences_save, websocket_sandbox_submit, websocket_receive_items):
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
