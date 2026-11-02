"""Bundled sidebar interface and a deliberately credential-free local data API."""
from copy import deepcopy
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.loader import async_get_integration

from .batch import batch_status_label, preview, review_batch
from .const import DOMAIN

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
    fields = ("id", "status", "created_at", "max_price", "zinc_environment",
              "zinc_order_id", "last_refreshed_at", "canceled_at")
    for batch in sorted(engine.store.data.get("batches", {}).values(),
                        key=lambda item: item["created_at"], reverse=True):
        item = {field: batch[field] for field in fields if field in batch}
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
        batches.append(item)
    return {
        "mode": mode, "batches": batches, "queue": preview(engine.store.data),
        "product_count": sum(bool(product["enabled"]) for product in engine.store.data["products"].values()),
        "shopping_list_ready": any(source.state is ConfigEntryState.LOADED for source in
                                   engine.hass.config_entries.async_entries("shopping_list")),
        "intake_events": deepcopy(engine.intake_events),
        "catalog": [{"name": product["name"], "aliases": list(product["aliases"]),
                     "retailer": product["retailer"], "enabled": product["enabled"]}
                    for product in engine.store.data["products"].values()],
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


async def async_setup_panel(hass, entry):
    """Register assets once, with a cache-busted, integration-owned sidebar panel."""
    if not hass.data.get(_STATIC_KEY):
        await hass.http.async_register_static_paths([
            StaticPathConfig(ASSET_PATH, str(Path(__file__).parent / "www"), cache_headers=True)
        ])
        hass.data[_STATIC_KEY] = True
    if not hass.data.get(_WS_KEY):
        websocket_api.async_register_command(hass, websocket_panel)
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
