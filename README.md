# Reorder by Grayco

Home Assistant custom integration for routing exact, preapproved shopping-list items to a persistent order queue, with **Zinc API submission (sandbox first)**.

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

No verified sandbox transaction or Home Assistant runtime integration test has been performed for this release. Test carefully before enabling live mode. Order status is retrieved manually (webhooks and automated polling are planned). No automated shopping-list removal or queue retry is performed.

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
