# Cart and order notifications (v0.9.0)

> **v0.12.0 terminology:** The app calls the queue **Cart** and prepared batches
> **Orders**. Existing action names/IDs remain unchanged. See
> [Cart and Orders](CART_AND_ORDERS.md) for editing, local removal and frozen review.


In **Reorder → Settings → Notifications**, choose events, recipients/destinations,
and Kiosk Satellite presentation options. Save first, then **Send test notification**.
The test uses those saved destinations without changing the cart, list or any purchase.
Only administrators can configure or test delivery. New destinations default to off;
the Home Assistant notification panel remains enabled for existing installations.

## Voice-to-cart flow

1. Use your existing Assist/voice flow to add a catalog product's exact name/alias
   to Home Assistant's built-in Shopping List. Reorder matches the resulting list
   event, not the voice recording or speaker identity.
2. A successful, saved match can send **Item added to cart**: for example, “Added
   Coffee × 2 to your cart. Saved allowance $25.00. Review your cart and prepare a
   batch when ready. No purchase has been made.” Here **cart** means the local queue;
   it is not a retailer cart or an already prepared order.
3. In **Manual** mode, open Reorder → Cart and prepare the reviewed lines as an order.
   Weekly/rolling modes prepare local orders according to the existing schedule.
   Saving a new order sends **Prepared order needs review**, if selected.
4. Open Reorder to inspect saved products, quantities, mode and combined ceiling before
   explicitly submitting. A notification, its dismissal, or a reminder is never an
   approval token. No mobile/kiosk tap is connected to a purchasing action.
5. Select status, confirmed delivery, cart-change and attention messages as desired.
   Submitted orders remain protected against list edits, duplicate adds and retries.

This release does not automatically grow a prepared order on each voice addition,
change Assist's spoken response, or identify a phone/kiosk from the voice speaker.
Destinations are explicitly selected for the household/list, not inferred per voice user.
The built-in Shopping List is the source; other to-do providers are not monitored.

## Events

| Setting | When it sends |
| --- | --- |
| Item added to cart | A new matched request has been saved locally. Repeated events for the same source item do not send it again. |
| Prepared order needs review | A new local batch has been saved, manually or on schedule. Repeated preparation without new eligible lines does not create another batch/reminder. |
| Order status changes | Order submission is accepted or a saved provider status changes. An unchanged refresh does not repeat it. Off by default. |
| Confirmed delivery | A line first obtains confirmed delivery evidence, including exact package mapping. Sandbox results are explicitly labeled simulated. The message asks you to inspect the saved list result; delivery alone is not proof the list update succeeded. |
| Cart edits and list changes | A saved local Cart edit/removal or source change cancels local lines and may invalidate a prepared order. No retailer order is canceled. Off by default. |
| Failed or uncertain orders | A submission becomes uncertain, a refresh enters failed/partial fulfillment, or a new polling-failure episode begins. Repeated identical polling failures do not repeatedly alert. No purchase is retried. |

Messages are sent after the underlying cart/batch/status is saved. Delivery is best
effort and asynchronous; there is no guaranteed or replayed notification queue.
Errors at one destination do not undo saved work or stop other destinations. The page
shows counts for the most recent delivery in this running session. A failed sender may
have delivered before returning an error; use the test button deliberately rather than
repeatedly sending. Reorder does not retry outbound messages automatically.

Event choices control automatic messages. Explicitly requested preview, review and
manual action reports may still appear in the HA panel when its destination is enabled.
Turn that destination off to suppress those reports too. No destinations means no
outbound notification; the saved app/sensor state still exists. Old HA item-added notices
are retired when those lines move into a saved order; the order notice replaces them.

## Destinations and privacy

- **Home Assistant notification panel:** Shared instance-level persistent notifications,
  not a private user's inbox. Contains an **Open Reorder** link. Administrator access is
  still required to open the sidebar; recipients without that access can see messages
  but cannot review there.
- **Notify actions:** Loaded `notify.<name>` actions, such as a mobile-app notifier or a
  configured notify group. Standard `message`/`title` payload; device-specific actionable
  buttons, images and approval callbacks are not added. Configure each phone/group in
  its own HA integration, then choose it here.
- **Notify entities:** Loaded `notify.*` entities using supported `notify.send_message`.
  Title is included in plain message text so title capability is not required.
- **Kiosk Satellite:** Dedicated `esphome.<node>_notification` actions described below.

Messages can reveal catalog names, quantities, allowances, local order IDs and order
outcomes. Choose trusted destinations and groups; the integration cannot control their
lock-screen settings or who can see/hear a shared display. API keys, addresses, payment
fields and raw provider errors are not sent. Do not select multiple routes to the same
physical device unless duplicate delivery is intended. Missing previously selected
destinations remain visible as unavailable so saving does not silently remove them.

## Kiosk Satellite built-in cards

Supported through the public [Kiosk Satellite ESPHome notification action](https://github.com/jxlarrea/kiosk-satellite/blob/main/docs/esphome.md#notifications).
The payload was reviewed against upstream commit
`c2672ce516d426e8de0611d57052d68cbbc56493`; tests mock the action schema, not a real kiosk.

1. On Kiosk Satellite, enable **Expose kiosk entities**, then connect its ESPHome
   integration to Home Assistant. Confirm an action such as
   `esphome.kitchen_tablet_notification` appears under Developer Tools → Actions.
2. Reload Reorder's saved app data if necessary, then select the discovered action
   under **Settings → Notifications → Kiosk Satellite**.
3. Set card duration (0–300 seconds), text scale (1–4), and optional chime. Defaults
   are 30 seconds, scale 1 and no chime. The kiosk's configured sound/volume are used.
4. Save and send a test. Check the card appears over the dashboard/screensaver, and
   confirm the phone/panel destinations you selected receive the same test too.

Kiosk cards are informational. Tapping dismisses them; it does not open Reorder or
approve an order. Open Reorder using the kiosk's HA dashboard/sidebar. Duration **0**
keeps a card until dismissed; Reorder does not clear pinned kiosk cards automatically
or replace them by ID. The upstream API creates a distinct card for each message.
Use the default timed cards to avoid stale review reminders. Reorder never invokes the
kiosk's shell, open-URL, dismissal or other ESPHome actions. Older versions expose fewer
fields; the adapter sends only fields declared by their loaded HA service schema.

No real phone, display or kiosk notification was sent during automated verification.
See [LIVE_TESTING.md](LIVE_TESTING.md) before any real purchase.
