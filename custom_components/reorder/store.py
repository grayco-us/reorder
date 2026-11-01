"""Persist product catalog, order queue and idempotency state."""
from copy import deepcopy
from homeassistant.helpers.storage import Store
from .const import STORAGE_VERSION, STORAGE_KEY

DEFAULT = {"products": {}, "orders": {}, "seen_items": []}

class ReorderStore:
    def __init__(self, hass):
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data = deepcopy(DEFAULT)

    async def load(self):
        saved = await self._store.async_load()
        if isinstance(saved, dict):
            self.data.update({key: saved[key] for key in DEFAULT if key in saved})

    async def save(self):
        await self._store.async_save(self.data)
