# Tracking and recovery (v0.11.0)

> **v0.12.0 terminology:** The app calls the queue **Cart** and prepared batches
> **Orders**. Existing action names/IDs remain unchanged. See
> [Cart and Orders](CART_AND_ORDERS.md) for editing, local removal and frozen review.


Use **Orders → Needs attention** to find uncertain submissions, saved tracking/list
errors, failed or partial fulfillment, missing item mappings, changed source entries,
and unresolved orders whose credentials do not match the current environment.
The filter is a derived view of saved state; it does not change orders or mark a
problem resolved. Check each batch's last successful refresh time and its recovery text.

Each batch separates **delivery-confirmed lines**, **failed/skipped lines** and
**currently completed linked list entries**. These counts describe different things.
Order placement is not delivery, and delivery does not prove a list update succeeded.
Per-line details show the last saved list result, including removed/renamed entries,
source unavailability and failed updates. An entry deliberately unchecked after recorded
completion stays unchecked; refresh does not treat it as a new purchase request.

## Safe next steps

| Situation | Next step |
| --- | --- |
| Uncertain submission, Zinc ID saved | Refresh the same order using matching credentials. Do not submit another batch to test the first attempt. |
| Uncertain submission, no Zinc ID | Check the matching Zinc account/dashboard or contact support. Reorder cannot discover the missing order automatically. Do not invent an ID, clear storage or bypass the submission lock. |
| Status request failed | Check connection/credentials, then refresh the existing order. Automatic tracking also retries. A failed status request does not prove the purchase failed. |
| Wrong/missing environment key | Configure the original matching Sandbox/live credentials. Changing keys never converts or cancels an order. |
| Partial or failed fulfillment | Inspect each item and the Zinc dashboard. Only confirmed delivered lines can complete their source entries. No failed product is repurchased automatically. |
| Saved delivery, failed list update | Verify native Shopping List availability and refresh to retry list synchronization. A new purchase is unnecessary. |
| Original list entry renamed/removed | Manage the changed/replacement entry deliberately. Reorder skips it rather than guessing by name. |
| Packages delivered, item links unknown/inferred/incomplete | Verify contents manually. Reorder does not infer that all products arrived from a package-level status. |
| Automatic list completion off | Complete confirmed received items in the native list, or use the eligible manual receipt control with its existing environment/confirmation guards. |

A manual refresh failure appears inline and retains the last saved order result.
Automatic polling failures also retain a saved attention indicator, which clears after
a successful refresh. The last refreshed time is the last successful saved refresh,
not the most recent failed attempt. The recovery panel does not automatically clear
purchase locks, attach guessed Zinc IDs, retry a POST, cancel a retailer order or buy
a replacement. Dashboard/support reconciliation remains necessary for uncertain
submissions without IDs and ambiguous provider data.

## Refresh while purchasing is off

With the correct `zn_live_` key configured, **Refresh status** now works even when
**Enable live Zinc purchasing** is off. The native refresh button and both refresh
actions follow the same rule. Shipping fields are not needed to read an existing order.
A valid key and matching saved Sandbox/live environment are still required; a key from
a different account can still fail provider authorization even in the same environment.

This is GET-only provider access. It never submits or cancels a purchase. A refreshed
confirmed delivery can still check off linked Shopping List entries if automatic
completion is enabled. Turn that preference off to manage list completion manually.
The existing manual receipt action keeps its live-mode and typed-confirmation guards.

Live submission still requires live opt-in, complete shipping details, the exact
**PLACE LIVE ORDER** phrase, and all existing source/idempotency/uncertainty checks.
The in-app review also binds confirmation to saved contents and connection options.
Turning purchasing off prevents new live submissions and invalidates an open review;
it does not cancel an order that was already submitted or stop read-only tracking.

Automated checks use mocked Zinc transport and synthetic credentials. Confirm provider
results in your own development instance; no real order was placed for this release.
