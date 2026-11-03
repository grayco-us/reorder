# Reorder sidebar app (v0.11.1)

> **v0.12.0 terminology:** The app calls the queue **Cart** and prepared batches
> **Orders**. Existing action names/IDs remain unchanged. See
> [Cart and Orders](CART_AND_ORDERS.md) for editing, local removal and frozen review.


Reorder now bundles its own responsive frontend and automatically adds **Reorder**
to Home Assistant's sidebar. There is no dashboard YAML to paste, no resource URL
to register, and no separate frontend plugin or build step to install.

This follows the integration-owned sidebar approach demonstrated by
[HA-HelloFresh](https://github.com/kedube/HA-HelloFresh). Reorder's interface is
independently implemented for its queue and batch workflow; no HelloFresh account,
API, or frontend dependency is involved.

## Upgrade

1. Pull/deploy the current feature branch as usual and restart Home Assistant.
2. Refresh your browser. A **Reorder** sidebar entry should appear for administrator
   users. Open it and choose an order to see its contents.
3. Once the app is working, you may hide the old manually created Reorder dashboard
   in **Settings → Dashboards**. Reorder does not delete or overwrite dashboards.

The panel lives at `/reorder-app`; static frontend files are served separately under
`/reorder-assets`. The asset URL includes the integration version, so restarting
Home Assistant after an upgrade points browsers at the new build. If the UI still
looks stale, hard-refresh the browser or reload the companion app frontend.
Existing configuration, storage, sensors, selectors, buttons and service actions are
retained. No batch migration or API-key re-entry is required.

## Current interface

- **Orders:** All / Ready / History filters, saved status, mode and spending ceiling.
  Selecting an order opens product names and HTTPS links, quantities, line ceilings,
  total ceiling, timestamps and the Zinc order ID when present. No notification is
  needed to review contents.
- **Queue:** The next up to 10 eligible Zinc order lines and their combined ceiling.
  **Prepare order for review** creates local work only, then opens the new order.
- **Refresh status:** Retrieves provider status through the existing guarded action.
  It is unavailable without a Zinc order ID or when the key environment differs.
- **Cancel locally:** Requires an explicit confirmation tied to that order ID and
  cancels only never-submitted ready orderes and their queued order lines. Submitted
  or uncertain work must be reconciled with Zinc. This is not retailer cancellation.
- **Shopping List activity** in Queue explains whether recent additions were queued
  or skipped. It shows the latest 20 received additions since restart, without saving
  a permanent activity history. Expand the catalog summary to check names, aliases,
  retailer and enabled state. A missing built-in Shopping List source is shown explicitly.
- **Products:** Create/edit approved products, manage aliases, quantity, ceilings,
  cooldown and substitutions, enable/disable matching, or confirm removal. Existing
  order snapshots are not rewritten. Names with order history are locked; use aliases.
- **Settings:** Save batch schedules and Shopping List synchronization preferences.
  The linked native configuration continues to handle keys, delivery and live setup.
- **Reload:** Reads the currently saved Reorder state; it does not refresh Zinc orders.
- **Connection:** Opens the existing Reorder integration configuration.

Ready sandbox orderes now have a typed-confirmation submission control. The backend
requires a test key independently of the browser. Live-enabled administrators also have **Review live order**, with a separate real-money
warning, saved-content acknowledgement and **PLACE LIVE ORDER**. Native actions retain
their existing safeguards. See [the ordering guide](ORDERING.md)
for item outcomes, periodic Zinc status checks and delivery/list synchronization.
Purchases are never retried or scheduled automatically. Reorder does not poll carriers
directly or cancel retailer orders.

Selection belongs to each browser panel, so two users/browsers can review different
batches without changing one another's selection. It resets when the panel is recreated.
Legacy native selector/button controls remain shared Home Assistant entities as before;
the new app does not use them. Changing the selected batch clears any pending local
cancellation confirmation. Backend action guards always recheck persisted state.

## Access and data

The sidebar and its `reorder/panel` WebSocket command require an authenticated
administrator. The frontend receives only local product/batch summaries, mode and
capabilities, never API keys, shipping addresses, config-entry options, or raw Zinc
responses. It uses Home Assistant's existing authenticated connection; no credentials
are stored by the browser component. Product text is escaped and links permit HTTPS
without embedded usernames/passwords only.

Local changes are reflected through Reorder update events. Refreshing a provider order
also runs every 15 minutes for tracked batches; the button checks immediately. Action errors appear inline, while saved state remains
available for review; uncertain submissions are clearly marked for reconciliation.
If frontend registration fails, the integration logs the error and keeps its existing
entities and actions working. A conflicting `/reorder-app` panel is not overwritten.

## Validation and development

Backend and service regression tests (Python 3.13):

Create the isolated environment and install both pinned dependencies as described in
[TESTING.md](TESTING.md) before running these commands.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Dependency-free frontend tests (Node 22+):

```bash
node tests/test_panel.mjs
```

Optional browser smoke test when Playwright and Chromium are installed:

```bash
REORDER_CHROMIUM_PATH=/usr/bin/chromium node tests/test_panel_browser.cjs
```

The browser test intercepts requests and serves only local fixture files, mocks every
Home Assistant call, checks desktop/mobile interactions, cancellation confirmation,
errors and text escaping, and captures screenshots. `REORDER_ARTIFACT_DIR` can select
an output directory; the default is `reorder-panel-artifacts` in the OS temporary
folder. No Zinc requests or real purchases are made by these tests. Screenshot data
is synthetic and is not evidence of installation in a user's Home Assistant instance.

The backend tests verify admin authorization, the credential-free response schema,
panel/cache registration, unload/reload behavior, and existing purchasing safeguards.
CI runs the backend and dependency-free frontend suites; browser tests are optional.

## If adding a Shopping List item does not queue it

1. Use Home Assistant's built-in **Shopping List**; arbitrary other to-do integrations
   are not monitored. Queue shows whether that source is configured and loaded.
2. Expand **Configured product names and aliases** and check the exact name/alias,
   enabled state, and retailer. Matching ignores case and extra spaces, but does not
   use fuzzy/substring matching. Zinc orders include Zinc products only.
3. Add a fresh item, then inspect **Shopping List activity**. Items added before the
   upgrade/restart are not automatically replayed. Removing and re-adding an item
   produces a new addition event without deleting any order history.
4. Follow the displayed reason. Existing queued, active, completed, or uncertain
   orders retain their current duplicate protection. Do not clear storage or resubmit
   uncertain orders to get around it. A real submission can still trigger cooldown.

A canceled local batch/order has never been sent to Zinc. In v0.5.1 it no longer
blocks a *fresh* item through cooldown, but its original Shopping List item remains
seen and its original order stays canceled. This is not an automatic retry or an
automatic restoration of canceled work. A queued `other`/`kroger` product is still
catalog-only: activity explains why it does not appear in the next Zinc order.

End-to-end tests exercise both `shopping_list.add_item` and the built-in
`todo.add_item` UI path with exact names/aliases, rather than only calling the matcher.

## Shopping List synchronization and in-app setup

See [Shopping List and configuration flows](FLOWS.md) for the complete behavior table.
Completion/removal cancels unsubmitted work; edits that change the approved product
invalidate a prepared order and return unaffected lines for fresh review. Submitted
purchases are never canceled by a list edit. The app shows **Needs fresh review** and
the historical canceled/returned lines. Products and Settings are available as new
app pages after deployment/restart and a browser refresh; no dashboard import is needed.

## Order stage (v0.8.0)

See [Sandbox ordering and receipt](ORDERING.md) for the full walkthrough. A ready order
in Sandbox mode can be submitted after a typed confirmation. Tracking, item failures,
partial fulfillment and reported totals appear after refresh. Explicit selected receipt
can check off exact linked list IDs. Confirmed delivered lines now complete their
original list IDs automatically by default; placement never implies delivery. Settings
provides an independent switch to keep receipt manual. Missing/mismatched provider details disable automated list completion.

## Live-trial guidance

The mode notice explains Sandbox, Live disabled and Live enabled. Expand **What these
terms mean** for queue/batch states, ceilings, delivery, list completion and recovery.
See [LIVE_TESTING.md](LIVE_TESTING.md) for in-app live review and the native alternative.
Live review is bound to saved order contents and connection options. A change or an
integration reload invalidates the confirmation; administrators must review again.

## Notifications

Settings now includes event selection, destination pickers, Kiosk Satellite card
presentation and a test button. Cart additions mean local queued requests, and batch
review reminders mean saved unsubmitted work. Nothing is bought from a notification.
See [NOTIFICATIONS.md](NOTIFICATIONS.md) for setup and delivery guarantees.

## Tracking and recovery

Use **Needs attention** for guided recovery and per-line delivery/list outcomes.
Manual refresh stays available with matching credentials even when live purchasing is
off. See [RECOVERY.md](RECOVERY.md); no recovery control retries a purchase or clears
uncertain submission history.

## Quiet activity history (v0.11.1)

The Queue activity panel shows meaningful changes and matching results. Routine
unchanged reconciliation checks no longer add repeated **Same product** entries.
Actual name edits show **Name updated**; repeated periodic blockers appear again when
the result changes. Queue recovery, source synchronization and purchasing guards are
unchanged. Restart Home Assistant after updating, then refresh the browser; the old
per-run activity clears without deleting any configuration or order history.
