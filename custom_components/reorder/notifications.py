"""Best-effort notifications for actions whose results are stored separately."""
import logging

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


@callback
def async_notify(
    hass: HomeAssistant, message: str, *, title: str, notification_id: str
) -> None:
    """Keep optional presentation failures separate from persisted action results."""
    try:
        persistent_notification.async_create(
            hass, message, title=title, notification_id=notification_id
        )
    except Exception:
        _LOGGER.warning(
            "Unable to display %s; check the Reorder sensor attributes for saved state",
            notification_id, exc_info=True,
        )


