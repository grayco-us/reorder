"""Reorder: shopping list order queue with optional Zinc integration."""
from copy import deepcopy
import logging

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol
from .frontend import async_remove_panel, async_setup_panel
from .notifications import async_notify
from .product_config import PRODUCT_SCHEMA
from .shopping import shopping_items
from .const import DOMAIN
from .store import ReorderStore
from .core import ReorderEngine
from .review import review_matches
from .zinc import ZincClient
from .batch import batch_status_label, cancel_batch, create_batch, preview, review_batch, scheduled_due
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta
from homeassistant.util import dt as dt_util
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = ReorderStore(hass)
    await store.load()
    engine = ReorderEngine(hass, store)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = engine

    async def options_updated(_hass, _entry):
        engine.publish()

    entry.async_on_unload(entry.add_update_listener(options_updated))

    @callback
    def handle_shopping_event(event):
        data = event.data
        action = data.get("action")
        if action in ("add", "update", "complete", "remove", "clear", "update_list"):
            # Source item dictionaries are mutable; capture the event at receipt time.
            hass.async_create_task(engine.handle_shopping_event(action,
                deepcopy(data.get("item")), shopping_items(hass) if action in ("clear", "update_list") else None))

    unsub = hass.bus.async_listen("shopping_list_updated", handle_shopping_event)
    entry.async_on_unload(unsub)

    async def add_product(call: ServiceCall):
        try:
            await engine.upsert_product(**call.data)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def remove_product(call: ServiceCall):
        await engine.remove_product(call.data["name"])

    async def change_order(call: ServiceCall, status):
        try:
            await engine.change_status(call.data["order_id"], status)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def approve_order(call: ServiceCall):
        await change_order(call, "approved")

    async def cancel_order(call: ServiceCall):
        await change_order(call, "canceled")

    def zinc_settings():
        opts = entry.options
        key = opts.get("zinc_api_key", "")
        if not key:
            raise HomeAssistantError("Configure Zinc credentials first")
        if not key.startswith(("zn_test_", "zn_live_")):
            raise HomeAssistantError("Use a Zinc sandbox or live API key")
        is_sandbox = key.startswith("zn_test_")
        if not is_sandbox and not opts.get("zinc_live_enabled", False):
            raise HomeAssistantError("Live Zinc ordering is disabled")
        address_fields = ("first_name", "last_name", "address_line1", "city", "state", "postal_code", "phone_number")
        address = {field: opts.get("ship_" + field, "") for field in address_fields}
        if any(not value for value in address.values()):
            raise HomeAssistantError("Configure all required shipping address fields")
        address["country"] = "US"
        return ZincClient(async_get_clientsession(hass), key), address, is_sandbox

    async def submit_zinc(call: ServiceCall):
        client, address, sandbox = zinc_settings()
        if call.data["confirmation"] != ("SANDBOX" if sandbox else "PLACE LIVE ORDER"):
            raise HomeAssistantError("Explicit confirmation phrase required")
        try:
            await engine.submit_zinc(call.data["order_id"], client, address, sandbox)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def refresh_zinc(call: ServiceCall):
        client, _, sandbox = zinc_settings()
        order = engine.store.data["orders"].get(call.data["order_id"])
        if not order or order.get("zinc_environment") != ("sandbox" if sandbox else "live"):
            raise HomeAssistantError("Order not found in current Zinc environment")
        try:
            await engine.refresh_zinc(call.data["order_id"], client)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def next_substitution(call: ServiceCall):
        try:
            await engine.queue_next_substitution(call.data["order_id"])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def batch_preview(call: ServiceCall) -> ServiceResponse:
        report = preview(store.data)
        async_notify(
            hass,
            f"Your cart has {report['count']} eligible product line(s), with a combined spending limit of ${report['price_ceiling']:.2f}. "
            "Open Reorder → Queue to review and prepare a batch. Nothing has been purchased; this is not a price quote.",
            title="Reorder — Batch Preview", notification_id="reorder_batch_preview")
        return report

    async def prepare_batch(call: ServiceCall) -> ServiceResponse:
        try:
            batch = await create_batch(engine, max_items=call.data.get("max_items", 10))
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        async_notify(
            hass,
            f"Batch {batch['id']} contains {len(batch['order_ids'])} product lines. "
            f"Combined spending limit ${batch['max_price']:.2f}. Open Reorder to review saved products and quantities before explicitly submitting. No order placed.",
            title="Reorder — Batch Ready", notification_id=f"reorder_batch_{batch['id']}")
        return dict(batch)

    async def batch_review(call: ServiceCall) -> ServiceResponse:
        try:
            async with engine.lock:
                report = review_batch(store.data, call.data["batch_id"])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        lines = [
            f"- {order['name']}: quantity {order['quantity']}, ceiling ${order['max_price']:.2f}\n"
            f"  {order['product_id']}"
            for order in report["orders"]
        ]
        async_notify(
            hass,
            f"Batch {report['id']}: {report['status']}.\n\n"
            + "\n".join(lines)
            + f"\n\nTotal price ceiling: ${report['max_price']:.2f}. This is not a quote. "
            "Review only; this action does not submit or cancel an order.",
            title="Reorder — Batch Review", notification_id=f"reorder_batch_{report['id']}",
        )
        return report

    async def batch_cancel(call: ServiceCall) -> ServiceResponse:
        try:
            report = await cancel_batch(engine, call.data["batch_id"])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        async_notify(
            hass,
            f"Batch {report['id']} and its {report['count']} queued product lines were canceled locally. "
            "No purchase was made. These orders will not be included in another batch.",
            title="Reorder — Batch Canceled", notification_id=f"reorder_batch_{report['id']}",
        )
        return report

    def notify_batch_status(report, operation):
        mode = "Sandbox simulation" if report["zinc_environment"] == "sandbox" else "Live order"
        async_notify(
            hass,
            f"Batch {report['id']}: {batch_status_label(report['status'])} ({report['status']}). {mode}. "
            f"Zinc order ID: {report['zinc_order_id']}. "
            "Open Reorder for saved product outcomes and tracking. Order placed does not mean delivered; no list item is completed merely by placement.",
            title=f"Reorder — Batch {operation}",
            notification_id=f"reorder_batch_{report['id']}",
        )

    async def submit_batch(call: ServiceCall) -> ServiceResponse:
        client, address, sandbox = zinc_settings()
        if call.data["confirmation"] != ("SANDBOX" if sandbox else "PLACE LIVE ORDER"):
            raise HomeAssistantError("Explicit confirmation phrase required")
        if "review_token" in call.data and not review_matches(engine, entry, call.data["batch_id"], call.data["review_token"]):
            raise HomeAssistantError("Review changed or expired. Reload and review saved contents and connection settings again; no order was submitted.")
        try:
            report = await engine.submit_batch_zinc(call.data["batch_id"], client, address, sandbox)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        notify_batch_status(report, "Submitted")
        return report

    async def refresh_batch(call: ServiceCall) -> ServiceResponse:
        client, _, sandbox = zinc_settings()
        batch = store.data.get("batches", {}).get(call.data["batch_id"])
        if not batch or batch.get("zinc_environment") != ("sandbox" if sandbox else "live"):
            raise HomeAssistantError("Batch not found in current environment")
        try:
            report = await engine.refresh_batch_zinc(call.data["batch_id"], client)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        notify_batch_status(report, "Refreshed")
        return report

    async def check_scheduled(_now):
        # Reconcile missed events after restarts, and retry requests blocked by cooldown.
        try:
            await engine.reconcile_shopping_list()
        except Exception:
            _LOGGER.warning("Shopping List reconciliation failed; local work remains protected")
        key = entry.options.get("zinc_api_key", "")
        if key.startswith(("zn_test_", "zn_live_")):
            # GET-only status tracking does not need an address or permission to purchase.
            await engine.refresh_pending_batches(ZincClient(async_get_clientsession(hass), key),
                "sandbox" if key.startswith("zn_test_") else "live")
        settings = store.data.get("batch_settings", {})
        if scheduled_due(store.data, dt_util.utcnow(), hass.config.time_zone):
            # Only prepare a batch, NEVER submit or spend funds on a schedule.
            # One batch per local date, persisted against restarts.
            local_date = dt_util.as_local(dt_util.utcnow()).date().isoformat()
            if settings.get("last_scheduled_date") == local_date:
                return
            try:
                batch = await create_batch(engine)
            except ValueError:
                return
            settings["last_scheduled_date"] = local_date
            await store.save()
            async_notify(
                hass,
                f"Batch {batch['id']} is ready to review. No purchase was made.",
                title="Reorder — Scheduled Batch", notification_id=f"reorder_batch_{batch['id']}")

    unsub_batch = async_track_time_interval(hass, check_scheduled, timedelta(minutes=15))
    entry.async_on_unload(unsub_batch)

    hass.services.async_register(
        DOMAIN, "preview_batch", batch_preview, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, "prepare_batch", prepare_batch, schema=vol.Schema({
        vol.Optional("max_items", default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=10))}),
        supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "review_batch", batch_review, schema=vol.Schema({
        vol.Required("batch_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "cancel_batch", batch_cancel, schema=vol.Schema({
        vol.Required("batch_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "submit_batch_zinc", submit_batch, schema=vol.Schema({
        vol.Required("batch_id"): cv.string, vol.Required("confirmation"): cv.string,
        vol.Optional("review_token"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "refresh_batch_zinc", refresh_batch, schema=vol.Schema({
        vol.Required("batch_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL)

    hass.services.async_register(DOMAIN, "queue_next_substitution", next_substitution,
                                 schema=vol.Schema({vol.Required("order_id"): cv.string}))

    hass.services.async_register(DOMAIN, "submit_zinc", submit_zinc, schema=vol.Schema({
        vol.Required("order_id"): cv.string, vol.Required("confirmation"): cv.string}))
    hass.services.async_register(DOMAIN, "refresh_zinc", refresh_zinc, schema=vol.Schema({
        vol.Required("order_id"): cv.string}))

    hass.services.async_register(DOMAIN, "set_product", add_product, schema=PRODUCT_SCHEMA)
    hass.services.async_register(DOMAIN, "remove_product", remove_product,
                                 schema=vol.Schema({vol.Required("name"): cv.string}))
    hass.services.async_register(DOMAIN, "approve_order", approve_order,
                                 schema=vol.Schema({vol.Required("order_id"): cv.string}))
    hass.services.async_register(DOMAIN, "cancel_order", cancel_order,
                                 schema=vol.Schema({vol.Required("order_id"): cv.string}))
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor", "select", "button"])
    try:
        await async_setup_panel(hass, entry)
    except Exception:
        # Existing services and automations remain usable if frontend setup fails.
        _LOGGER.exception("Reorder sidebar could not be registered; existing actions remain available")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, ["sensor", "select", "button"]):
        return False
    async_remove_panel(hass, entry)
    for service in ("set_product", "remove_product", "approve_order", "cancel_order", "submit_zinc", "refresh_zinc", "queue_next_substitution", "preview_batch", "prepare_batch", "submit_batch_zinc", "refresh_batch_zinc", "review_batch", "cancel_batch"):
        hass.services.async_remove(DOMAIN, service)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
