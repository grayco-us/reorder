/* Reorder's bundled sidebar app. No external libraries, keys, or purchase controls. */
export const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
export function productURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export const panelActions = new Set(["prepare_batch", "refresh_batch_zinc", "cancel_batch"]);

const css = `
:host{display:block;height:100%;overflow:auto;background:var(--primary-background-color,#f5f7fa);color:var(--primary-text-color,#172033);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
*{box-sizing:border-box}button,a{font:inherit}button{cursor:pointer}button:disabled{cursor:not-allowed;opacity:.5}button:focus-visible,a:focus-visible{outline:3px solid var(--primary-color,#3876be);outline-offset:3px}
header{display:flex;align-items:center;gap:14px;padding:18px 24px;background:var(--card-background-color,#fff);border-bottom:1px solid var(--divider-color,#e3e8ef)}header h1{font-size:22px;margin:0;letter-spacing:-.5px}.grow{flex:1}.menu{border:0;background:none;font-size:24px;padding:0 6px;color:inherit}.settings{color:var(--primary-color,#3876be);text-decoration:none;font-weight:600}
main{max-width:1440px;margin:auto;padding:26px}.top{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:22px}h2{margin:0;font-size:26px;letter-spacing:-.6px}p{color:var(--secondary-text-color,#69758a);line-height:1.5}.top p{margin:6px 0 0}.badge{display:inline-flex;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:650;background:var(--secondary-background-color,#eef2f7);white-space:nowrap}.sandbox{color:var(--success-color,#287951);border:1px solid currentColor}.live{color:var(--warning-color,#a65f00);border:1px solid currentColor}
.tabs,.filters,.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.tabs{border-bottom:1px solid var(--divider-color,#e3e8ef);margin-bottom:22px}.tab{border:0;border-bottom:3px solid transparent;border-radius:0;padding:12px 14px;background:none;color:var(--secondary-text-color,#69758a)}.tab.active{border-bottom-color:var(--primary-color,#3876be);color:var(--primary-color,#3876be);font-weight:700}.count{font-size:12px;margin-left:7px}.layout{display:grid;grid-template-columns:minmax(270px,340px) minmax(0,1fr);gap:22px;align-items:start}
.card{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#e3e8ef);border-radius:16px;overflow:hidden}.card-head{padding:20px;border-bottom:1px solid var(--divider-color,#e3e8ef)}h3{font-size:17px;margin:0 0 12px}.filters button,.secondary{border:1px solid var(--divider-color,#dbe2eb);background:var(--card-background-color,#fff);color:inherit;border-radius:9px;padding:9px 13px}.filters button{font-size:12px;padding:6px 10px}.filters .active{background:var(--primary-color,#3876be);border-color:var(--primary-color,#3876be);color:var(--text-primary-color,#fff)}.batch{display:block;width:100%;text-align:left;background:none;color:inherit;border:0;border-bottom:1px solid var(--divider-color,#e3e8ef);padding:17px 20px}.batch:last-child{border-bottom:0}.batch.selected{background:var(--secondary-background-color,#edf3fb);box-shadow:inset 3px 0 var(--primary-color,#3876be)}.batch strong{display:block;font-size:14px;margin-bottom:7px}.batch small{display:block;color:var(--secondary-text-color,#69758a);margin-top:8px;font-size:12px}.batch .row{display:flex;justify-content:space-between;align-items:center;gap:10px}.batch .price{font-size:13px;font-weight:650}.empty{padding:36px 24px;text-align:center}.empty h3{margin-bottom:8px}.empty p{margin:0}.details{padding:24px}.detail-top{display:flex;justify-content:space-between;align-items:start;gap:14px;margin-bottom:16px}.eyebrow{font-size:12px;color:var(--secondary-text-color,#69758a);margin:0 0 7px}.details h3{font-size:24px;letter-spacing:-.5px;margin:0}.meta{display:flex;gap:8px 22px;flex-wrap:wrap;font-size:12px;color:var(--secondary-text-color,#69758a);margin:14px 0 20px}.actions{margin-bottom:22px}.primary{border:0;border-radius:9px;padding:11px 16px;background:var(--primary-color,#3876be);color:var(--text-primary-color,#fff);font-weight:650}.danger{color:var(--error-color,#b43d3d)}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--secondary-text-color,#69758a);font-weight:650}th,td{padding:14px 10px;border-bottom:1px solid var(--divider-color,#e3e8ef)}th:first-child,td:first-child{padding-left:0}th:last-child,td:last-child{text-align:right;padding-right:0}.quantity{text-align:center;width:75px}td a{color:var(--primary-text-color,#172033);text-decoration:none;font-weight:600}td a:hover{text-decoration:underline}svg.external{width:12px;height:12px;margin-left:6px;vertical-align:-1px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linejoin:round}td small{display:block;margin-top:5px;color:var(--secondary-text-color,#69758a);font-size:11px}.total{display:flex;justify-content:space-between;align-items:center;margin-top:20px;font-size:14px}.total strong{font-size:24px;letter-spacing:-.5px}.hint{font-size:12px;margin:8px 0 0}.notice{padding:13px 16px;border-radius:10px;margin-bottom:18px;border:1px solid var(--divider-color,#dbe2eb);font-size:14px;line-height:1.5}.error{border-color:var(--error-color,#b43d3d);color:var(--error-color,#b43d3d)}.confirm{border-color:var(--warning-color,#a65f00);margin:16px 0}.confirm p{margin:6px 0 12px}.confirm .actions{margin:0}.queue{padding:24px}.queue .actions{margin:20px 0 0}.footer{font-size:12px;color:var(--secondary-text-color,#69758a);margin-top:20px}.loading{padding:50px;text-align:center}
@media(max-width:760px){header{padding:14px 16px;gap:10px}header h1{font-size:20px}main{padding:18px 12px}.layout{grid-template-columns:1fr;gap:16px}.top{align-items:start}.top h2{font-size:23px}.details,.queue{padding:18px}.batch-list{max-height:290px;overflow:auto}.settings{font-size:13px}.meta{gap:7px 14px}}
`;

