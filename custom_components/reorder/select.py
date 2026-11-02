"""Choose a saved batch for the native dashboard controls."""
from homeassistant.components.select import SelectEntity
from homeassistant.core import callback

from .batch import batch_status_label, review_batch
from .const import DOMAIN, EVENT_UPDATED


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ReorderBatchSelect(hass.data[DOMAIN][entry.entry_id], entry)])


class ReorderBatchSelect(SelectEntity):
    """Keep selection local to this running integration, never in order storage."""

    _attr_name = "Reorder batch"
    _attr_icon = "mdi:format-list-bulleted"
    _attr_should_poll = False

    def __init__(self, engine, entry):
        self.engine = engine
        self._attr_unique_id = f"{entry.entry_id}_batch_selection"

    def _choices(self):
        batches = self.engine.store.data.get("batches", {}).values()
        return {f"{batch['id']} — {batch_status_label(batch['status'])}": batch["id"] for batch in
                sorted(batches, key=lambda batch: batch["created_at"], reverse=True)}

    @property
    def options(self):
        return list(self._choices())

    @property
    def current_option(self):
        return next((label for label, batch_id in self._choices().items()
                     if batch_id == self.engine.selected_batch_id), None)

    @property
    def extra_state_attributes(self):
        attributes = {"batch_id": self.engine.selected_batch_id, "batch": None,
                      "orders": [], "review_error": None}
        if self.engine.selected_batch_id is None:
            return attributes
        try:
            report = review_batch(self.engine.store.data, self.engine.selected_batch_id)
        except (ValueError, KeyError, TypeError):
            attributes["review_error"] = "Saved batch details are incomplete or unavailable. No order was changed."
            return attributes
        fields = ("id", "status", "created_at", "max_price", "zinc_environment",
                  "zinc_order_id", "last_refreshed_at", "canceled_at")
        attributes["batch"] = {key: report[key] for key in fields if key in report}
        attributes["batch"]["status_label"] = batch_status_label(report["status"])
        attributes["orders"] = report["orders"]
        return attributes

    async def async_select_option(self, option):
        batch_id = self._choices().get(option)
        if batch_id is None:
            raise ValueError("Choose an existing batch")
        self.engine.selected_batch_id = batch_id
        self.engine.publish()

    async def async_added_to_hass(self):
        self.async_on_remove(self.hass.bus.async_listen(EVENT_UPDATED, self._updated))

    @callback
    def _updated(self, event):
        self.async_write_ha_state()
