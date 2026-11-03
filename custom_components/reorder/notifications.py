"""Best-effort notifications for actions whose results are stored separately."""
import logging
import re

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


@callback
def async_notify(
    hass: HomeAssistant, message: str, *, title: str, notification_id: str
) -> None:
    """Keep optional presentation failures separate from persisted action results."""
    engines = hass.data.get("reorder", {})
    engine = next((value for value in engines.values() if hasattr(value, "store")), None)
    if engine is not None and not settings_for(engine)["persistent"]:
        return
    try:
        persistent_notification.async_create(
            hass, message, title=title, notification_id=notification_id
        )
    except Exception:
        _LOGGER.warning(
            "Unable to display %s; check the Reorder sensor attributes for saved state",
            notification_id, exc_info=True,
        )



# Events describe saved state. Delivery never invokes a purchasing action.
EVENT_LABELS = {
    "cart_added": "Added to cart",
    "batch_ready": "Order needs review",
    "order_status": "Order status changed",
    "delivery": "Delivery confirmed",
    "list_change": "Cart changed",
    "attention": "Needs attention",
}
DEFAULT_SETTINGS = {"persistent": True,
    "events": ["cart_added", "batch_ready", "delivery", "attention"],
    "notify_services": [], "notify_entities": [], "kiosk_services": [],
    "kiosk_duration": 30, "kiosk_chime": False, "kiosk_scale": 1}


def settings_for(engine):
    from copy import deepcopy
    return {**deepcopy(DEFAULT_SETTINGS),
            **deepcopy(engine.store.data.get("preferences", {}).get("notification_settings", {}))}


def destinations(hass):
    """Discover notify-only destinations, never expose arbitrary action execution."""
    return {
        "services": sorted("notify." + service for service in hass.services.async_services().get("notify", {})
                           if service not in ("send_message", "persistent_notification")),
        "kiosks": sorted("esphome." + service for service in hass.services.async_services().get("esphome", {})
                         if service.endswith("_notification")),
        "entities": [{"id": entity_id, "name": hass.states.get(entity_id).name}
                     for entity_id in sorted(hass.states.async_entity_ids("notify"))],
    }


async def async_deliver(engine, event, message, *, batch_id=None, order_id=None, test=False):
    """Best effort isolated delivery; no provider calls or state mutation."""
    settings = settings_for(engine)
    if not test and event not in settings["events"]:
        return {"sent": 0, "failed": 0}
    title = "Reorder — " + ("Test notification" if test else EVENT_LABELS[event])
    url = "/reorder-app"
    # Plain message works on screens and speech-only destinations alike.
    body = message + " Open Reorder to review."
    notification_id = "reorder_batch_" + batch_id if batch_id else "reorder_" + (order_id or event)
    sent = failed = 0
    if settings["persistent"]:
        try:
            persistent_notification.async_create(engine.hass, body + "\n\n[Open Reorder](/reorder-app)",
                title=title, notification_id=notification_id)
            sent += 1
        except Exception:
            failed += 1
    for service in settings["notify_services"]:
        try:
            domain, name = service.split(".", 1)
            if domain != "notify" or name in ("send_message", "persistent_notification"):
                raise ValueError("Not a supported notify action")
            await engine.hass.services.async_call(domain, name, {"message": body, "title": title}, blocking=True)
            sent += 1
        except Exception:
            failed += 1
    for entity_id in settings["notify_entities"]:
        try:
            # Title is optional for NotifyEntity and not supported by every destination.
            await engine.hass.services.async_call("notify", "send_message",
                {"message": title + ": " + body}, target={"entity_id": entity_id}, blocking=True)
            sent += 1
        except Exception:
            failed += 1
    for service in settings["kiosk_services"]:
        try:
            if not re.fullmatch(r"esphome\.[a-z0-9_]+_notification", service):
                raise ValueError("Not a Kiosk Satellite notification action")
            domain, name = service.split(".", 1)
            payload = {"message": body, "title": title, "duration": settings["kiosk_duration"],
                "type": "warning" if event in ("attention", "batch_ready") else "success" if event == "delivery" else "info",
                "chime": settings["kiosk_chime"], "scale": settings["kiosk_scale"],
                "icon": "mdi:cart-outline", "chime_file": "", "volume": 0, "image": ""}
            # Older Satellite versions expose a smaller set of ESPHome arguments.
            action = engine.hass.services.async_services().get(domain, {}).get(name)
            schema = getattr(getattr(action, "schema", None), "schema", None)
            if isinstance(schema, dict):
                supported = {getattr(key, "schema", key) for key in schema}
                payload = {key: value for key, value in payload.items() if key in supported}
            await engine.hass.services.async_call(domain, name, payload, blocking=True)
            sent += 1
        except Exception:
            failed += 1
    if failed:
        _LOGGER.warning("%s Reorder notification destination(s) failed; saved cart/order state is unchanged", failed)
    engine.notification_delivery = {"event": "test" if test else event, "sent": sent, "failed": failed}
    engine.publish()
    return {"sent": sent, "failed": failed}


def emit(engine, event, message, *, batch_id=None, order_id=None):
    """Schedule delivery only after callers have saved the underlying result."""
    coroutine = None
    try:
        if event in settings_for(engine)["events"]:
            coroutine = async_deliver(engine, event, message, batch_id=batch_id, order_id=order_id)
            engine.hass.async_create_task(coroutine)
    except Exception:
        if coroutine is not None:
            coroutine.close()
        _LOGGER.warning("Could not schedule a Reorder notification; saved state is unchanged")


def dismiss_cart(engine, order_ids):
    """Retire superseded HA cart notices; never clear unrelated kiosk cards."""
    for order_id in order_ids:
        try:
            persistent_notification.async_dismiss(engine.hass, "reorder_" + order_id)
        except Exception:
            _LOGGER.warning("Could not dismiss an old Reorder cart notification")
