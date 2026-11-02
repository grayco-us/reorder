import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { makePanelData } from "./panel-fixture.mjs";

globalThis.HTMLElement = class {
  attachShadow() { this.shadowRoot = { innerHTML: "", addEventListener() {} }; }
};
globalThis.customElements = { get() { return false; }, define() {} };
const source = await readFile(new URL("../custom_components/reorder/www/reorder-panel.js", import.meta.url), "utf8");
const { ReorderPanel, escapeHTML, productURL, panelActions } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
function panel() {
  const view = new ReorderPanel();
  view._data = makePanelData();
  view._entryId = "fixture";
  view._hass = { language: "en-US", config: { time_zone: "America/New_York" } };
  return view;
}

test("product text is escaped and links permit HTTPS without embedded credentials only", () => {
  assert.equal(escapeHTML('<img src=x onerror="alert(1)">'), "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  for (const url of ["javascript:alert(1)", "http://example.com", "https://user:password@example.com", "not a url"]) assert.equal(productURL(url), null);
  assert.equal(productURL("https://example.com/item"), "https://example.com/item");
});

test("inline contents and mode render without a review action or shared selector", () => {
  const view = panel();
  view._selectedId = "ready-batch";
  view._render();
  assert.match(view.shadowRoot.innerHTML, /Cat litter/);
  assert.match(view.shadowRoot.innerHTML, /\$50\.00/);
  assert.match(view.shadowRoot.innerHTML, /Sandbox/);
  assert.doesNotMatch(view.shadowRoot.innerHTML, /select\.reorder_batch|data-action="submit|data-action="review/);
});

test("browser instances keep independent selection", () => {
  const first = panel(), second = panel();
  first._selectedId = "ready-batch";
  second._selectedId = "placed-batch";
  assert.match(first._details(), /Cat litter/);
  assert.doesNotMatch(second._details(), /Cat litter/);
  assert.match(second._details(), /Sandbox success test/);
});

test("local cancellation requires explicit confirmation bound to the batch ID", async () => {
  const view = panel(), calls = [];
  view._hass.callWS = async message => { calls.push(message); return message.type === "reorder/panel" ? makePanelData() : {}; };
  await view._action("cancel_batch", "ready-batch");
  assert.equal(calls.length, 0);
  view._confirmCancel = "placed-batch";
  await view._action("cancel_batch", "placed-batch");
  assert.equal(calls.length, 0);
  view._confirmCancel = "ready-batch";
  await view._action("cancel_batch", "ready-batch");
  assert.equal(calls[0].service, "cancel_batch");
  assert.deepEqual(calls[0].service_data, { batch_id: "ready-batch" });
  assert.equal(calls.length, 2); // One action plus one local snapshot read.
});

test("only guarded refresh, prepare, and cancellation actions are allowed", async () => {
  assert.equal(panelActions.has("submit_batch_zinc"), false);
  assert.equal(panelActions.has("submit_zinc"), false);
  const view = panel(), calls = [];
  view._hass.callWS = async message => { calls.push(message); return message.type === "reorder/panel" ? makePanelData() : {}; };
  await view._action("submit_batch_zinc", "placed-batch");
  await view._action("refresh_batch_zinc", "uncertain-batch");
  assert.equal(calls.length, 0);
  await view._action("refresh_batch_zinc", "placed-batch");
  assert.equal(calls[0].service, "refresh_batch_zinc");
  assert.equal(calls.length, 2);
});

test("pending action disables duplicate requests and surfaces failure inline", async () => {
  const view = panel();
  let reject, count = 0;
  view._hass.callWS = () => { count++; return new Promise((resolve, fail) => { reject = fail; }); };
  const action = view._action("refresh_batch_zinc", "placed-batch");
  await view._action("refresh_batch_zinc", "placed-batch");
  assert.equal(count, 1);
  reject({ message: "Zinc returned HTTP 503" });
  await action;
  assert.match(view.shadowRoot.innerHTML, /Zinc returned HTTP 503/);
  assert.equal(view._busy, false);
  assert.equal(view._data.batches[1].status, "order_placed");
});

test("older snapshot responses cannot replace a newer result", async () => {
  const view = panel();
  const responses = [];
  view._hass.callWS = () => new Promise(resolve => responses.push(resolve));
  const first = view._load(), second = view._load();
  const newer = makePanelData(); newer.mode = "Live disabled";
  responses[1](newer); await second;
  responses[0](makePanelData()); await first;
  assert.equal(view._data.mode, "Live disabled");
});

test("prepare selects its returned batch without submitting a purchase", async () => {
  const view = panel(), calls = [];
  view._tab = "queue";
  const data = makePanelData();
  data.batches.unshift({ ...data.batches[0], id: "new-batch" });
  view._hass.callWS = async message => { calls.push(message); return message.type === "reorder/panel" ? data : { response: { id: "new-batch" } }; };
  await view._action("prepare_batch");
  assert.equal(view._selectedId, "new-batch");
  assert.equal(view._tab, "batches");
  assert.equal(calls[0].service, "prepare_batch");
  assert.deepEqual(calls[0].service_data, { max_items: 10 });
});


test("queue shows matching explanations and configured aliases without performing actions", () => {
  const view = panel();
  view._tab = "queue";
  view._data.intake_events = [{ name: "coffee", reason: "no_match", message: "No enabled catalog name or alias matches this item.", created_at: "2026-11-02T14:00:00Z" }];
  view._data.catalog = [{ name: "Morning coffee", aliases: ["coffee"], enabled: true, retailer: "zinc" }];
  view._render();
  assert.match(view.shadowRoot.innerHTML, /Shopping List activity/);
  assert.match(view.shadowRoot.innerHTML, /No catalog match/);
  assert.match(view.shadowRoot.innerHTML, /Aliases: coffee/);
  assert.match(view.shadowRoot.innerHTML, /built-in Shopping List/);
  view._data.shopping_list_ready = false;
  view._render();
  assert.match(view.shadowRoot.innerHTML, /built-in Shopping List is not loaded/);
});


test("product forms send validated-shape values without credentials or order mutations", () => {
  const view = panel(), calls = [];
  view._originalProduct = "Morning coffee";
  view._productDraft = { name: "Morning coffee", aliases: "coffee, morning brew", retailer: "zinc", product_id: "https://example.com/coffee", quantity: "2", max_price: "25", cooldown_hours: "24", enabled: true, substitute_1: "", substitute_2: "" };
  view._manage = (...args) => calls.push(args);
  view._submit({ preventDefault() {}, target: { dataset: { form: "product" } } });
  assert.equal(calls[0][0], "reorder/product_save");
  assert.equal(calls[0][1].original_name, "Morning coffee");
  assert.deepEqual(calls[0][1].product.aliases, ["coffee", "morning brew"]);
  assert.equal(calls[0][1].product.quantity, 2);
  assert.equal(calls[0][1].product.max_price, 25);
  assert.doesNotMatch(JSON.stringify(calls), /zinc_api_key|shipping_address|submit_batch/);
});

test("settings form sends schedule and synchronization preferences only", () => {
  const view = panel(), calls = [];
  view._preferencesDraft = { strategy: "weekly", weekday: "1", hour: "12", rolling_hours: "24", sync_shopping_list: false };
  view._manage = (...args) => calls.push(args);
  view._submit({ preventDefault() {}, target: { dataset: { form: "preferences" } } });
  assert.equal(calls[0][0], "reorder/preferences_save");
  assert.deepEqual(calls[0][1].preferences, { strategy: "weekly", weekday: 1, hour: 12, rolling_hours: 24, sync_shopping_list: false });
});

test("failed product saves preserve the draft and surface the validation message", async () => {
  const view = panel();
  view._tab = "products";
  view._productDraft = { name: "Tea", aliases: "coffee", retailer: "zinc", product_id: "https://example.com/tea", quantity: 1, max_price: 25, cooldown_hours: 24, enabled: true, substitute_1: "", substitute_2: "" };
  view._hass.callWS = async () => { throw { message: "Alias already belongs to Coffee" }; };
  await view._manage("reorder/product_save", { product: {} }, "Saved");
  assert.equal(view._productDraft.name, "Tea");
  assert.match(view.shadowRoot.innerHTML, /Alias already belongs to Coffee/);
  assert.equal(view._busy, false);
});

test("invalidated batches explain canceled and returned lines inline", () => {
  const view = panel();
  const batch = view._data.batches[0];
  batch.status = "invalidated";
  batch.status_label = "Needs fresh review";
  batch.can_cancel = false;
  batch.orders[0].status = "canceled";
  batch.orders[1].status = "returned_to_queue";
  view._selectedId = batch.id;
  const html = view._details();
  assert.match(html, /Needs fresh review/);
  assert.match(html, /Returned to queue for fresh review/);
  assert.match(html, /Canceled locally/);
  assert.match(html, /This batch cannot be submitted/);
});


test("saving one settings page preserves an unrelated unsaved form draft", async () => {
  const view = panel();
  view._productDraft = { name: "Unsaved product" };
  view._preferencesDraft = { strategy: "weekly" };
  view._hass.callWS = async message => message.type === "reorder/panel" ? makePanelData() : {};
  await view._manage("reorder/preferences_save", { preferences: {} }, "Saved");
  assert.equal(view._productDraft.name, "Unsaved product");
  assert.equal(view._preferencesDraft, null);
});


test("sandbox submission needs typed confirmation and uses only the restricted gateway", async () => {
  const view = panel(), calls = [];
  view._confirmSubmit = "ready-batch";
  view._hass.callWS = async message => { calls.push(message); return message.type === "reorder/panel" ? makePanelData() : {}; };
  await view._submitSandbox();
  assert.equal(calls.length, 0);
  view._sandboxPhrase = "SANDBOX";
  await view._submitSandbox();
  assert.equal(calls[0].type, "reorder/sandbox_submit");
  assert.equal(calls[0].confirmation, "SANDBOX");
  assert.equal(calls.some(call => call.type === "call_service"), false);
});

test("live mode never acquires sandbox submission capability from client confirmation", async () => {
  const view = panel();
  view._data.mode = "Live enabled";
  view._data.batches[0].can_submit_sandbox = false;
  view._confirmSubmit = "ready-batch";
  view._sandboxPhrase = "SANDBOX";
  view._hass.callWS = () => { throw new Error("must not send"); };
  await view._submitSandbox();
  assert.doesNotMatch(view._orderControls(view._data.batches[0]), /data-open-submit/);
});

test("receipt confirmation requires selected eligible IDs and never changes provider status", async () => {
  const view = panel(), calls = [];
  const batch = view._data.batches[1];
  batch.receivable_order_ids = [batch.orders[0].id];
  view._confirmReceipt = batch.id;
  view._receiptPhrase = "SIMULATE RECEIPT";
  view._hass.callWS = async message => { calls.push(message); return message.type === "reorder/panel" ? view._data : { results: [{ order_id: batch.orders[0].id, status: "completed" }] }; };
  await view._receiveItems();
  assert.equal(calls.length, 0);
  view._receiptOrderIds = [batch.orders[0].id];
  await view._receiveItems();
  assert.equal(calls[0].type, "reorder/receive_items");
  assert.deepEqual(calls[0].order_ids, [batch.orders[0].id]);
  assert.equal(batch.status, "order_placed");
});

test("tracking and partial failures are visible with escaped safe links and prices", () => {
  const view = panel();
  const html = view._fulfillment({ fulfillment: { outcome: "partial", error_code: "product_out_of_stock", prices_cents: { total: 1234 }, shipments: [{ carrier: "usps", tracking_number: "TEST<123>", status: "in_transit", url: "javascript:alert(1)", estimated_delivery_date: "2026-11-06" }] } });
  assert.match(html, /Partial fulfillment/);
  assert.match(html, /product_out_of_stock/);
  assert.match(html, /\$12\.34/);
  assert.match(html, /TEST&lt;123&gt;/);
  assert.doesNotMatch(html, /href="javascript:/);
});
