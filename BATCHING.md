# Reorder v0.7.0 — Batch testing

**Development preview. No scheduled payments.** A weekly/rolling schedule only creates a persistent batch marked `ready`.

## Update via Gitea

Commit this full package to a feature branch; merge into `main` after checking files. On UbuntuDev:

```bash
cd /opt/grayco/projects/reorder
git switch main
git pull --ff-only origin main
./deploy-dev.sh
cd /opt/grayco/ha-dev && docker compose restart homeassistant-dev
```

Use `git switch -c feature/batching` before making local changes; `git add . && git commit -m "feat: persistent review-first batching" && git push -u origin feature/batching` to publish a branch.

## Test flow

1. Settings → Devices & services → Reorder → Configure → **Batching schedule and preferences**. Start with **Manual batching**.
2. Add a few distinct Zinc products to the development HA shopping list. Existing queued orders are preserved from v0.3.x.
3. Developer Tools → Actions → `reorder.preview_batch`: notification shows count and combined ceiling.
4. Invoke `reorder.prepare_batch` (optional `max_items: 10`). Find `batch_id` in **Prepared batches** sensor attributes or the persistent notification.
5. Inspect batch line items, quantities, URLs and ceiling. With Zinc test credentials ONLY, call:

```yaml
action: reorder.submit_batch_zinc
data:
  batch_id: REPLACE_WITH_BATCH_ID
  confirmation: SANDBOX
```

6. Call `reorder.refresh_batch_zinc` to fetch fulfillment status. No automatic retry after network uncertainty.

**Important:** Batch price ceiling is a conservative sum of product price ceilings, not a merchant quote. Batching assumes Zinc accepts the specified product URLs and shipping address. Verify live API request shape and retailer grouping in sandbox before live use. Failed or partially fulfilled batches require manual reconciliation; per-line automatic substitutions are not supported in batches yet.

## Limitations & safety

- Up to 10 distinct queued product records, same provider (`zinc`).
- Schedules prepare batches for review, NOT automatic charge/checkout.
- Individual submission is blocked for orders already locked in a batch.
- Local cancellation is available for unsubmitted ready batches only. No retailer cancellation, splitting, batch edit, automatic fallback, or automatic per-item product-status interpretation is provided.
- Weekly mode uses a 15-minute periodic check and local HA time; a weekly review is created only when pending eligible items exist. Rolling mode checks age of oldest queued eligible item.
- The developer must verify Zinc API details and sandbox results before live transactions.
- Back up the HA `.storage` directory before upgrades; no storage-version migration is necessary because the added keys have defaults.

## Action results and retry behavior

`preview_batch` and `prepare_batch` support optional action responses. Existing callers
that do not request a response continue to work. Scripts can capture the prepared ID:

```yaml
- action: reorder.prepare_batch
  data:
    max_items: 10
  response_variable: prepared_batch
# prepared_batch.id identifies the saved batch; this action makes no purchase.
```

Preview responses include `count`, `orders`, and `price_ceiling`. Preparation responses
include `id`, `order_ids`, `status`, and `max_price`. The Prepared batches sensor also
exposes the saved batch if notification display fails. Such failures log a warning
without failing the action or undoing a successfully saved batch.

Repeated preparation with the same queue does not duplicate batches: assigned orders
are excluded under a lock. When the eligible queue is empty, preparation reports
`No eligible queued Zinc orders`. Additional unassigned orders can form a separate
batch. Preview is read-only. Neither action calls Zinc.

Submission persists `submitting` and the Zinc environment before the request. The
idempotency key remains `reorder-batch-<batch_id>` (single orders retain their order
ID key). Concurrent/repeated submissions are rejected locally. A timeout or response
without a Zinc order ID is marked `submission_unknown`; check Zinc before further
action. A returned/refreshed status cannot reset the durable submission guard. The
integration does not automatically retry, purchase substitutions, or spend on schedules.
Zinc request shape and provider-side idempotency still require separate sandbox validation.

## Automated regression tests

Use Python 3.13 with an isolated virtual environment:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Tests use Home Assistant 2025.12.5, temporary storage, real action registration/config
flows and a mocked Zinc transport. They cover preview/preparation, notification and
storage failures, concurrent/repeated calls, restart compatibility, payload idempotency,
submission uncertainty, and purchasing guards. All key strings and shipping fields are
synthetic; tests never contact Zinc. CI runs this suite in addition to the existing
compile, JSON, and manifest/layout checks. `tests/test_matching.py` remains a manual
checklist and is not counted as an automated test.

## Submission and refresh feedback (v0.4.2)

Submission and refresh update the batch's persistent notification with its Reorder
batch ID, raw Zinc status, Zinc order ID, and sandbox/live mode. A successful refresh
also saves `last_refreshed_at` in the Prepared batches sensor attributes. The sensor's
numeric state counts only batches still `ready`; it is not a count of completed orders.

