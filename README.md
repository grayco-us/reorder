# Reorder by Grayco

Home Assistant custom integration for routing exact, preapproved shopping-list items to a persistent order queue, with **Zinc API submission (sandbox first)**.

## v0.7.0: Sandbox submission, tracking and explicit list receipt

Ready sandbox batches can now be submitted from the sidebar after typing **SANDBOX**.
The server independently requires a `zn_test_` key; live purchase controls are not
exposed. Refresh retains safe per-item outcomes, partial failures, tracking and reported
costs. Placement and delivery remain distinct; no list item is cleared automatically.

Use **Complete test list items**, select successful linked lines, and type **SIMULATE
RECEIPT** to exercise list completion without claiming provider delivery. Failed/skipped,
renamed, missing or ambiguous lines stay untouched. Existing live-order list maintenance
requires explicit per-item delivery and its own confirmation. Confirmed receipt/delivery
permits future requests only after the configured cooldown, without resubmitting an old
order. See the [full order-stage test guide](ORDERING.md).

## v0.6.0: Shopping List synchronization and in-app setup

Reorder now handles renames, completion/unchecking, removal, and bulk list changes.
Unsubmitted affected lines are canceled; prepared batches become **Needs fresh review**
and return their other lines to the queue. Submitted/uncertain work is never altered
by a list edit. Source state is rechecked before submission to close edit/submit races.
See the [flow table and compatibility notes](FLOWS.md).

The sidebar **Products** page adds product setup, editing, enable/disable and confirmed
removal. **Settings** manages batching schedules and list synchronization. Validation
and rollback are shared with the legacy interfaces, and native product/schedule forms
now preserve saved Zinc connection options. Keys, delivery and live setup remain in
Home Assistant's native configuration, linked from the app. Existing storage and
purchasing safeguards remain compatible; no purchases are submitted by the app.

## v0.5.1: Explain Shopping List intake

The sidebar Queue tab now shows the most recent Shopping List matching outcomes:
queued, unmatched, disabled, ambiguous, already processed, blocked by an existing
order, cooldown, or save failure. It also shows configured product names/aliases and
whether the built-in Shopping List integration is loaded. Activity is limited to the
latest 20 received additions in memory and clears when Reorder restarts.

A never-submitted local cancellation no longer starts a purchase cooldown: adding a
fresh Shopping List item can queue that product again. The canceled order itself
remains canceled. Seen-item deduplication, active/uncertain-order guards, real
submission cooldowns, and all purchasing confirmations are unchanged. Failed queue
saves restore the order/seen-item state rather than leaving a phantom queued order.

## v0.5.0: Reorder in the Home Assistant sidebar

Reorder now includes a bundled sidebar app: batch lists and inline product review,
queue preparation, provider-status refresh, and confirmed local cancellation. No
manual dashboard YAML, custom card installation, or frontend build is required.
It adapts to desktop and mobile, uses Home Assistant themes and local time, and keeps
batch selection local to each browser. There is no purchase control in the app.

Deploy the update, restart Home Assistant, refresh your browser, and open **Reorder**
in the sidebar as an administrator. Existing configuration, stored orders, entities,
and actions are retained. The old dashboard is optional and is not removed or
modified automatically. See the [sidebar app guide](SIDEBAR.md) for access, testing,
upgrade details and current limitations.

## v0.4.5: Review batch contents inline

Selecting a batch now displays its saved products, clickable product links,
quantities, individual price ceilings, and total ceiling directly on the dashboard.
No Review button or notification is required. A two-section layout keeps the batch
selector, details, and controls together, with the queue and history alongside them.
Statuses have readable display labels; timestamps use Home Assistant's local timezone.

Update the integration and re-import [the dashboard YAML](dashboards/reorder.yaml)
to use the new layout. Existing dashboards are not automatically overwritten. Raw
provider status values, entity IDs, and stored batches remain unchanged. The existing
review action and button continue to work for callers using notification-based review.

## v0.4.4: Native Reorder dashboard

A [starter dashboard](dashboards/reorder.yaml) now shows ready and submitted/past
batches, purchasing mode, and native batch selection with review, refresh, and local
cancellation controls. It uses Home Assistant's built-in cards only and contains no
purchase button. Selection clears after restart; unavailable operations remain guarded.
The mode sensor never exposes keys or delivery details. Existing sensor IDs, stored
batches, and configuration are preserved.

Follow the [dashboard installation guide](DASHBOARD.md) to create a separate dashboard
and import the YAML after updating the integration. Dashboard creation is explicit;
upgrading Reorder does not overwrite your existing dashboards.

## v0.4.3: Review and cancel prepared batches

Use `reorder.review_batch` with a batch ID to display its saved product names, URLs,
quantities, individual price ceilings, total ceiling, and current local status. It
never contacts Zinc. Catalog edits do not change the queued product snapshots being
reviewed. The action also supports an optional response for scripts.

