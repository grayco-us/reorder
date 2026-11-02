# Sandbox ordering, tracking, and Shopping List receipt (v0.7.0)

The sidebar now supports the next stage of the workflow: explicitly submit a **sandbox**
batch, retrieve item/fulfillment/tracking details, and deliberately complete selected
linked Shopping List items. The app still has **no live-purchase control**. Existing
manual live actions retain their original opt-in and confirmation safeguards.

## Success-path test

1. Configure your `zn_test_` key and test shipping details in the native Reorder
   configuration. Keep live purchasing off. The app must show **Sandbox**.
2. Add an enabled Zinc product named **Sandbox success test**, with quantity 1,
   price ceiling $50, and URL:
   `https://zinc.com/shop/products/test-success`.
3. Add that name to Home Assistant's built-in Shopping List. In Queue, prepare a batch
   and review its saved products/quantities/total ceiling. Existing prepared batches
   do not change when you edit the catalog.
4. Open the ready batch and choose **Submit sandbox batch**. Check the displayed
   number of lines and ceiling, type **SANDBOX**, and confirm once. The server requires
   a test key independently of the browser; a live key cannot use this gateway.
5. Use **Refresh status**. Zinc is asynchronous: pending/processing can precede
   `order_placed`. Placement is not delivery. Refresh displays the provider's item
   outcomes, safe error codes, reported actual total, merchant order IDs and tracking
   when supplied. No carrier tracking is invented or fetched automatically.
6. To test list maintenance, choose **Complete test list items** once per-item results
   uniquely match successful lines. Select the intended lines, type **SIMULATE RECEIPT**,
   and confirm. Only those exact Shopping List IDs are checked off. The provider's
   order/delivery status is not changed by this simulation.
7. Confirm the native Shopping List item is completed, the app shows its list status,
   and unselected/failed items remain open. Repeat receipt is idempotent; it never
   submits an order or resets the original completion/cooldown timestamp.

Sandbox tracking may be simulated, incomplete, or never advance to delivered. The
simulation is a deliberately labeled local list update, not proof of physical delivery.
If no matching provider items are supplied, refresh again; unmatched/ambiguous lines
cannot be completed automatically. You may still manage such list items manually.

## Failure and partial-fulfillment tests

Use separate batches and unique test product names for the documented scenarios:

| Sandbox URL suffix | Expected scenario |
| --- | --- |
| `test-out-of-stock` | Asynchronous `product_out_of_stock` failure |
| `test-price-exceeded` | Asynchronous `max_price_exceeded` failure |
| `test-invalid-address` | Synchronous address rejection |

The prefix is `https://zinc.com/shop/products/`. Refresh accepted orders to retrieve
results. The current request uses Zinc's strict default fulfillment: a mixed batch
can fail as a whole. When Zinc reports partial success, the UI shows it and only
explicitly successful eligible test lines can be selected for simulated receipt.
Failed, skipped, canceled, unmatched or quantity-mismatched lines are not cleared or
retried. There is no automatic replacement, new batch submission or retailer cancellation.

HTTP failures show status and a sanitized machine-readable code when available, never
raw provider error bodies. A failed/uncertain attempt remains locked against resubmission.
If an ID was returned but other response data was malformed, the ID is retained for a
read-only refresh/reconciliation. If there is no ID, check Zinc before further action.
Do not create new IDs or clear storage to bypass uncertainty.

## Tracking and delivery

Only allowlisted provider fields are retained: item ID/URL/quantity/status/error code,
carrier/tracking number/status/public HTTPS URL/date-only ETA, merchant order IDs and
reported price components in cents. Keys, addresses, private delivery-proof photos,
raw error text, payment details and arbitrary job-result payloads are excluded.

The API's overall `order_placed` state is preserved. Per-item statuses and shipment
statuses are shown separately. A delivered package alone is not used to guess that
all lines arrived. Matching must be unique by saved URL and quantity; duplicate or
canonicalized/mismatched URLs may require manual reconciliation. No automatic polling
or webhook endpoint is added in this release: provider updates require Refresh.

For existing manually submitted **live** orders, list completion is available only
for uniquely matched, explicitly provider-delivered items, with matching configured
live mode and the separate **ITEMS RECEIVED** confirmation. It never submits a purchase.
A partial/failed aggregate order can still have a confirmed delivered line, but failed
or skipped lines are never made eligible. No real credentials or purchases are needed
to validate the sandbox flow.

## List changes, errors, and repeat orders

- Completion targets item IDs through Home Assistant's built-in To-do service, not
  names. Duplicate names, renamed and removed source entries are not guessed or cleared.
- Order placement, tracking appearance and refresh never check off list items on their
  own. The explicit receipt confirmation is required, even for provider-delivered lines.
- A list update can partly succeed before another line or the local metadata save fails.
  Reload/check the list before retrying. Already-complete IDs are recognized without
  repeating any purchase; the app reports completed vs skipped/failed counts.
- Submitted/uncertain work remains unchanged by the resulting Shopping List events.
- Confirmed delivery, or explicit recorded receipt, releases the permanent active lock
  for that completed order but **does not bypass cooldown**. Cooldown starts from the
  first confirmed delivery/receipt observation. A fresh Shopping List item can queue
  another request only after that interval; the original item ID remains deduplicated.
  Uncertain or unreceived placed orders remain protected as before.

Store additions are backward compatible. Existing batches can be refreshed to populate
these details; no data deletion/migration is required. Submission and repeat-purchase
checks still occur on the server immediately before the network request.
