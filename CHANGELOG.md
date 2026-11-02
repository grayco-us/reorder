# Development history

These are development milestones, not a list of published releases. The v0.11.0 work was merged into `main` through PR #2; see the [README](README.md)
for present behavior and installation instructions. Older descriptions below are historical.

## v0.11.0

- Needs-attention filtering, per-item delivery/list progress and guided recovery.
- Matching-key refresh works without live purchase opt-in or shipping details.
- CI fix: preinstall HA's matching frontend dependency, use an isolated environment,
  and verify dependency setup before running tests. Integration version unchanged.

## v0.10.0

- In-app live batch review, saved-content acknowledgement and typed confirmation.
- Session-bound review seal invalidates confirmation after batch/connection changes.

## v0.9.0

- Configurable cart, review, status, delivery, source-change and attention notifications.
- Notify actions/entities and Kiosk Satellite cards with duration, text size and chime.
- Saved-destination test button and notification-failure isolation.

## v0.8.1

- Live-trial guide, clearer field/action help and state/spending definitions.

## v0.8.0

- Periodic GET-only batch tracking and confirmed-delivery Shopping List completion.
- Exact package/item mapping, repeat-order cooldown and receipt retry protection.
- Periodic reconciliation of missed source events.

## v0.7.0

- In-app Sandbox submission, sanitized fulfillment/tracking details and explicit receipt.
- Partial-failure visibility and known-ID reconciliation after uncertain responses.

## v0.6.0

- Source rename, completion, unchecking, removal and bulk-change synchronization.
- Ready-batch invalidation with unaffected lines returned to the queue.
- In-app product/preferences management and native credential-preservation fixes.

## v0.5.1

- Shopping List matching activity and visible reasons for skipped/blocked requests.
- Never-submitted local cancellations no longer start purchase cooldowns.

## v0.5.0

- Bundled administrator-only sidebar app with inline batch review and queue controls.

## v0.4.5

- Inline saved batch contents in the optional manual dashboard.

## v0.4.4

- Native starter dashboard and shared batch review/refresh/cancel controls.

## v0.4.3

- Saved-batch review and guarded, idempotent local cancellation.

## v0.4.2

- Visible submission/refresh results, optional responses and saved refresh timestamps.
- Pending-state duplicate protection and invalid-response handling.

## v0.4.1

- Supported Home Assistant persistent notification API for batch actions.
- Persistence-before-notification and repeated/concurrent preparation safeguards.

## v0.4.0

- Supplied development baseline: persistent multi-line Zinc batching and review-only
  weekly/rolling preparation schedules.

## v0.3.1

- Configured quantities and ranked substitutes for the manual standalone stock-failure
  workflow.

## v0.3.0

- Zinc provider, exact catalog matching, cooldowns, explicit submission and guarded
  Sandbox/live credentials.
