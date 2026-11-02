DOMAIN = "reorder"
STORAGE_VERSION = 1
STORAGE_KEY = "reorder.catalog_v1"
EVENT_UPDATED = "reorder_updated"

# Include Zinc v2 pending plus legacy states retained in existing storage.
ACTIVE_PURCHASE_STATUSES = {
    "pending", "submitting", "submitted", "in_progress", "order_placed",
    "submission_unknown",
}
