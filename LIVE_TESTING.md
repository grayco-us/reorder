# First live trial (v0.10.0)

This guide is for a user-run real purchase, not another Sandbox simulation. No live
order has been verified by the automated tests. Live submission is available in the sidebar for administrators, with live purchasing
enabled, an explicit saved-content review and the exact `PLACE LIVE ORDER` phrase.
The existing native action remains available. Saving settings, adding list items, preparing a batch and
scheduled batch preparation never submit purchases.

## Prepare one small trial

1. Update the integration, restart Home Assistant, and refresh the browser. Verify
   the Sandbox flow before changing credentials. Keep batch preparation **Manual**
   for the trial so the saved contents are easy to review.
2. Reconcile any pending/uncertain Sandbox work before switching keys. A different
   key does not convert or cancel old orders, and only the current environment is
   tracked. An earlier active order or cooldown may block the same catalog product
   even across environments; do not clear storage, rename products or create duplicate
   batches to bypass it.
3. In **Connection → Zinc API and delivery settings**, enter your own `zn_live_`
   key and correct US recipient/address/phone details. Keep **Enable live Zinc
   purchasing** off while reviewing. Confirm funding, fees, available product variant,
   pack size, delivery options and any account restrictions directly in Zinc/retailer.
   Do not paste keys, addresses or payment details into issues or screenshots.
4. In **Products**, review one intended, inexpensive real retailer product with
   quantity **1** and a suitable USD ceiling including tax/shipping. Use its actual
   HTTPS product URL, not `zinc.com/shop/products/test-*`. A catalog quantity is
   retailer units, not the quantity parsed from Shopping List text.
5. Add the exact catalog name/alias to the built-in Shopping List once. Review Queue
   and its activity explanation. If the request is blocked, resolve the stated cause;
   repeated additions do not override an active purchase or cooldown.
6. Prepare a batch and verify it contains **only the one intended line**. Check its
   saved URL, variant/pack size, quantity and combined ceiling. Product edits do not
   update an already prepared batch. If wrong, cancel the unsubmitted work locally
   and request/review a new batch; never alter submitted history.

The batch ceiling is the sum of saved product allowances. Zinc receives one combined
order cap, not individual line caps. A reported total is not a quote or proof of final
payment settlement. Check Zinc's current fees and funding/authorization terms separately.
A ready batch has not been bound to Sandbox/live credentials yet: the current key at
submission selects the environment. Review saved contents again after switching keys.

## Submit once, then observe

When you are ready to make the real purchase, enable **live purchasing** in Connection.
The app should show **Live enabled**. Select the intended ready batch and choose
**Review live order**. Check its saved products, URLs/pack sizes, quantities and combined
ceiling, and verify delivery details in Connection. Tick **I checked the saved products,
quantities and combined spending limit**, type **PLACE LIVE ORDER**, then choose
**Place live order** once. This can spend real money.

The app confirmation is bound to the reviewed batch and connection options. Changing
saved contents, credentials, delivery details or live opt-in, or reloading the integration,
requires a fresh review. A stale confirmation fails before submission. Notifications
and kiosk cards remain informational; they cannot authorize this step.

Alternatively, in **Developer Tools → Actions**, select
**Reorder: Submit Zinc batch** (`reorder.submit_batch_zinc`) and enter the local saved
batch ID shown in the app. This is not the Zinc order ID or a product/order-line ID.

```yaml
action: reorder.submit_batch_zinc
data:
  batch_id: REPLACE_WITH_REVIEWED_LOCAL_BATCH_ID
  confirmation: PLACE LIVE ORDER
```

Run that action **once**. It can spend real money. Do not use the standalone
`reorder.submit_zinc` action for a prepared batch. After the attempt, turn live
purchasing off to prevent new live submissions; keep the same live key configured.
Read-only automatic batch tracking and delivery completion continue with that key.
Manual Refresh is disabled by the existing live-mode guard while live purchasing is
off; use the periodic updates, or deliberately re-enable live mode for manual refresh
and turn it off afterward. Enabling it alone does not submit anything.

If an error occurs, inspect saved batch state and the Zinc dashboard before any
further purchase. `submission_unknown`, timeouts, HTTP errors or missing notifications
must never be treated as evidence that nothing was purchased. A known Zinc ID can be
refreshed; an uncertain attempt without one requires dashboard/support reconciliation.
Reorder locks attempted submissions instead of retrying or creating another purchase.

## Observe through delivery

- **Pending/submitted** means processing. **Order placed** means retailer placement,
  not arrival. Confirm the matching order and charges/holds in Zinc.
- **Refresh status** queries Zinc immediately. Unresolved tracked batches also refresh
  every 15 minutes, at most ten per pass; provider/carrier updates may lag. **Reload**
  only reads saved app data. Review per-item errors, reported totals and tracking.
- With **Automatically check off linked list items after confirmed delivery** enabled,
  an explicitly delivered item, or exact links to all known delivered packages carrying
  it, completes its original Shopping List ID. It leaves the active list and remains
  in completed history. One arriving package cannot clear a partly delivered item.
- Failed/skipped items, unknown/inferred package mappings, mismatched URLs/quantities,
  renamed sources and new same-name list IDs remain open. Reconcile these manually;
  do not assume the entire batch arrived from its aggregate status.
- A list-update error leaves delivery saved and retries on refresh without another
  purchase. To manage receipt manually, turn off automatic completion in Settings;
  eligible live lines require **ITEMS RECEIVED**. That action only updates the list.
- Once completion is recorded, unchecking the original entry is respected and does not
  request another purchase. Add a fresh entry for a new request after the configured
  cooldown. Submitted/uncertain purchases are unaffected by list edits or removals.
- **Cancel locally** applies only before submission. Retailer cancellation, returns
  and refunds must be handled with Zinc or the retailer. Turning off live purchasing,
  deleting a list item or removing a catalog product cannot cancel a real order.

Record the integration/HA versions, local batch ID, Zinc ID, timestamps, state changes,
line outcomes, list result and any sanitized machine error code. Confirm one order
exists in Zinc, one intended purchase occurred, and delivery updated only its original
list entry. Do not include credentials, full addresses or raw API responses in reports.

See [ORDERING.md](ORDERING.md) for Sandbox scenarios and delivery-mapping limitations,
and [FLOWS.md](FLOWS.md) for adding, editing, completing and removing list items.
