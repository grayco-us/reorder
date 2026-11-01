"""Persistent, review-first batch planning. Never triggers a payment automatically."""
from datetime import timedelta
from uuid import uuid4
from urllib.parse import urlparse
from homeassistant.util import dt as dt_util

ACTIVE = {"queued", "approved"}

def eligible_orders(data, retailer="zinc"):
    return sorted((o for o in data["orders"].values()
                   if o.get("status") in ACTIVE and o.get("retailer") == retailer
                   and not o.get("batch_id") and "zinc_environment" not in o), key=lambda o: o["created_at"])

def preview(data, retailer="zinc", limit=10):
    orders = eligible_orders(data, retailer)[:limit]
    return {"retailer": retailer, "orders": [{"id": o["id"], "name": o["name"],
        "quantity": o["quantity"], "product_id": o["product_id"],
        "max_price": o["max_price"]} for o in orders],
        "count": len(orders), "price_ceiling": round(sum(o["max_price"] for o in orders), 2),
        "note": "Price ceiling is an upper limit, not a quote. Tax and shipping are not estimated."}

async def create_batch(engine, retailer="zinc", max_items=10):
    if retailer != "zinc":
        raise ValueError("Only Zinc batches are supported in this version")
    if not 1 <= max_items <= 10:
        raise ValueError("Batch size must be from 1 to 10")
    async with engine.lock:
        orders = eligible_orders(engine.store.data, retailer)[:max_items]
        if not orders:
            raise ValueError("No eligible queued Zinc orders")
        # Recheck duplicate product keys; all orders are locked before persistence.
        keys = [o["product_key"] for o in orders]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate catalog product in batch")
        batch_id = uuid4().hex[:12]
        batch = {"id": batch_id, "retailer": retailer, "order_ids": [o["id"] for o in orders],
                 "status": "ready", "created_at": dt_util.utcnow().isoformat(),
                 "max_price": round(sum(o["max_price"] for o in orders), 2),
                 "note": "Prepared locally. No retailer order has been submitted."}
        engine.store.data.setdefault("batches", {})[batch_id] = batch
        for order in orders:
            order["batch_id"] = batch_id
        try:
            await engine.store.save()
        except Exception:
            # A failed write must not leave a phantom batch in the running instance.
            engine.store.data["batches"].pop(batch_id, None)
            for order in orders:
                order.pop("batch_id", None)
            raise
    engine.publish()
    return batch

def scheduled_due(data, now, timezone):
    settings = data.get("batch_settings", {})
    strategy = settings.get("strategy", "manual")
    if strategy == "manual":
        return False
    items = eligible_orders(data)
    if not items:
        return False
    if strategy == "rolling":
        first = dt_util.parse_datetime(items[0]["created_at"])
        return bool(first and now >= first + timedelta(hours=settings.get("rolling_hours", 48)))
    if strategy == "weekly":
        local_now = dt_util.as_local(now)
        weekday = settings.get("weekday", 6)
        hour = settings.get("hour", 10)
        return local_now.weekday() == weekday and local_now.hour >= hour
    return False
