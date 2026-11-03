# Cart and Orders (v0.12.0)

The app now uses **Cart** for local requests waiting to be prepared, and **Orders**
for saved groups of products awaiting review or already submitted. An Order is the
same persistent multi-line record previously called a batch; no history is recreated.

## Edit your Cart

1. Add a matching catalog name/alias to Home Assistant's built-in Shopping List.
2. Open **Cart** and select **Edit** on the intended item.
3. Change its quantity (1–20 retailer units) and spending allowance (USD), then save.
   Both apply only to this request. Catalog defaults and the native Shopping List
   entry are not changed. Check the product URL's pack size and variant.
4. Save or discard the edit before choosing **Prepare order for review**. Up to ten
   eligible product lines become a saved Order; their allowances form one combined
   provider spending cap, not separate enforced line caps or a price quote.
5. In **Orders**, review the frozen saved contents. Sandbox and live submission keep
   their existing typed confirmations and live opt-in requirements.

If another session edits the same Cart item, or it is prepared/submitted while a form
is open, a stale save/removal is rejected. Discard that draft, reload and review current
state rather than overwriting it. A failed storage write restores the original record.
The edit/remove handlers never contact a retailer or submit a purchase.

## Remove an item

Choose **Remove**, then confirm **Remove from Cart**. This cancels the local unsubmitted
request, retaining its history. It does not edit/check off/delete its Shopping List
entry or cancel a retailer order. Reconciliation does not silently revive that removed
request. To request it again, add a fresh Shopping List entry; normal active-order and
cooldown checks still apply. A never-submitted local removal does not start a purchase
cooldown.

Prepared or attempted Orders cannot be edited through the Cart controls. A ready,
unsubmitted Order can still be canceled locally using its existing confirmation.
Submitted/uncertain purchases remain protected; retailer cancellations and refunds
must be handled with Zinc/the retailer. Source edits still invalidate affected ready
Orders and return unaffected lines to the Cart, as described in [FLOWS.md](FLOWS.md).

## Tracking and notifications

**Ready for review**, **Pending**, **Order placed**, **Partially delivered** and
**Delivered** distinguish saved review, provider processing, placement and confirmed
item delivery. Delivered labels derive from verified per-item delivery; raw provider
statuses remain stored unchanged. List completion remains a separate result, and
**Needs attention** still exposes partial failures and unresolved mapping/list issues.

Settings and notification text use the same Cart/Orders vocabulary. The existing
optional **Cart edits and list changes** event also covers successful local quantity,
allowance and removal changes. No notification or its dismissal approves an Order.
See [NOTIFICATIONS.md](NOTIFICATIONS.md) for routing and Kiosk Satellite setup.

## Compatibility and development scope

Existing storage keys, IDs, entities, native action names and notification event keys
remain compatible. In particular, actions such as `reorder.prepare_batch`,
`reorder.submit_batch_zinc` and `reorder.refresh_batch_zinc` retain their names;
`batch_id` remains the saved Order ID in native calls. Legacy standalone `order_id`
actions refer to individual request lines, not the multi-line Order. Prefer the app
if you are unsure which ID a native action expects. Native legacy entity IDs/names
remain available; optional dashboard YAML uses the new human-readable card labels.

This stage adds Cart editing and clearer names. Schedules still only prepare Orders;
purchases still require explicit confirmation. Selectable approval-required/unattended
modes, spending budgets, notification grouping and quiet hours are subsequent development
work, not switches enabled by this release. No real orders are placed by automated tests.
