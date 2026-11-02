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


def shopping_entity_for_item(hass, item_id):
    """Find an exact built-in to-do entity; never complete by a possibly duplicate name."""
    from homeassistant.helpers import entity_registry as er
    entries = [entry for entry in hass.config_entries.async_entries("shopping_list")
               if entry.state is ConfigEntryState.LOADED]
    source_ids = []
    for entry in entries:
        current = getattr(getattr(entry, "runtime_data", None), "items", None)
        if current is None and len(entries) == 1:
            current = getattr(hass.data.get("shopping_list"), "items", None)
        if isinstance(current, list) and any(str(item.get("id")) == item_id for item in current):
            source_ids.append(entry.entry_id)
    registry = er.async_get(hass)
    matches = [entry.entity_id for source_id in source_ids
               for entry in er.async_entries_for_config_entry(registry, source_id)
               if entry.entity_id.startswith("todo.") and entry.platform == "shopping_list" and entry.disabled_by is None]
    return matches[0] if len(matches) == 1 else None
