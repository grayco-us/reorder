"""Reorder: shopping list order queue with optional Zinc integration."""
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol
from .const import DOMAIN
from .store import ReorderStore
from .core import ReorderEngine
from .zinc import ZincClient
from homeassistant.helpers.aiohttp_client import async_get_clientsession

PRODUCT_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Optional("aliases", default=[]): [cv.string],
    vol.Required("retailer"): vol.In(["zinc", "kroger", "other"]),
    vol.Required("product_id"): cv.string,
    vol.Optional("substitutes", default=[]): vol.All([cv.url], vol.Length(max=2)),
    vol.Optional("quantity", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    vol.Optional("max_price", default=50): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
    vol.Optional("cooldown_hours", default=168): vol.All(vol.Coerce(int), vol.Range(min=1)),
    vol.Optional("enabled", default=True): cv.boolean,
})

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = ReorderStore(hass)
    await store.load()
    engine = ReorderEngine(hass, store)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = engine

    @callback
    def handle_shopping_event(event):
        data = event.data
        if data.get("action") == "add":
            hass.async_create_task(engine.match_new_item(data.get("item")))

    unsub = hass.bus.async_listen("shopping_list_updated", handle_shopping_event)
    entry.async_on_unload(unsub)

    async def add_product(call: ServiceCall):
        await engine.upsert_product(**call.data)

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
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, ["sensor"]):
        return False
    for service in ("set_product", "remove_product", "approve_order", "cancel_order", "submit_zinc", "refresh_zinc", "queue_next_substitution"):
        hass.services.async_remove(DOMAIN, service)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
