"""Persistent, review-first batch planning. Never triggers a payment automatically."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from homeassistant.util import dt as dt_util
from .notifications import emit, dismiss_cart

ACTIVE = {"queued", "approved"}


def batch_status_label(status):
    """Readable display names without changing persisted/provider status values."""
    return {
        "ready": "Ready for review", "pending": "Pending", "submitting": "Submitting",
        "submitted": "Submitted", "in_progress": "In progress", "order_placed": "Order placed",
        "failed": "Failed", "order_failed": "Failed", "canceled": "Canceled",
        "cancelled": "Canceled", "cancelled_by_retailer": "Canceled by retailer",
        "submission_unknown": "Needs reconciliation", "invalidated": "Needs fresh review",
    }.get(status, str(status).replace("_", " ").capitalize())

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
        raise ValueError("Only Zinc orders are supported in this version")
    if not 1 <= max_items <= 10:
        raise ValueError("Order size must be from 1 to 10")
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
    dismiss_cart(engine, batch["order_ids"])
    emit(engine, "batch_ready", f"Your batch is ready for review: {len(orders)} product line(s), combined spending limit ${batch['max_price']:.2f}. Review saved products and quantities before explicitly submitting. Nothing has been purchased.", batch_id=batch_id)
    return batch


def review_batch(data, batch_id):
    """Return saved product snapshots without consulting the mutable catalog."""
    batch = data.get("batches", {}).get(batch_id)
    if batch is None:
        raise ValueError("Order not found")
    if batch["status"] == "invalidated" and "snapshot_orders" in batch:
        orders = batch["snapshot_orders"]
        return deepcopy({**batch, "orders": orders, "count": len(orders)})
    orders = []
    for order_id in batch["order_ids"]:
        order = data["orders"].get(order_id)
        if order is None or order.get("batch_id") != batch_id:
            raise ValueError("Order contains a missing or reassigned order")
        orders.append({key: order[key] for key in (
            "id", "name", "product_id", "quantity", "max_price", "status"
        )})
    return deepcopy({**batch, "orders": orders, "count": len(orders)})


async def cancel_batch(engine, batch_id):
    """Cancel only local, unsubmitted work; never attempt a retailer cancellation."""
    async with engine.lock:
        batch = engine.store.data.get("batches", {}).get(batch_id)
        if batch is None:
            raise ValueError("Order not found")
        if "zinc_environment" in batch or batch.get("zinc_order_id"):
            raise ValueError("Submitted or uncertain orders must be reconciled with Zinc")
        if batch["status"] == "canceled" and batch.get("canceled_at"):
            return review_batch(engine.store.data, batch_id)
        if batch["status"] != "ready":
            raise ValueError("Only an unsubmitted ready order can be canceled locally")
        orders = [engine.store.data["orders"].get(key) for key in batch["order_ids"]]
        if not orders or any(
            order is None or order.get("batch_id") != batch_id
            or order["status"] not in ACTIVE or "zinc_environment" in order
            or order.get("zinc_order_id") for order in orders
        ):
            raise ValueError("Order contains an invalid, changed, or attempted order")
        previous_batch = deepcopy(batch)
        previous_orders = [deepcopy(order) for order in orders]
        batch.update(
            status="canceled", canceled_at=dt_util.utcnow().isoformat(),
            note="Order and its queued orders canceled locally. Nothing was sent to Zinc.",
        )
        for order in orders:
            order.update(status="canceled", note="Canceled with its unsubmitted order; no purchase was made.")
        try:
            await engine.store.save()
        except Exception:
            batch.clear()
            batch.update(previous_batch)
            for order, previous in zip(orders, previous_orders, strict=True):
                order.clear()
                order.update(previous)
            raise
        report = review_batch(engine.store.data, batch_id)
    engine.publish()
    return report

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
