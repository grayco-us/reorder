# Reorder v0.4.1 — Batch testing

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
- No cancellation, splitting, batch edit, automatic fallback, or automatic product-status interpretation in this version.
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
