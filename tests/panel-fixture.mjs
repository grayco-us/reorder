export function makePanelData() {
  return {
    mode: "Sandbox", product_count: 3, shopping_list_ready: true,
    preferences: { strategy: "manual", weekday: 6, hour: 10, rolling_hours: 48, sync_shopping_list: true },
    catalog: [
      { name: "Morning coffee", aliases: ["coffee"], enabled: true, retailer: "zinc", product_id: "https://example.com/coffee", quantity: 1, max_price: 18, cooldown_hours: 168, substitutes: [], can_rename: false },
      { name: "Cat litter", aliases: [], enabled: true, retailer: "zinc", product_id: "https://example.com/cat-litter", quantity: 2, max_price: 35, cooldown_hours: 168, substitutes: [], can_rename: false },
      { name: "Laundry detergent", aliases: [], enabled: true, retailer: "zinc", product_id: "https://example.com/detergent", quantity: 1, max_price: 15, cooldown_hours: 168, substitutes: [], can_rename: false },
    ],
    intake_events: [{ name: "coffee", reason: "queued", message: "Queued locally as queue-1. No purchase was made.", created_at: "2026-11-02T13:30:00Z", order_id: "queue-1" }],
    queue: { count: 1, price_ceiling: 18, orders: [{ id: "queue-1", name: "Morning coffee", quantity: 1, max_price: 18, product_id: "https://example.com/coffee" }] },
    batches: [
      { id: "ready-batch", status: "ready", status_label: "Ready for review", created_at: "2026-11-02T13:33:06Z", max_price: 50, can_cancel: true, can_refresh: false, can_submit_sandbox: true, review_error: null, receivable_order_ids: [], orders: [
        { id: "line-1", name: "Cat litter", quantity: 2, max_price: 35, product_id: "https://example.com/cat-litter" },
        { id: "line-2", name: "Laundry detergent", quantity: 1, max_price: 15, product_id: "https://example.com/detergent" },
      ] },
      { id: "placed-batch", status: "order_placed", status_label: "Order placed", zinc_environment: "sandbox", zinc_order_id: "mock-zinc-id", created_at: "2026-11-01T13:33:06Z", last_refreshed_at: "2026-11-02T13:55:00Z", max_price: 50, can_cancel: false, can_refresh: true, review_error: null, orders: [
        { id: "line-3", name: "Sandbox success test", quantity: 1, max_price: 50, product_id: "https://zinc.com/shop/products/test-success" },
      ] },
      { id: "uncertain-batch", status: "submission_unknown", status_label: "Needs reconciliation", zinc_environment: "sandbox", created_at: "2026-10-31T13:33:06Z", max_price: 22, can_cancel: false, can_refresh: false, review_error: null, orders: [
        { id: "line-4", name: "Paper towels", quantity: 1, max_price: 22, product_id: "https://example.com/towels" },
      ] },
    ],
  };
}