`reorder.cancel_batch` cancels a locally prepared `ready` batch **and its queued
orders**. Canceled orders stay in history, are not returned to the queue, and cannot
be purchased or automatically batched again. Repeating the cancellation is safe.
This does not cancel a retailer purchase: any submitted or uncertain batch must be
reconciled with Zinc. Cancellation is saved before notification, with in-memory
rollback on storage failure. Configuration and existing storage remain compatible.

## v0.4.2: Visible submission and refresh results

`reorder.submit_batch_zinc` and `reorder.refresh_batch_zinc` now show the batch ID,
Zinc status, and sandbox/live mode in a persistent notification. Refresh updates the
same notification instead of adding one on every call. Both actions support optional
responses for scripts; existing callers still work without requesting a response.
Saved batches include `last_refreshed_at` after a successful refresh. Notification
failures cannot turn a successful save into a failed action.

Zinc v2 `pending` orders block duplicate purchases for the same product. Invalid
refresh responses leave the previously saved status intact. Failed batches remain
locked against resubmission; reconcile with Zinc instead of submitting again.
Configuration, entity IDs, and the existing storage version/key are unchanged.

## v0.4.1: Reliable batch actions

Batch preview and preparation use Home Assistant's supported persistent notification API.
Preparing a batch saves its ID and product assignments before displaying a notification.
Notification failures are logged and do not report a failed preparation: check the
**Prepared batches** sensor attributes or request the action response for the batch ID.
Preview and preparation never submit purchases. See [batching and regression tests](BATCHING.md).

Repeated or simultaneous preparation cannot assign the same queued order to multiple
batches. If no unbatched eligible orders remain, the action reports `No eligible queued
Zinc orders`. With additional eligible orders, a later call may prepare a separate,
disjoint batch. Existing configurations and `reorder.catalog_v1` storage remain compatible.

Submission is persisted before Zinc I/O. Attempted submissions cannot be reopened by
provider status changes, and unknown outcomes require manual reconciliation with Zinc.
Sandbox/live key checks, live opt-in, and exact confirmation phrases remain required.
No real orders or payment credentials are used in automated tests.

## v0.3.1: Default quantity and ranked substitutions

- Product catalog already supports `quantity` (1–20). Shopping-list `coffee` triggers the configured quantity, e.g. two bags, rather than quantity one.
- New catalog fields: First substitution and Second substitution (complete HTTPS product URLs). Up to two alternatives, tried in rank order.
- Order records snapshot quantity, substitute URLs, and price cap at queue time. Editing the catalog does not silently change an existing queued order.
- Once an order has been **confirmed** out of stock, use `reorder.queue_next_substitution` with its order ID. This creates a NEW queued order with the next URL; it does NOT purchase. You must separately submit the replacement with `reorder.submit_zinc`.
- **Not automated yet:** On status refresh, v0.3.1 recognizes a `failed` order with explicit `out_of_stock` error code (top-level `error_code` or nested `error.code`). Other payload shapes require adapter testing. The next substitution is queued only by the manual action below, not automatically bought. Do not retry uncertain orders.
- Quantity applies equally to preferred and substitute product. Select alternatives with comparable package sizes, and configure a total price cap high enough for quantity plus taxes and shipping.

## v0.3.0: Zinc provider

- Catalog management in **Settings → Devices & services → Reorder → Configure**.
- Exact name/alias matching, cooldowns, and duplicate prevention on shopping-list additions.
- New **Zinc API and shipping settings** under Configure.
- Zinc orders use `POST https://api.zinc.com/orders`, with exact product URL, quantity, complete order price cap (`max_price` in cents), address, and stable idempotency key.
- **No automatic purchasing from shopping-list additions.** A matching item is queued locally; use the explicit `reorder.submit_zinc` action to transmit it.
- Live purchasing is OFF by default; test keys (`zn_test_`) use Zinc's sandbox. Live requires a `zn_live_` key, enabling live in options, and the exact `PLACE LIVE ORDER` confirmation in the action.
- `reorder.refresh_zinc` retrieves current status. Zinc orders are asynchronous; API acceptance does **not** mean the retailer placed the order.
- Submission is marked durably before the network call. If network response is uncertain, review Zinc before taking further action; the same idempotency key must be reused to prevent duplicates.

### Important safety and privacy

A real order can charge your funded Zinc wallet, including shipping/tax, within the configured total-order ceiling. `max_price` is a **total order cap in USD**, including tax and shipping, not a unit price. Address and API key are stored in Home Assistant's config-entry options. Protect your HA instance, backups, and diagnostics; never commit secrets to Git.

