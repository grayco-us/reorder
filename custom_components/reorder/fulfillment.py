"""Small, credential-free fulfillment snapshots; never retain provider response bodies."""
from copy import deepcopy
from datetime import date
import re
from urllib.parse import urlparse


def safe_code(value):
    return value if isinstance(value, str) and not value.startswith(("zn_", "sk_", "pk_")) and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value) else None


def text(value, limit=128):
    return value[:limit] if isinstance(value, str) else None


def public_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
        return value if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def day(value):
    try:
        return date.fromisoformat(value).isoformat() if isinstance(value, str) else None
    except ValueError:
        return None


def fulfillment_snapshot(response, previous=None):
    result = deepcopy(previous or {})
    for key in ("items", "tracking_numbers"):
        if key in response and not isinstance(response[key], list):
            raise ValueError(f"Zinc response has invalid {key}; reconcile before retrying")
    if "items" in response:
        items = []
        for item in response["items"]:
            if (not isinstance(item, dict) or not isinstance(item.get("quantity"), int)
                    or isinstance(item["quantity"], bool) or item["quantity"] < 1
                    or not isinstance(item.get("status"), str) or not isinstance(item.get("url"), str)):
                raise ValueError("Zinc response has an invalid product item")
            items.append({"id": text(item.get("id")), "url": public_url(item["url"]),
                          "quantity": item["quantity"], "status": safe_code(item["status"]),
                          "error_code": safe_code(item.get("error_type"))})
        result["items"] = items
    if "tracking_numbers" in response:
        shipments = []
        for shipment in response["tracking_numbers"]:
            if not isinstance(shipment, dict):
                raise ValueError("Zinc response has invalid tracking data")
            shipments.append({"carrier": text(shipment.get("carrier"), 64),
                "tracking_number": text(shipment.get("tracking_number")),
                "status": safe_code(shipment.get("status")),
                "url": public_url(shipment.get("zinc_tracking_url")),
                "estimated_delivery_date": day(shipment.get("estimated_delivery_date"))})
        result["shipments"] = shipments
    job = response.get("job_result")
    if job is not None and not isinstance(job, dict):
        raise ValueError("Zinc response has invalid fulfillment result")
    error = response.get("error") if isinstance(response.get("error"), dict) else {}
    result["error_code"] = safe_code((job or {}).get("error_type") or response.get("error_code")
                                    or response.get("code") or error.get("code"))
    prices = (job or {}).get("price_components", response.get("price_components"))
    if isinstance(prices, dict):
        result["prices_cents"] = {key: value for key in ("subtotal", "tax", "shipping", "total")
                                  if isinstance(value := prices.get(key), int) and not isinstance(value, bool) and value >= 0}
    if isinstance(response.get("merchant_order_ids"), list):
        result["merchant_order_ids"] = [value[:128] for value in response["merchant_order_ids"] if isinstance(value, str)][:20]
    statuses = {item["status"] for item in result.get("items", [])}
    good = statuses.intersection({"ordered", "shipped", "delivered", "available_for_pickup"})
    bad = statuses.intersection({"failed", "skipped", "cancelled"})
    result["outcome"] = "partial" if good and bad else "failed" if bad and not good else "processing_or_success"
    return result


def mapped_item(order, fulfillment, orders=None):
    if orders is not None and sum(other["product_id"] == order["product_id"] and other["quantity"] == order["quantity"] for other in orders) != 1:
        return None
    matches = [item for item in fulfillment.get("items", [])
               if item["url"] == order["product_id"] and item["quantity"] == order["quantity"]]
    return matches[0] if len(matches) == 1 else None


def receipt_eligible(order, batch, orders):
    """Sandbox can simulate receipt; real list updates require explicit item delivery."""
    if order.get("zinc_environment") != batch.get("zinc_environment") or order.get("zinc_order_id") != batch.get("zinc_order_id"):
        return False
    if batch.get("status") not in ("order_placed", "order_failed", "failed") or not batch.get("zinc_order_id"):
        return False
    item = mapped_item(order, batch.get("fulfillment", {}), orders)
    if not item or item.get("error_code"):
        return False
    allowed = {"ordered", "shipped", "available_for_pickup", "delivered"} if batch.get("zinc_environment") == "sandbox" else {"delivered"}
    return item["status"] in allowed and bool(order.get("shopping_item_id"))
