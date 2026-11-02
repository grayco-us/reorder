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
