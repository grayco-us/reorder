# Legacy Reorder dashboard

For v0.5.0 and later, the [automatic sidebar app](SIDEBAR.md) is the recommended
interface and needs no dashboard YAML. This guide remains for existing dashboards
and users who prefer native cards.

The starter dashboard uses only built-in Home Assistant cards and Reorder's native
entities. It has no purchase/submit control and needs no custom frontend plugin.
Install integration v0.4.5 or later before importing the current YAML. The Sections
layout uses only native cards supported by the tested Home Assistant 2025.12.5 runtime.

## Install in the UI

1. Update/deploy the integration and restart Home Assistant. Existing batches and
   configuration are retained. Confirm the new entities exist under **Settings →
   Devices & services → Entities**, filtered to Reorder.
2. Under **Settings → Dashboards**, create a new empty dashboard named **Reorder**
   and enable its sidebar entry. Keep your existing dashboards.
3. Open that new dashboard, choose **Edit dashboard**, then open the three-dot menu
   and **Raw configuration editor**. If prompted, take control of this new empty
   dashboard only.
4. Replace that new dashboard's configuration with the contents of
   [dashboards/reorder.yaml](dashboards/reorder.yaml), then save.
5. Choose a saved batch in **Choose a batch**. Its contents appear directly below
   the selector. Refresh and Cancel locally become available when appropriate.

On the development host, the YAML is in the checkout at
`/opt/grayco/projects/reorder/dashboards/reorder.yaml`. `deploy-dev.sh` installs the
integration files; it does not create or overwrite dashboards. Import the YAML once
through the UI. Later integration updates preserve that dashboard. To update the
starter layout later, review the new YAML before replacing your customized layout.

## Entities used by the starter

| Entity | Purpose |
| --- | --- |
| `sensor.reorder_purchasing_mode` | Sandbox, Live enabled, Live disabled, Not configured, or Invalid key |
| `sensor.prepared_batches` | Count of ready batches and the most recent 25 batch records |
| `sensor.queued_orders` | Number of queued product lines |
| `sensor.approved_products` | Number of enabled catalog products |
| `select.reorder_batch` | Choose a batch by ID and readable status; provides the inline product details |
| `button.reorder_review_batch` | Retained notification-based review control for existing callers; not needed in the current layout |
| `button.reorder_refresh_batch` | Retrieve Zinc status for the selected submitted batch |
| `button.reorder_cancel_batch` | Cancel a selected ready batch and its queued orders locally |

These are default entity IDs. If you renamed entities or Home Assistant added suffixes
such as `_2`, replace the corresponding IDs throughout the YAML, including template
references and button targets. Existing sensor IDs and unique IDs were not changed.

## What the controls do

- **Preview queue** displays eligible unbatched products without making changes.
- **Prepare batch** saves up to 10 eligible product lines locally; it does not purchase.
- **Batch contents** appears automatically when a ready, submitted, or canceled batch
  is selected. It displays the saved product names, HTTPS links, quantities, line-item
  ceilings, total ceiling, mode, and status. No action, notification, or Zinc request
  is needed to review these details. Catalog changes do not rewrite saved order lines.
  The existing `review_batch` action and review button remain available for scripts
  and older dashboards that use persistent notifications.
- **Refresh** is available only when the selected batch has a Zinc order ID and its
  sandbox/live environment matches the configured key. Live mode must be enabled for
  live-key access. It retrieves status; it never submits or retries an order.
- **Cancel locally** requires confirmation in this dashboard and works only for a
  never-submitted ready batch. It cancels the batch AND its queued orders, retaining
  history. This is not a retailer cancellation and does not requeue those lines.

Selected detail attributes (`batch`, `orders`, and `review_error`) come from the full
stored batch, including records older than the 25-row history window. Only product
and batch fields are exposed; keys and shipping addresses are excluded. Missing or
reassigned product records display a clear error rather than misleading partial contents.

The selector tracks the batch ID, so an updated status label does not switch the
selection to another batch. Selection intentionally resets after restart or integration
reload. Controls cannot execute until you explicitly select a batch again. The
integration's service-side guards still apply if a batch changes while a button is
being pressed. Dashboard confirmation is a UI convenience; the existing `cancel_batch`
action remains callable directly as documented.

Mode indication comes from key type and the live-enable setting; keys and shipping
addresses are never exposed in the mode sensor. Configuring a sandbox key continues
to select Zinc's isolated sandbox. The dashboard does not change purchasing settings.

## Empty or unavailable displays

An empty batch list is normal before preparation. Submitted batches move from **Ready
for review** to **Submitted and past batches**; the ready count can therefore fall to
zero after a successful submission. Refresh updates the displayed status and timestamp.
Timestamps are formatted in Home Assistant's configured local timezone. Status labels
such as **Order placed** and **Needs reconciliation** are display-only; raw provider
status values in storage and service responses remain unchanged. Selector option text
now uses these readable labels; any scripts matching old option text need updating.
The lists show the most recent 25 stored batches; the selector includes all saved
batches, including older ones that can still be reviewed.

If an entity is unavailable, confirm that a batch is selected and eligible for that
control. After an upgrade, missing selector/button entities usually mean the integration
has not restarted or an entity ID differs from the defaults above. Refresh failures
appear as Home Assistant action errors and preserve the previously saved status.

## Validation

Automated tests load the real sensor/select/button platforms, exercise selector and
button service calls, check sandbox/live availability and restart behavior, and render
the dashboard templates with empty, selected, submitted, and incomplete product data.
Tests verify that selection and inline review create no notification or network request,
use saved product snapshots, escape product text, and format local timestamps. Zinc transport and unrelated
multicast discovery are mocked. The dashboard configuration is also checked to contain
only native cards and preview/prepare/button actions, with confirmation for local
cancellation. A browser visual check and installation in your own Home Assistant are
still required; the agent cannot access that instance.

## Updating from v0.4.4

Deploy/restart the integration, then replace the Reorder dashboard's raw YAML with
the new starter YAML if you want the grouped Sections layout. Preserve a copy of any
layout customizations first, and carry over renamed entity IDs. Existing dashboard
configuration is not rewritten automatically. No storage migration is needed.
The first section now contains the selector, inline contents, and controls; the second
contains the queue overview and history. On narrow screens the sections stack in that
order, keeping the selected batch's details and controls together.
