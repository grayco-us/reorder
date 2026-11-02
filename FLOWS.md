# Shopping List and configuration flows (v0.8.0)

Reorder watches Home Assistant's built-in Shopping List. Adds and updates only create
or change **local** work; they never submit a purchase. Synchronization is on by default
and can be disabled under **Reorder → Settings** for manual queue management.

| Shopping List change | Unsubmitted order | Prepared batch | Submitted or uncertain work |
| --- | --- | --- | --- |
| Add an enabled exact name/alias | Queue once, subject to duplicate/cooldown rules | Existing work is not duplicated | Existing safeguards still block duplicates |
| Rename to another alias of the same product | Keep quantities, URL and price ceiling | Keep the prepared batch | Leave unchanged |
| Rename to another approved product | Cancel old line; queue a new product snapshot | Invalidate the old batch; return other lines to queue | Leave unchanged; add a separate item for a new request |
| Rename to an unmatched/disabled/ambiguous name | Cancel old line; explain why no replacement was queued | Invalidate and return other lines to queue | Leave unchanged |
| Check off / complete | Cancel the local line | Invalidate and return other lines to queue | Leave unchanged; this does not cancel a retailer order |
| Uncheck | Queue a fresh snapshot if the prior cancellation came from a list change | Requires a new preparation/review | Does not reopen submitted work |
| Remove | Cancel the local line | Invalidate and return other lines to queue | Leave unchanged |
| Complete/uncheck all, clear completed | Reconcile affected linked lines against a known current list | Apply the same invalidation rule | Leave unchanged |
| Reorder the list | No change | No change | No change |

An invalidated batch has status `invalidated` (**Needs fresh review**). It cannot be
submitted. Its product snapshots remain available in history even after unaffected
orders are assigned to a new batch. A removed/completed line stays canceled. Unaffected
lines retain their saved quantities and spending limits when returned to the queue.
Prepare another batch to review the resulting set; the old batch is never silently
edited into a different purchasable order.

A manual `cancel_batch` or `cancel_order` is not undone by unchecking. To request a
manually canceled product again, add a fresh Shopping List item. Seen-item IDs persist,
so replayed source events cannot duplicate orders. Ordinary completed purchases and
active/uncertain submissions retain the existing duplicate protections.

## Timing, restarts, and failures

Source item dictionaries are copied when events are received, and source events are
processed serially. Store mutations are also locked. Rapid edits cannot interleave
half-applied queue/batch changes. Failed writes restore the touched local order and
batch records and expose an intake error.

Submission separately checks linked Shopping List items immediately before marking
work `submitting`. Removed/completed or newly unapproved/ambiguous names block a stale
submission even if their event is still pending or a prior synchronization write failed.
Once submission starts, subsequent list edits never attempt to cancel or alter the
provider request. Use Zinc to reconcile actual purchases or unknown outcomes.

A missing/unloaded Shopping List source is **unknown**, not an empty list: Reorder does
not guess that all items were removed. It blocks linked submissions until list state
can be verified. The adapter supports both the older shared Shopping List data and
newer config-entry runtime data. Other to-do providers are not automatically monitored.

Every 15 minutes, Reorder reconciles the current native list to recover missed adds,
edits, completion and removal after downtime. Previously blocked open entries can
queue once their active-order/cooldown blocker clears. Missing/unavailable source state
never cancels everything. Confirmed delivered batch lines can check off original IDs;
see [the ordering guide](ORDERING.md).
Turning synchronization off keeps local work until you manage it explicitly and turns
off the source-state submission check. Purchasing confirmations and idempotency stay on.

## Products in the sidebar

**Reorder → Products** supports add, edit, enable/disable and confirmed removal:

- Name, comma-separated aliases, provider, product URL/identifier.
- Quantity (1–20), total price ceiling ($0.01–$10,000), cooldown (1–8760 hours).
- Up to two ranked substitution URLs; these are still manual replacement choices.
- Zinc product/substitution URLs must be HTTPS without embedded credentials.
- New saves reject aliases/names overlapping another enabled product. Legacy ambiguous
  catalogs still load and produce an explicit intake explanation instead of a guess.

Catalog changes apply to future matching and never rewrite queued, prepared or submitted
product snapshots. Removing a catalog product is different from removing a Shopping
List item: the former stops future matching and leaves existing local work intact;
the latter follows the synchronization table above. Removal requires confirmation in
the app. A product with order history cannot be renamed because historical product
keys must stay stable; its name field is read-only and aliases remain editable. Products
without order history may be renamed atomically. If an old source identity cannot be
verified after catalog changes, review/reprepare instead of bypassing submission checks.

All product interfaces use the same backend validation and transactional save helpers.
A failed edit/rename/removal leaves the prior catalog intact. Product edits do not
rescan or queue every existing Shopping List item automatically. Add or edit an item
when you want a fresh match. Unsaved form drafts survive navigating between app pages;
validation errors keep the draft for correction.

## Preferences in the sidebar

**Reorder → Settings** manages manual/weekly/rolling batch preparation, weekday, hour
in Home Assistant's local timezone, rolling window, source-change synchronization,
and the independent automatic delivery-completion preference.
Schedules prepare batches only; they never submit purchases. Saving unchanged schedule
values preserves the last scheduled date; a real schedule change resets that date.

API keys, delivery details and live-purchasing setup remain in Home Assistant's native
Reorder configuration, linked from Settings and **Connection**. They are not returned
by the sidebar data API or included in product/preferences commands. The sidebar and
its management commands require administrator access. The legacy native product and
schedule forms remain supported and now preserve existing connection options instead
of overwriting them with an empty dictionary.

## Development checks

The regression suite exercises real Shopping List add/update/remove/bulk methods,
queue/batch invalidation, manual cancellation vs unchecking, stale-submit checks,
in-flight requests, failed saves, legacy options flows and admin-only management.
Frontend tests validate payloads, drafts and audit display; Chromium smoke tests cover
product create/edit/disable/remove, schedule/preferences saving, validation errors and
mobile rendering with synthetic local fixtures. No Zinc transactions are needed.

## Order/receipt stage (v0.8.0)

The new [ordering guide](ORDERING.md) adds sandbox-only UI submission and explicit
per-line receipt/list completion. These are separate from source-change synchronization:
placement never checks off items; confirmed delivered lines are automatically completed
by default, with an independent Settings switch for manual receipt. Completion uses exact source
IDs and skips renamed/missing lines; partial failures remain open. Provider delivery or
an explicit recorded receipt permits a fresh request only after cooldown, while the old
source ID and attempted submission remain protected against replay.
