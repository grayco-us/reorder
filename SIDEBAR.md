# Reorder sidebar app (v0.5.1)

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
   users. Open it and choose a batch to see its contents.
3. Once the app is working, you may hide the old manually created Reorder dashboard
   in **Settings → Dashboards**. Reorder does not delete or overwrite dashboards.

The panel lives at `/reorder-app`; static frontend files are served separately under
`/reorder-assets`. The asset URL includes the integration version, so restarting
Home Assistant after an upgrade points browsers at the new build. If the UI still
looks stale, hard-refresh the browser or reload the companion app frontend.
Existing configuration, storage, sensors, selectors, buttons and service actions are
retained. No batch migration or API-key re-entry is required.

## Current interface

- **Batches:** All / Ready / History filters, saved status, mode and spending ceiling.
  Selecting a batch opens product names and HTTPS links, quantities, line ceilings,
  total ceiling, timestamps and the Zinc order ID when present. No notification is
  needed to review contents.
- **Queue:** The next up to 10 eligible Zinc order lines and their combined ceiling.
  **Prepare batch for review** creates local work only, then opens the new batch.
- **Refresh status:** Retrieves provider status through the existing guarded action.
  It is unavailable without a Zinc order ID or when the key environment differs.
- **Cancel locally:** Requires an explicit confirmation tied to that batch ID and
  cancels only never-submitted ready batches and their queued order lines. Submitted
  or uncertain work must be reconciled with Zinc. This is not retailer cancellation.
- **Shopping List activity** in Queue explains whether recent additions were queued
  or skipped. It shows the latest 20 received additions since restart, without saving
  a permanent activity history. Expand the catalog summary to check names, aliases,
  retailer and enabled state. A missing built-in Shopping List source is shown explicitly.
- **Reload:** Reads the currently saved Reorder state; it does not refresh Zinc orders.
- **Settings:** Opens the existing Reorder integration configuration.

There is no submit/purchase control in this release. Explicit sandbox/live submission
still uses the existing actions and their confirmation requirements. The app adds no
automatic retry, purchasing schedule, or retailer cancellation behavior.

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
is an explicit button action. Action errors appear inline, while saved state remains
available for review; uncertain submissions are clearly marked for reconciliation.
If frontend registration fails, the integration logs the error and keeps its existing
entities and actions working. A conflicting `/reorder-app` panel is not overwritten.

## Validation and development

Backend and service regression tests (Python 3.13):

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
   use fuzzy/substring matching. Zinc batches include Zinc products only.
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
catalog-only: activity explains why it does not appear in the next Zinc batch.

End-to-end tests exercise both `shopping_list.add_item` and the built-in
`todo.add_item` UI path with exact names/aliases, rather than only calling the matcher.
