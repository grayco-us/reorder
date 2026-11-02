"""Read the built-in Shopping List across supported Home Assistant layouts."""
from copy import deepcopy

from homeassistant.config_entries import ConfigEntryState


def shopping_items(hass):
    """Return a copied current list, or None if its state cannot be established."""
    entries = [entry for entry in hass.config_entries.async_entries("shopping_list")
               if entry.state is ConfigEntryState.LOADED]
    if not entries:
        return None
    legacy = hass.data.get("shopping_list")
    items = getattr(legacy, "items", None)
    if isinstance(items, list):
        return deepcopy(items)
    sources = []
    for entry in entries:
        runtime = getattr(entry, "runtime_data", None)
        current = getattr(runtime, "items", None)
        if isinstance(current, list):
            sources.extend(current)
    if sources or any(isinstance(getattr(getattr(entry, "runtime_data", None), "items", None), list)
                      for entry in entries):
        return deepcopy(sources)
    return None
