"""Native review, read-only refresh, and local cancellation controls."""
from homeassistant.components.button import ButtonEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, EVENT_UPDATED


async def async_setup_entry(hass, entry, async_add_entities):
    engine = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ReorderBatchButton(engine, entry, "review_batch", "Review", "mdi:clipboard-text-search"),
        ReorderBatchButton(engine, entry, "refresh_batch_zinc", "Refresh", "mdi:refresh"),
        ReorderBatchButton(engine, entry, "cancel_batch", "Cancel", "mdi:cancel"),
    ])


class ReorderBatchButton(ButtonEntity):
    """Capture the selected ID at press time; service guards remain authoritative."""

    _attr_should_poll = False

    def __init__(self, engine, entry, service, label, icon):
        self.engine, self.entry, self.service = engine, entry, service
        self._attr_unique_id = f"{entry.entry_id}_{service}_button"
        self._attr_name = f"Reorder {label.lower()} batch"
        self._attr_icon = icon

    @property
    def available(self):
        batch = self.engine.store.data.get("batches", {}).get(self.engine.selected_batch_id)
        if batch is None:
            return False
        if self.service == "cancel_batch":
            return (batch["status"] == "ready" and "zinc_environment" not in batch
                    and not batch.get("zinc_order_id"))
        if self.service == "refresh_batch_zinc":
            key = self.entry.options.get("zinc_api_key", "")
            mode = "sandbox" if key.startswith("zn_test_") else "live" if key.startswith("zn_live_") else None
            return bool(mode and batch.get("zinc_order_id") and batch.get("zinc_environment") == mode)
        return True

    async def async_press(self):
        batch_id = self.engine.selected_batch_id
        if not self.available:
            raise HomeAssistantError("Select a batch eligible for this action")
        await self.hass.services.async_call(
            DOMAIN, self.service, {"batch_id": batch_id}, blocking=True,
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.hass.bus.async_listen(EVENT_UPDATED, self._updated))

    @callback
    def _updated(self, event):
        self.async_write_ha_state()
