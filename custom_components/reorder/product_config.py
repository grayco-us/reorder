"""Shared product and preference validation for actions, options, and the sidebar."""
import math
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.helpers import config_validation as cv


def finite_price(value):
    try:
        value = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("Price ceiling must be a number") from err
    if not math.isfinite(value) or not 0.01 <= value <= 10000:
        raise vol.Invalid("Price ceiling must be between 0.01 and 10000 USD")
    return value


PRODUCT_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Optional("aliases", default=[]): [cv.string],
    vol.Required("retailer"): vol.In(["zinc", "kroger", "other"]),
    vol.Required("product_id"): cv.string,
    vol.Optional("substitutes", default=[]): [cv.string],
    vol.Optional("quantity", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    vol.Optional("max_price", default=50): finite_price,
    vol.Optional("cooldown_hours", default=168): vol.All(vol.Coerce(int), vol.Range(min=1, max=8760)),
    vol.Optional("enabled", default=True): cv.boolean,
    vol.Optional("original_name"): cv.string,
    vol.Optional("create_only", default=False): cv.boolean,
})

PREFERENCES_SCHEMA = vol.Schema({
    vol.Required("strategy"): vol.In(["manual", "weekly", "rolling"]),
    vol.Required("weekday"): vol.All(vol.Coerce(int), vol.Range(min=0, max=6)),
    vol.Required("hour"): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
    vol.Required("rolling_hours"): vol.All(vol.Coerce(int), vol.Range(min=1, max=336)),
    vol.Optional("sync_shopping_list", default=True): cv.boolean,
    vol.Optional("auto_complete_delivered"): cv.boolean,
})


def https_url(value):
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password


def product_values(values):
    """Validate the complete record before a caller changes storage."""
    data = PRODUCT_SCHEMA(values)
    data["name"] = data["name"].strip()
    data["product_id"] = data["product_id"].strip()
    if not data["name"] or not data["product_id"]:
        raise ValueError("Enter a product name and product URL or identifier")
    if data["retailer"] == "zinc" and not https_url(data["product_id"]):
        raise ValueError("Zinc products require a complete HTTPS URL without embedded credentials")
    return data