The sandbox success path has been manually exercised in a development Home Assistant instance. Automated regression tests use mocked Zinc transport; live purchasing and the full range of sandbox failures remain unverified. Test carefully before enabling live mode. Order status is retrieved manually (webhooks and automated polling are planned). No automated shopping-list removal or queue retry is performed.

## Install

Copy `custom_components/reorder` to `/config/custom_components/reorder`, restart Home Assistant, and add **Reorder** under Settings → Devices & services. Existing v0.2 catalog storage (`reorder.catalog_v1`) is retained.

### Configure Zinc

1. Create a Zinc account or sandbox key at [Zinc](https://www.zinc.com/developers). For sandbox, use a test key starting `zn_test_`.
2. Go to **Reorder → Configure → Zinc API and shipping settings** and enter the Zinc key and shipping address. Keep **Enable live Zinc purchasing** turned off.
3. **Reorder → Configure → Add product**: choose `zinc`, and set `product_id` to a full HTTPS retailer product URL (e.g. an Amazon `/dp/...` link). Set a maximum **total order** cost, quantity, and aliases.
4. Add the exact product name or alias to Home Assistant's shopping list. The queued order ID appears under the `Queued orders` sensor's `orders` attribute.
5. Call **Developer Tools → Actions → `reorder.submit_zinc`**:

```yaml
action: reorder.submit_zinc
data:
  order_id: REPLACE_WITH_QUEUED_ID
  confirmation: SANDBOX
```

6. View order state in the sensor attributes. To query Zinc again:

```yaml
action: reorder.refresh_zinc
data:
  order_id: REPLACE_WITH_QUEUED_ID
```

**Live orders:** Only after testing, configure a `zn_live_` key, enable live purchasing, and explicitly submit with `confirmation: PLACE LIVE ORDER`. This **can spend real money**. Existing sandbox order records must not be refreshed with a live key (or vice versa).

## Git / publishing under Grayco

Create an empty GitHub repository `Grayco/reorder`, then from the extracted project directory:

```bash
git init
git branch -M main
git add .
git commit -m "feat: Zinc sandbox ordering and guarded live submission (v0.3.0)"
git remote add origin https://github.com/Grayco/reorder.git
git push -u origin main
```

If you already have a cloned repository, copy updated files into it, then:

```bash
git status
git add .
git commit -m "feat: add Zinc provider v0.3.0"
git push origin main
```

After testing, release a prerelease tag:

```bash
git tag -a v0.3.0 -m "Reorder v0.3.0"
git push origin v0.3.0
```

Create a GitHub Release from that tag and mark it **Pre-release**. To install from HACS, open HACS → Custom repositories, add your repo URL, and choose **Integration**. The repo contains `custom_components/reorder`, `hacs.json`, and `.github/workflows/validate.yml`.

## Next milestones

- Automatable Zinc submission behind per-product purchasing enablement and whole-house monthly caps.
- Webhook verification and status tracking including delivery.
- More descriptive statuses, confirmation via dashboard, easier product lookup, secrets/password selector improvements.
- Kroger cart provider.

Documentation: [Zinc quickstart](https://www.zinc.com/docs/quickstart), [Zinc developer guide](https://www.zinc.com/developers).

### Replacement workflow (Zinc sandbox)

After submitting the preferred product, refresh order status. Only if Zinc returns `status: failed` AND `error.code: out_of_stock` (or `error_code: out_of_stock`), the order becomes `out_of_stock`. Then use:

```yaml
action: reorder.queue_next_substitution
data:
  order_id: ORIGINAL_ORDER_ID
```

Find the new queued order ID under the Reorder queue sensor and submit with `reorder.submit_zinc` using `confirmation: SANDBOX`. If that also fails out of stock, refresh its status and queue the second alternative using its ID. Different errors, timeouts, or ambiguous responses do not trigger substitution. No automatic live purchasing is implemented.

### Gitea update

From your existing Gitea checkout, replace the contents with this package, then:

```bash
git add .
git commit -m "feat: quantity and ranked Zinc substitutes (v0.3.1)"
git push origin main
```

Do not push a release tag until you've tested against Home Assistant and Zinc sandbox.

## v0.4.0 — Batch queue (development)

See [BATCHING.md](BATCHING.md) for the complete Gitea workflow, deployment and sandbox test instructions. Batches are review-first: schedules **never** submit transactions automatically. Prepared batches contain up to 10 distinct Zinc catalog items; quantities are retained and the sum of per-product price ceilings becomes the overall batch ceiling. `reorder.preview_batch`, `reorder.prepare_batch`, `reorder.submit_batch_zinc` and `reorder.refresh_batch_zinc` are available in Developer Tools → Actions.

Do not enable live Zinc transactions until a sandbox order has successfully exercised the multi-line request and the provider's response handling has been checked. Partial fulfillment and per-product substitution inside a batch are not automated in this release.
