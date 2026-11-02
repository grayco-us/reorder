# Reorder by Grayco

Turn Home Assistant Shopping List items into reviewed purchases, with a saved product
catalog, a local cart, Zinc ordering, delivery tracking, and list completion.

**Current development version: v0.11.0.** Adding an item or preparing a batch never
places an order. Purchases require explicit confirmation; live purchasing is off by
default.

The v0.11.0 development work is now on
[`main`](https://github.com/grayco-us/reorder/tree/main), following
[PR #2](https://github.com/grayco-us/reorder/pull/2). Use the installation instructions
below; the original development branch has been removed after merging.

## How it works

1. **Add to your list.** Add an enabled catalog product's name or alias to Home
   Assistant's built-in Shopping List, including through your existing voice/Assist flow.
2. **Review your cart.** Reorder matches the item and saves a local queued request.
   Queue activity explains unmatched names, disabled products, cooldowns and existing
   orders. The cart is local work, not a retailer cart or a purchase.
3. **Prepare a batch.** Manually prepare up to 10 distinct eligible Zinc product lines,
   or use a weekly/rolling preparation schedule. The batch saves its product URLs,
   quantities and spending allowances for review. Later catalog edits do not rewrite it;
   new list additions wait in the queue for another batch.
4. **Explicitly submit.** Sandbox orders require **SANDBOX**. Live orders require a
   live key, live purchasing enabled, reviewed saved contents and spending limit, and
   **PLACE LIVE ORDER**. Notifications and kiosk taps never approve a purchase.
5. **Track the order.** Read per-item outcomes, reported costs, tracking and list-update
   results in the Reorder sidebar. Unresolved batches refresh every 15 minutes, up to
   10 per pass; **Refresh status** checks immediately.
6. **Complete the list after delivery.** By default, confirmed delivered lines check off
   their original Shopping List entries. Completed entries leave the active list and
   remain in completed history. Placement alone does not complete anything.

## What is included

- An administrator-only sidebar app with **Batches**, **Queue**, **Products** and
  **Settings**, using Home Assistant themes and local time. No manual dashboard YAML
  or custom frontend card is required.
- Exact product-name/alias matching, configured retailer quantities, cooldowns and
  duplicate-purchase protection.
- Separate Sandbox and live submission flows. In-app live confirmation is bound to
  saved batch contents and connection settings; changes or an integration reload
  require a fresh review.
- Shopping List add, rename, completion, unchecking, removal and bulk-change handling,
  plus periodic reconciliation after missed events or downtime.
- Delivery completion using an explicitly delivered item or exact links to all known
  delivered packages carrying it. Inferred, unknown or incomplete mappings stay open.
- Configurable cart, batch-review, order-status, delivery and attention notifications,
  including Kiosk Satellite's built-in notification cards.
- A **Needs attention** filter with guided handling of uncertain submissions, partial
  failures, tracking errors, list-update failures and credential mismatches.
- Persistent catalog/order history, supported native actions/entities, and compatibility
  with existing Reorder configuration and storage.

| Provider | Current support |
| --- | --- |
| Zinc | Sandbox and explicitly confirmed live purchasing using full HTTPS product URLs |
| Kroger / Other | Catalog placeholders; not eligible for Zinc batches or purchasing |

## Install or update

The current code on `main` can be installed manually. Repository/HACS metadata alone
does not establish that a tagged release is available through HACS.

1. Create and download a Home Assistant backup before updating a production instance.
2. [Download the main branch ZIP](https://github.com/grayco-us/reorder/archive/refs/heads/main.zip)
   and extract it.
3. Copy **only** `custom_components/reorder/` into your Home Assistant configuration
   directory, normally `/config/custom_components/reorder/`. For an update, replace the
   integration folder. Avoid an extra nested `reorder` directory.
4. Restart Home Assistant, then refresh your browser. The integration manifest should
   show version `0.11.0`.
5. For a fresh installation, add **Reorder** under **Settings → Devices & services →
   Add integration**. Ensure Home Assistant's built-in **Shopping List** integration
   is configured and loaded. Open **Reorder** in the sidebar as an administrator.

For updates, keep existing configuration and `reorder.catalog_v1` storage. Do not delete
history or copy development-instance storage into production. Existing entities,
actions and optional manual dashboards remain supported. API keys, delivery details
and live purchasing opt-in stay in the native Reorder configuration, linked through
**Connection** in the app.

## Start with Sandbox

1. In **Connection → Zinc API and delivery settings**, configure your own `zn_test_`
   key and test shipping details. Leave **Enable live Zinc purchasing** off.
2. In **Products**, add an enabled Zinc test product with an exact matching name,
   quantity, HTTPS URL and spending allowance. For a documented success scenario,
   use `https://zinc.com/shop/products/test-success`.
3. Set batch preparation to **Manual** in Settings. Add the product's exact name or
   alias to the built-in Shopping List, then inspect **Queue**.
4. Choose **Prepare batch for review**. Inspect the saved URLs, pack sizes, quantities
   and combined spending limit.
5. Choose **Submit sandbox batch**, type **SANDBOX**, and confirm once. Follow results
   using **Refresh status** and automatic tracking.
6. To exercise list completion before simulated delivery appears, use **Complete test
   list items**, select eligible successful lines, and type **SIMULATE RECEIPT**. This
   updates your real HA list but does not claim physical delivery or submit an order.

Use [ORDERING.md](ORDERING.md) for the complete Sandbox walkthrough, failure scenarios
and delivery-mapping limits. Sandbox tracking can be simulated or incomplete.

## Product matching and spending limits

| Setting | Meaning |
| --- | --- |
| Name / aliases | Exact matching ignores case and extra spaces. List text is not fuzzy-matched or parsed for quantities. |
| Quantity | Fixed retailer units per request. Check the pack size and variant at the saved product URL. |
| Price allowance | USD contribution for those units, including tax/shipping. Batch allowances are summed into **one order cap**, not separate provider-enforced line caps. This is not a quote. |
| Cooldown | Blocks repeat requests; 168 hours is 7 days. First confirmed delivery or recorded receipt anchors the cooldown when available. Pending/uncertain purchases remain protected. |
| Enabled | Controls new catalog matches. Disabling or removing a product does not cancel existing work or purchases. |

Zinc's reported total is not proof of final payment settlement. Check its current fees,
funding and authorization terms separately. Ranked substitutes support the existing
manual standalone out-of-stock workflow; batches do not switch products automatically.

## Shopping List changes

Checking off or removing a linked item cancels its **unsubmitted** local request. If it
belongs to a ready batch, that batch needs fresh review and its unaffected lines return
to the queue. Renaming to a different product follows the same invalidation policy;
an alias for the same product retains the saved quantities and allowances.

Submitted and uncertain purchases are never canceled by list edits. Delivery completion
uses the original item ID, so it cannot clear a replacement entry merely because the
name matches. Once completion is recorded, deliberately unchecking that entry is
respected. Add a fresh entry for a new request; active-order and cooldown checks still
apply. Unchecking also does not revive manually canceled work.

Source-change synchronization and automatic delivery completion have separate switches
in Settings. Missing source state is never assumed to mean an empty list. See
[FLOWS.md](FLOWS.md) for the detailed behavior matrix.

## Notifications and Kiosk Satellite

Under **Settings → Notifications**, choose events and destinations, save, then use
**Send test notification**. Supported destinations include the shared Home Assistant
notification panel, loaded notify actions/entities, and
[Kiosk Satellite](https://github.com/jxlarrea/kiosk-satellite) notification cards.

For Kiosk Satellite, enable **Expose kiosk entities**, connect its ESPHome integration,
then select the discovered kiosk in Reorder. Configure card duration, text scale and
optional chime. Cards are informational: tapping dismisses them rather than approving
an order. Open Reorder to review a batch.

Notifications can reveal product names, quantities and order outcomes to selected
recipients or shared screens. They do not include connection credentials, delivery
addresses or payment fields. Messages are best effort; a notification failure does not
undo saved work. See [NOTIFICATIONS.md](NOTIFICATIONS.md) for defaults, recipient
privacy, voice-to-cart behavior and device setup.

## First live purchase

Follow [LIVE_TESTING.md](LIVE_TESTING.md) for one small user-run trial after Sandbox
and notification checks succeed. Live orders can spend real money. Use an actual
retailer product URL, not a Sandbox scenario URL.

With live credentials and purchasing enabled, select a ready batch, choose **Review
live order**, check its saved contents and combined ceiling, acknowledge the review,
and type **PLACE LIVE ORDER** before submitting once. The native action remains an
alternative. Turning purchasing off afterward prevents new live submissions; matching-key
tracking and manual refresh continue without needing shipping details. Configured
confirmed-delivery list completion can still run.

An uncertain submission may already have created an order. Check **Needs attention**
and the matching Zinc account before any further purchase. Never clear storage,
invent an order ID or create another batch to bypass a lock. If no Zinc ID was returned,
dashboard/support reconciliation is necessary. **Cancel locally** cannot cancel a
retailer purchase; retailer cancellations, returns and refunds happen outside Reorder.
See [RECOVERY.md](RECOVERY.md).

## Validation and current limits

The Python regression baseline is **Home Assistant 2025.12.5 / Python 3.13** with its
matching frontend package. This is the tested baseline, not a claim that every HA
version is supported. The current suite contains **162 backend tests and 29 frontend
tests**, plus optional desktop/mobile browser checks.

Automated purchasing and notification checks use mocked transport, temporary HA
configurations and synthetic credentials. They do not place real orders or contact a
physical phone/kiosk. Sandbox submission/refresh has been exercised separately in a
development HA instance; actual live purchasing, device notifications and delivery
behavior require verification in your own installation.

Current boundaries:

- Built-in Shopping List only; no other to-do providers or speaker-identity routing.
- No automatic purchases from list additions, schedules, notifications or recovery.
- Periodic Zinc batch tracking; no webhook endpoint or direct carrier polling.
- Legacy standalone orders use manual refresh and are not included in automatic
  batch delivery-to-list completion.
- Ambiguous mappings and uncertain submissions without IDs require manual reconciliation.
- No automatic batch substitutions, retailer cancellations or refunds.

For reproducible local/CI setup, see [TESTING.md](TESTING.md). CI explicitly installs
Home Assistant's matching frontend package before tests and uses a virtual environment.
Keep feature changes on a branch and submit a pull request; do not merge directly into
`main`.

## Documentation

| Guide | Purpose |
| --- | --- |
| [Sidebar app](SIDEBAR.md) | App access, controls and compatibility |
| [Batching](BATCHING.md) | Batch planning and native actions |
| [Ordering](ORDERING.md) | Sandbox tests, tracking and receipt |
| [Live testing](LIVE_TESTING.md) | First real purchase walkthrough |
| [List flows](FLOWS.md) | Adding, editing, completing and removing items |
| [Notifications](NOTIFICATIONS.md) | Phone/display routing and Kiosk Satellite |
| [Recovery](RECOVERY.md) | Needs-attention states and safe next steps |
| [Development checks](TESTING.md) | Isolated test environment and commands |
| [Optional legacy dashboard](DASHBOARD.md) | Manual dashboard setup; not required for the app |
| [Development history](CHANGELOG.md) | Version highlights |

Repository: [grayco-us/reorder](https://github.com/grayco-us/reorder) ·
[Issues](https://github.com/grayco-us/reorder/issues) ·
[GitHub checks](https://github.com/grayco-us/reorder/actions) ·
[Zinc documentation](https://www.zinc.com/docs)
