# Reorder v0.4.0 — Batch testing

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