Both actions accept optional responses, including `id`, `status`, `zinc_environment`,
`zinc_order_id`, and the saved batch fields. For an existing sandbox batch:

```yaml
- action: reorder.refresh_batch_zinc
  data:
    batch_id: YOUR_REORDER_BATCH_ID
  response_variable: refreshed_batch
```

Use the Reorder batch ID, not the Zinc order ID. Refresh only retrieves status; it
never creates an order. Missing/invalid status or a mismatched Zinc ID raises an error
and preserves the saved state. A failed network request does not show a success
notification. Notification display failures are logged without failing saved actions.

The documented v2 states include `pending`, `in_progress`, `order_placed`,
`order_failed`, `cancelled`, and `cancelled_by_retailer`. They are retained verbatim
for batches, including failures; failed/cancelled batches cannot be resubmitted.
Legacy states remain supported. Individual-order replacement is still manual and
requires an explicitly failed order and an explicit top-level/nested stock error code
(`product_out_of_stock` or legacy `out_of_stock`). Per-item `error_type` alone is not
interpreted as whole-order stock failure. Batch replacements and partial-fulfillment
reconciliation remain unsupported; no automatic replacements or retries were added.

## Review and cancel local batches (v0.4.3)

Review a batch without submitting, refreshing, or changing it:

```yaml
action: reorder.review_batch
data:
  batch_id: YOUR_REORDER_BATCH_ID
```

The notification lists the saved product names and URLs, quantities, price ceilings,
and local batch status. Optional responses include the saved batch fields plus
`orders` and `count`. Catalog edits do not rewrite these product snapshots. This
works for ready, submitted, and canceled batches; it never contacts Zinc and does
not need credentials. Refresh separately when you need the latest provider status.

To discard a **ready, never-submitted** batch and its queued order lines:

```yaml
action: reorder.cancel_batch
data:
  batch_id: YOUR_REORDER_BATCH_ID
```

Both the batch and its member orders become `canceled`, remain in local history,
and cannot be submitted or picked up by the batching schedule. This does not return
the lines to the queue or remove Shopping List items. Repeating cancellation returns
the same saved result, including `canceled_at`. Notification failure cannot undo a
successful cancellation; a storage-write failure restores in-memory state and reports
an error. Ready-batch counts update immediately after successful cancellation.

Once a submission has started, including `submission_unknown`, local cancellation
is rejected. A provider status change cannot reopen local cancellation. Reconcile
those orders with Zinc; this action never sends a cancellation request to a retailer.
No live transactions are required to test these actions.

## Native dashboard (v0.4.4)

The [Reorder dashboard guide](DASHBOARD.md) explains how to import the built-in-card
layout. It lists saved batches and their mode/status, and provides a batch selector
with review, refresh, and local cancellation buttons. No submission or purchasing
control is included. Selected batch state is transient and resets after restart or
integration reload; batch records remain unchanged.

## Inline batch review (v0.4.5)

The current dashboard shows the selected batch's saved product lines and spending
limits inline, without calling `review_batch` or generating a notification. Status
labels are readable and times use Home Assistant's local timezone. Re-import the
updated YAML after deploying v0.4.5; it does not overwrite customized dashboards.
Existing notification-based review remains supported, with no changes to saved
batch status values, entity IDs, or purchasing safeguards.

## Automatic sidebar app (v0.5.0)

The recommended interface is now [Reorder in the sidebar](SIDEBAR.md). It is bundled
with the integration and registered on startup, with no dashboard to create. Review
saved batches inline, prepare queued products locally, refresh status, or confirm a
local cancellation. The existing submission actions retain their safeguards; no
purchase control is included in the app. Old dashboards and entities remain usable.

## Shopping List intake (v0.5.1)

The Queue tab explains recent matching outcomes and shows the configured names and
aliases. Check it when an added item is missing. Intake activity is transient (latest
20 additions since restart); stored orders and seen-item IDs remain persistent.
Locally canceled, never-submitted work no longer causes cooldown for a fresh item.
Canceled records are retained, while real-submission and duplicate protections remain.

## Shopping List edits and setup (v0.6.0)

[The flow guide](FLOWS.md) describes rename/complete/uncheck/remove and bulk behavior.
Prepared batches affected by a product-changing list edit become `invalidated` and
cannot be submitted; unaffected lines return to queue and the old review stays in
history. Submission rechecks linked list state, while in-flight/submitted requests
remain untouched. Product and batch/list preference forms now live in the sidebar;
credentials and delivery configuration remain native and are preserved by legacy saves.

## Sandbox order and receipt controls (v0.7.0)

The sidebar now supports explicitly confirmed sandbox submission, safe fulfillment/
tracking details, and selected receipt/list completion. It does not expose live purchasing
or automatically clear Shopping List items. Follow [ORDERING.md](ORDERING.md), starting
with the success URL, then separate failure scenarios. Partial/mismatched lines are
never guessed, and existing submission/idempotency/cooldown protections still apply.