export class ReorderPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._selectedId = null;
    this._tab = "batches";
    this._filter = "all";
    this._busy = false;
    this._error = "";
    this._notice = "";
    this._confirmCancel = null;
    this._generation = 0;
    this._loadSequence = 0;
    this.shadowRoot.addEventListener("click", event => this._click(event));
  }
  set hass(value) { this._hass = value; this._start(); }
  get hass() { return this._hass; }
  set panel(value) { this._panel = value; this._start(); }
  get panel() { return this._panel; }
  connectedCallback() { this._start(); this._render(); }
  disconnectedCallback() { this._stop(); }
  _stop() {
    this._generation++;
    this._unsubscribe?.();
    this._unsubscribe = null;
    this._connection = null;
  }
  _start() {
    const entryId = this._panel?.config?.entry_id;
    if (!this.isConnected || !entryId || !this._hass?.connection) return;
    if (this._connection === this._hass.connection && this._entryId === entryId) return;
    this._stop();
    this._connection = this._hass.connection;
    this._entryId = entryId;
    const generation = this._generation;
    this._load();
    this._connection.subscribeEvents(() => this._load(), "reorder_updated").then(unsubscribe => {
      if (generation === this._generation && this.isConnected) this._unsubscribe = unsubscribe;
      else unsubscribe();
    }).catch(() => { /* Manual reload remains available if subscription fails. */ });
  }
  async _load() {
    if (!this._hass || !this._entryId) return;
    const generation = this._generation;
    const sequence = ++this._loadSequence;
    try {
      const data = await this._hass.callWS({ type: "reorder/panel", entry_id: this._entryId });
      if (generation !== this._generation || sequence !== this._loadSequence) return;
      this._data = data;
      if (this._selectedId && !data.batches.some(batch => batch.id === this._selectedId)) {
        this._selectedId = null;
        this._confirmCancel = null;
      }
    } catch (error) {
      if (generation !== this._generation || sequence !== this._loadSequence) return;
      this._error = error.message || "Unable to load Reorder. Check that the integration is running.";
    }
    this._render();
  }
  _money(value) {
    return new Intl.NumberFormat(this._hass?.language || "en", { style: "currency", currency: "USD" }).format(Number(value));
  }
  _date(value) {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime())) return "Not available";
    return new Intl.DateTimeFormat(this._hass?.language || "en", {
      dateStyle: "medium", timeStyle: "short", timeZone: this._hass?.config?.time_zone || "UTC",
    }).format(date);
  }
  _mode(mode) {
    const label = mode === "sandbox" ? "Sandbox" : mode === "live" ? "Live" : mode === "local" ? "Local" : mode;
    return `<span class="badge ${mode === "Sandbox" || mode === "sandbox" ? "sandbox" : mode === "Live enabled" || mode === "live" ? "live" : ""}">${escapeHTML(label)}</span>`;
  }
  _products(orders) {
    return `<div class="table-scroll"><table><thead><tr><th>Product</th><th class="quantity">Qty</th><th>Price ceiling</th></tr></thead><tbody>${orders.map(order => {
      const url = productURL(order.product_id);
      const name = url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(order.name)}<svg class="external" aria-hidden="true" viewBox="0 0 24 24"><path d="M14 3h7v7M10 14 21 3M21 14v7H3V3h7"/></svg></a>` : escapeHTML(order.name);
      return `<tr><td>${name}</td><td class="quantity">${escapeHTML(order.quantity)}</td><td>${this._money(order.max_price)}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  }
  _batchList() {
    const all = this._data.batches;
    const batches = all.filter(batch => this._filter === "all" || (this._filter === "ready" ? batch.status === "ready" : batch.status !== "ready"));
    return `<aside class="card"><div class="card-head"><h3>Your batches</h3><div class="filters">${[["all", "All"], ["ready", "Ready"], ["history", "History"]].map(([key, name]) => `<button class="${key === this._filter ? "active" : ""}" data-filter="${key}" aria-pressed="${key === this._filter}">${name}</button>`).join("")}</div></div><div class="batch-list">${batches.length ? batches.map(batch => `<button class="batch ${batch.id === this._selectedId ? "selected" : ""}" data-batch="${escapeHTML(batch.id)}" aria-pressed="${batch.id === this._selectedId}"><strong>${escapeHTML(batch.status_label)}</strong><div class="row">${this._mode(batch.zinc_environment || "local")}<span class="price">${this._money(batch.max_price)}</span></div><small>${escapeHTML(batch.id)} · ${escapeHTML(this._date(batch.created_at))}</small></button>`).join("") : '<div class="empty"><h3>No batches here yet</h3><p>Prepare queued products to review them before ordering.</p></div>'}</div></aside>`;
  }
  _details() {
    const batch = this._data.batches.find(item => item.id === this._selectedId);
    if (!batch) return '<section class="card empty"><h3>Choose a batch to review</h3><p>See saved products, quantities, spending limits, and status here.</p></section>';
    const confirmation = this._confirmCancel === batch.id ? `<div class="notice confirm" role="alert"><strong>Cancel this batch and its ${batch.orders.length} queued product line(s)?</strong><p>They stay in history and will not be queued again automatically. This does not cancel a retailer purchase.</p><div class="actions"><button class="secondary" data-keep>Keep batch</button><button class="primary" data-action="cancel_batch" data-id="${escapeHTML(batch.id)}" ${this._busy ? "disabled" : ""}>Confirm local cancellation</button></div></div>` : "";
    return `<section class="card details"><div class="detail-top"><div><p class="eyebrow">Batch ${escapeHTML(batch.id)}</p><h3>${escapeHTML(batch.status_label)}</h3></div>${this._mode(batch.zinc_environment || "Not submitted")}</div><div class="meta"><span>Created ${escapeHTML(this._date(batch.created_at))}</span>${batch.last_refreshed_at ? `<span>Updated ${escapeHTML(this._date(batch.last_refreshed_at))}</span>` : ""}${batch.canceled_at ? `<span>Canceled ${escapeHTML(this._date(batch.canceled_at))}</span>` : ""}</div><div class="actions"><button class="secondary" data-action="refresh_batch_zinc" data-id="${escapeHTML(batch.id)}" ${!batch.can_refresh || this._busy ? "disabled" : ""}>Refresh status</button><button class="secondary danger" data-cancel="${escapeHTML(batch.id)}" ${!batch.can_cancel || this._busy ? "disabled" : ""}>Cancel locally</button></div>${confirmation}${batch.review_error ? `<div class="notice error">${escapeHTML(batch.review_error)}</div>` : this._products(batch.orders)}<div class="total"><span>Total price ceiling</span><strong>${this._money(batch.max_price)}</strong></div><p class="hint">Spending limits, not a price quote. These are the products saved with this batch.</p>${batch.status === "submission_unknown" ? '<div class="notice error">The submission outcome is uncertain. Reconcile this order with Zinc before taking further action.</div>' : ""}${batch.zinc_order_id ? `<p class="hint">Zinc order ${escapeHTML(batch.zinc_order_id)}</p>` : ""}</section>`;
  }
  _queue() {
    const queue = this._data.queue;
    return `<section class="card queue"><h3>Next batch</h3><p>Up to 10 eligible Zinc product lines. Preparing a batch saves it locally without making a purchase.</p>${queue.count ? this._products(queue.orders) : '<div class="empty"><h3>Your queue is clear</h3><p>Add an enabled Zinc product’s exact name or alias to your Home Assistant Shopping List.</p></div>'}<div class="total"><span>Combined price ceiling</span><strong>${this._money(queue.price_ceiling)}</strong></div><div class="actions"><button class="primary" data-action="prepare_batch" ${!queue.count || this._busy ? "disabled" : ""}>Prepare batch for review</button></div></section>`;
  }
  _render() {
    const data = this._data;
    this.shadowRoot.innerHTML = `<style>${css}</style><header><button class="menu" data-menu aria-label="Open Home Assistant menu">☰</button><h1>Reorder</h1><span class="grow"></span>${data ? this._mode(data.mode) : ""}<a class="settings" href="/config/integrations/integration/reorder">Settings</a></header><main><div class="top"><div><h2>Batches & orders</h2><p>Review your batches and track order progress.</p></div><button class="secondary" data-reload ${this._busy ? "disabled" : ""}>Reload</button></div>${this._error ? `<div class="notice error" role="alert">${escapeHTML(this._error)}</div>` : ""}${this._notice ? `<div class="notice" role="status">${escapeHTML(this._notice)}</div>` : ""}${data ? `<nav class="tabs" aria-label="Reorder sections"><button class="tab ${this._tab === "batches" ? "active" : ""}" data-tab="batches">Batches<span class="count">${data.batches.length}</span></button><button class="tab ${this._tab === "queue" ? "active" : ""}" data-tab="queue">Queue<span class="count">${data.queue.count}</span></button></nav>${this._tab === "queue" ? this._queue() : `<div class="layout">${this._batchList()}${this._details()}</div>`}<p class="footer">${data.batches.filter(batch => batch.status === "ready").length} ready for review · ${data.product_count} enabled catalog product(s) · No purchases can be submitted from this app.</p>` : '<div class="card loading" role="status">Loading Reorder…</div>'}</main>`;
  }
  _click(event) {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    const data = button.dataset;
    if ("menu" in data) {
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
      return;
    }
    if ("reload" in data) { this._error = ""; this._load(); return; }
    if (data.tab) { this._tab = data.tab; this._confirmCancel = null; }
    if (data.filter) { this._filter = data.filter; }
    if (data.batch) { this._selectedId = data.batch; this._confirmCancel = null; }
    if (data.cancel) { this._confirmCancel = data.cancel; }
    if ("keep" in data) { this._confirmCancel = null; }
    if (data.action) { this._action(data.action, data.id); return; }
    this._render();
  }
  async _action(action, batchId) {
    if (this._busy || !panelActions.has(action)) return;
    const batch = this._data?.batches.find(item => item.id === batchId);
    if (action === "cancel_batch" && (!batch?.can_cancel || this._confirmCancel !== batchId)) return;
    if (action === "refresh_batch_zinc" && !batch?.can_refresh) return;
    if (action === "prepare_batch" && !this._data?.queue.count) return;
    this._busy = true;
    this._error = "";
    this._notice = "";
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "call_service", domain: "reorder", service: action,
        service_data: action === "prepare_batch" ? { max_items: 10 } : { batch_id: batchId },
        return_response: true,
      });
      if (action === "prepare_batch") {
        this._selectedId = result?.response?.id || this._selectedId;
        this._tab = "batches";
        this._filter = "all";
        this._notice = "Batch prepared locally. No purchase was made.";
      } else {
        this._notice = action === "cancel_batch" ? "Batch and queued product lines canceled locally." : "Status refreshed from Zinc.";
      }
      this._confirmCancel = null;
      await this._load();
    } catch (error) {
      this._error = error.message || "The action failed. Check the saved batch status before trying again.";
    } finally {
      this._busy = false;
      this._render();
    }
  }
}
if (!customElements.get("reorder-panel")) customElements.define("reorder-panel", ReorderPanel);
