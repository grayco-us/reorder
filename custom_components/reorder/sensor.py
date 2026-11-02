"""Dashboard entities for order queue and catalog."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from .const import DOMAIN, EVENT_UPDATED

async def async_setup_entry(hass, entry, async_add_entities):
    engine = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReorderSensor(engine, entry, "pending", "Queued orders"),
                        ReorderSensor(engine, entry, "catalog", "Approved products"),
                        ReorderSensor(engine, entry, "batches", "Prepared batches"),
                        ReorderSensor(engine, entry, "mode", "Reorder purchasing mode")])

class ReorderSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    def __init__(self, engine, entry, kind, label):
        self.engine, self.kind, self.entry = engine, kind, entry
        self._attr_name = label
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_icon = "mdi:cart-clock" if kind == "pending" else "mdi:package-variant"

    @property
    def native_value(self):
        if self.kind == "mode":
            key = self.entry.options.get("zinc_api_key", "")
            if not key:
                return "Not configured"
            if key.startswith("zn_test_"):
                return "Sandbox"
            if key.startswith("zn_live_"):
                return "Live enabled" if self.entry.options.get("zinc_live_enabled", False) else "Live disabled"
            return "Invalid key"
        if self.kind == "batches":
            return sum(b["status"] == "ready" for b in self.engine.store.data.get("batches", {}).values())
        if self.kind == "pending":
            return sum(o["status"] == "queued" for o in self.engine.store.data["orders"].values())
        return sum(p["enabled"] for p in self.engine.store.data["products"].values())

    @property
    def extra_state_attributes(self):
        if self.kind == "mode":
            return {"live_enabled": self.entry.options.get("zinc_live_enabled", False)}
        if self.kind == "batches":
            return {"batches": list(self.engine.store.data.get("batches", {}).values())[-25:],
                    "settings": self.engine.store.data.get("batch_settings", {})}
        if self.kind == "pending":
            return {"orders": [o for o in self.engine.store.data["orders"].values() if o["status"] == "queued"][-25:]}
        return {"products": list(self.engine.store.data["products"].values())[:100]}

    async def async_added_to_hass(self):
        self.async_on_remove(self.hass.bus.async_listen(EVENT_UPDATED, self._updated))

    @callback
    def _updated(self, event):
        self.async_write_ha_state()
