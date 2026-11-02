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
.tabs,.filters,.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.tabs{overflow-x:auto;flex-wrap:nowrap;border-bottom:1px solid var(--divider-color,#e3e8ef);margin-bottom:22px}.tab{white-space:nowrap;border:0;border-bottom:3px solid transparent;border-radius:0;padding:12px 14px;background:none;color:var(--secondary-text-color,#69758a)}.tab.active{border-bottom-color:var(--primary-color,#3876be);color:var(--primary-color,#3876be);font-weight:700}.count{font-size:12px;margin-left:7px}.layout{display:grid;grid-template-columns:minmax(270px,340px) minmax(0,1fr);gap:22px;align-items:start}
.card{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#e3e8ef);border-radius:16px;overflow:hidden}.card-head{padding:20px;border-bottom:1px solid var(--divider-color,#e3e8ef)}h3{font-size:17px;margin:0 0 12px}.filters button,.secondary{border:1px solid var(--divider-color,#dbe2eb);background:var(--card-background-color,#fff);color:inherit;border-radius:9px;padding:9px 13px}.filters button{font-size:12px;padding:6px 10px}.filters .active{background:var(--primary-color,#3876be);border-color:var(--primary-color,#3876be);color:var(--text-primary-color,#fff)}.batch{display:block;width:100%;text-align:left;background:none;color:inherit;border:0;border-bottom:1px solid var(--divider-color,#e3e8ef);padding:17px 20px}.batch:last-child{border-bottom:0}.batch.selected{background:var(--secondary-background-color,#edf3fb);box-shadow:inset 3px 0 var(--primary-color,#3876be)}.batch strong{display:block;font-size:14px;margin-bottom:7px}.batch small{display:block;color:var(--secondary-text-color,#69758a);margin-top:8px;font-size:12px}.batch .row{display:flex;justify-content:space-between;align-items:center;gap:10px}.batch .price{font-size:13px;font-weight:650}.empty{padding:36px 24px;text-align:center}.empty h3{margin-bottom:8px}.empty p{margin:0}.details{padding:24px}.detail-top{display:flex;justify-content:space-between;align-items:start;gap:14px;margin-bottom:16px}.eyebrow{font-size:12px;color:var(--secondary-text-color,#69758a);margin:0 0 7px}.details h3{font-size:24px;letter-spacing:-.5px;margin:0}.meta{display:flex;gap:8px 22px;flex-wrap:wrap;font-size:12px;color:var(--secondary-text-color,#69758a);margin:14px 0 20px}.actions{margin-bottom:22px}.primary{border:0;border-radius:9px;padding:11px 16px;background:var(--primary-color,#3876be);color:var(--text-primary-color,#fff);font-weight:650}.danger{color:var(--error-color,#b43d3d)}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--secondary-text-color,#69758a);font-weight:650}th,td{padding:14px 10px;border-bottom:1px solid var(--divider-color,#e3e8ef)}th:first-child,td:first-child{padding-left:0}th:last-child,td:last-child{text-align:right;padding-right:0}.quantity{text-align:center;width:75px}td a{color:var(--primary-text-color,#172033);text-decoration:none;font-weight:600}td a:hover{text-decoration:underline}svg.external{width:12px;height:12px;margin-left:6px;vertical-align:-1px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linejoin:round}td small{display:block;margin-top:5px;color:var(--secondary-text-color,#69758a);font-size:11px}.total{display:flex;justify-content:space-between;align-items:center;margin-top:20px;font-size:14px}.total strong{font-size:24px;letter-spacing:-.5px}.hint{font-size:12px;margin:8px 0 0}.notice{padding:13px 16px;border-radius:10px;margin-bottom:18px;border:1px solid var(--divider-color,#dbe2eb);font-size:14px;line-height:1.5}.error{border-color:var(--error-color,#b43d3d);color:var(--error-color,#b43d3d)}.confirm{border-color:var(--warning-color,#a65f00);margin:16px 0}.confirm p{margin:6px 0 12px}.confirm .actions{margin:0}.queue{padding:24px}.queue .actions{margin:20px 0 0}.footer{font-size:12px;color:var(--secondary-text-color,#69758a);margin-top:20px}.loading{padding:50px;text-align:center}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.form-grid label{display:flex;flex-direction:column;gap:7px;font-size:13px;font-weight:600}.form-grid input,.form-grid select{width:100%;padding:10px;border:1px solid var(--divider-color,#dbe2eb);border-radius:8px;background:var(--card-background-color,#fff);color:inherit;font:inherit}.form-grid input:disabled{opacity:.65}.form-grid .wide{grid-column:1/-1}.form-grid .check{flex-direction:row;align-items:center;font-weight:400}.form-grid .check input{width:auto}.product-row{padding:18px 0;border-bottom:1px solid var(--divider-color,#e3e8ef)}.product-row:last-child{border:0}.product-row h3{margin-bottom:6px}.product-row .actions{margin:12px 0 0}.editor{margin-top:22px;padding-top:22px;border-top:1px solid var(--divider-color,#e3e8ef)}
@media(max-width:760px){header{padding:14px 16px;gap:10px}header h1{font-size:20px}main{padding:18px 12px}.layout{grid-template-columns:1fr;gap:16px}.top{align-items:start}.top h2{font-size:23px}.details,.queue{padding:18px}.batch-list{max-height:290px;overflow:auto}.settings{font-size:13px}.meta{gap:7px 14px}.form-grid{grid-template-columns:1fr}.tab{padding:10px}}
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
    this._productDraft = null;
    this._originalProduct = null;
    this._removeProductName = null;
    this._preferencesDraft = null;
    this._generation = 0;
    this._loadSequence = 0;
    this.shadowRoot.addEventListener("click", event => this._click(event));
    this.shadowRoot.addEventListener("input", event => this._input(event));
    this.shadowRoot.addEventListener("change", event => this._input(event));
    this.shadowRoot.addEventListener("submit", event => this._submit(event));
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
      const outcome = order.status === "returned_to_queue" ? "Returned to queue for fresh review" : order.status === "canceled" ? "Canceled locally" : "";
      return `<tr><td>${name}${outcome ? `<small>${outcome}</small>` : ""}</td><td class="quantity">${escapeHTML(order.quantity)}</td><td>${this._money(order.max_price)}</td></tr>`;
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
    return `<section class="card details"><div class="detail-top"><div><p class="eyebrow">Batch ${escapeHTML(batch.id)}</p><h3>${escapeHTML(batch.status_label)}</h3></div>${this._mode(batch.zinc_environment || "Not submitted")}</div><div class="meta"><span>Created ${escapeHTML(this._date(batch.created_at))}</span>${batch.last_refreshed_at ? `<span>Updated ${escapeHTML(this._date(batch.last_refreshed_at))}</span>` : ""}${batch.canceled_at ? `<span>Canceled ${escapeHTML(this._date(batch.canceled_at))}</span>` : ""}${batch.invalidated_at ? `<span>Invalidated ${escapeHTML(this._date(batch.invalidated_at))}</span>` : ""}</div><div class="actions"><button class="secondary" data-action="refresh_batch_zinc" data-id="${escapeHTML(batch.id)}" ${!batch.can_refresh || this._busy ? "disabled" : ""}>Refresh status</button><button class="secondary danger" data-cancel="${escapeHTML(batch.id)}" ${!batch.can_cancel || this._busy ? "disabled" : ""}>Cancel locally</button></div>${confirmation}${batch.status === "invalidated" ? '<div class="notice">The Shopping List changed. This batch cannot be submitted; unaffected lines returned to the queue. Prepare a new batch for review.</div>' : ""}${batch.review_error ? `<div class="notice error">${escapeHTML(batch.review_error)}</div>` : this._products(batch.orders)}<div class="total"><span>Total price ceiling</span><strong>${this._money(batch.max_price)}</strong></div><p class="hint">Spending limits, not a price quote. These are the products saved with this batch.</p>${batch.status === "submission_unknown" ? '<div class="notice error">The submission outcome is uncertain. Reconcile this order with Zinc before taking further action.</div>' : ""}${batch.zinc_order_id ? `<p class="hint">Zinc order ${escapeHTML(batch.zinc_order_id)}</p>` : ""}</section>`;
  }
  _intake() {
    const labels = { queued: "Queued", no_match: "No catalog match", disabled: "Product disabled", ambiguous: "Ambiguous match", existing_order: "Existing order", cooldown: "Cooldown", already_seen: "Already processed", ignored: "Ignored", invalid_item: "Invalid item", storage_error: "Save failed", list_change: "List synchronized", submitted_unchanged: "Submitted order unchanged", sync_blocked: "Needs review", unchanged: "Same product", sync_disabled: "Manual synchronization", sync_unavailable: "List unavailable" };
    const events = this._data.intake_events || [];
    const catalog = this._data.catalog || [];
    return `<div style="margin-top:32px"><h3>Shopping List activity</h3>${this._data.shopping_list_ready === false ? '<div class="notice error">Home Assistant’s built-in Shopping List is not loaded. Add or repair that integration in Settings; other to-do lists do not send its events.</div>' : ""}<p class="hint">Most recent 20 additions received since Reorder last started. Only Home Assistant's built-in Shopping List is monitored.</p>${events.length ? events.map(event => `<div class="notice"><strong>${escapeHTML(event.name)}</strong> · ${escapeHTML(labels[event.reason] || event.reason)}<p style="margin:6px 0">${escapeHTML(event.message)}</p><span class="hint">${escapeHTML(this._date(event.created_at))}</span></div>`).join("") : '<p>No additions received since restart. Add a fresh item to the built-in Shopping List to test matching.</p>'}<details style="margin-top:20px"><summary>Configured product names and aliases</summary>${catalog.length ? catalog.map(product => `<p><strong>${escapeHTML(product.name)}</strong> · ${product.enabled ? "Enabled" : "Disabled"} · ${escapeHTML(product.retailer)}<br><span class="hint">Aliases: ${escapeHTML(product.aliases.join(", ") || "None")}</span></p>`).join("") : '<p>No catalog products configured. Add a product in Reorder settings first.</p>'}</details></div>`;
  }
  _queue() {
    const queue = this._data.queue;
    return `<section class="card queue"><h3>Next batch</h3><p>Up to 10 eligible Zinc product lines. Preparing a batch saves it locally without making a purchase.</p>${queue.count ? this._products(queue.orders) : '<div class="empty"><h3>Your queue is clear</h3><p>Add an enabled Zinc product’s exact name or alias to your Home Assistant Shopping List.</p></div>'}<div class="total"><span>Combined price ceiling</span><strong>${this._money(queue.price_ceiling)}</strong></div><div class="actions"><button class="primary" data-action="prepare_batch" ${!queue.count || this._busy ? "disabled" : ""}>Prepare batch for review</button></div>${this._intake()}</section>`;
  }
  _field(label, name, value, options = {}) {
    return `<label class="${options.wide ? "wide" : ""}">${escapeHTML(label)}<input name="${name}" type="${options.type || "text"}" value="${escapeHTML(value)}" ${options.required ? "required" : ""} ${options.disabled ? "disabled" : ""} ${options.min !== undefined ? `min="${options.min}"` : ""} ${options.max !== undefined ? `max="${options.max}"` : ""} ${options.step ? `step="${options.step}"` : ""}></label>`;
  }
  _productsPage() {
    const catalog = this._data.catalog || [];
    const draft = this._productDraft;
    const form = draft ? `<form class="editor" data-form="product"><h3>${this._originalProduct ? "Edit product" : "New product"}</h3><div class="form-grid">${this._field("Product name", "name", draft.name, { required: true, wide: true, disabled: draft.can_rename === false })}${this._field("Aliases (comma separated)", "aliases", draft.aliases, { wide: true })}<label>Provider<select name="retailer">${["zinc", "other", "kroger"].map(value => `<option value="${value}" ${draft.retailer === value ? "selected" : ""}>${value === "zinc" ? "Zinc" : value === "other" ? "Other — catalog only" : "Kroger — planned"}</option>`).join("")}</select></label>${this._field("Quantity", "quantity", draft.quantity, { type: "number", min: 1, max: 20, required: true })}${this._field("Product URL / identifier", "product_id", draft.product_id, { wide: true, required: true })}${this._field("Total price ceiling (USD)", "max_price", draft.max_price, { type: "number", min: 0.01, max: 10000, step: "0.01", required: true })}${this._field("Cooldown (hours)", "cooldown_hours", draft.cooldown_hours, { type: "number", min: 1, max: 8760, required: true })}${this._field("First substitution URL", "substitute_1", draft.substitute_1, { wide: true })}${this._field("Second substitution URL", "substitute_2", draft.substitute_2, { wide: true })}<label class="check wide"><input name="enabled" type="checkbox" ${draft.enabled ? "checked" : ""}>Enabled for new Shopping List matches</label></div><p class="hint">Zinc requires HTTPS product URLs. Price ceiling covers the configured quantity, tax, and shipping. Product changes affect future orders; existing snapshots stay unchanged.${draft.can_rename === false ? " This name has order history; use aliases to change how items match." : ""}</p><div class="actions"><button class="primary" type="submit" ${this._busy ? "disabled" : ""}>Save product</button><button class="secondary" type="button" data-close-product ${this._busy ? "disabled" : ""}>Discard changes</button></div></form>` : "";
    return `<section class="card queue"><div class="detail-top"><div><h3>Products</h3><p class="hint">Approved products and exact Shopping List names or aliases.</p></div><button class="primary" data-new-product ${this._busy ? "disabled" : ""}>Add product</button></div>${form}${catalog.map(product => `<div class="product-row"><h3>${escapeHTML(product.name)}</h3><p class="hint">${product.enabled ? "Enabled" : "Disabled"} · ${escapeHTML(product.retailer)} · Quantity ${escapeHTML(product.quantity)} · Ceiling ${this._money(product.max_price)}<br>Aliases: ${escapeHTML(product.aliases.join(", ") || "None")}</p><div class="actions"><button class="secondary" data-edit-product="${escapeHTML(product.name)}" ${this._busy ? "disabled" : ""}>Edit</button><button class="secondary" data-toggle-product="${escapeHTML(product.name)}" ${this._busy ? "disabled" : ""}>${product.enabled ? "Disable" : "Enable"}</button><button class="secondary danger" data-remove-product="${escapeHTML(product.name)}" ${this._busy ? "disabled" : ""}>Remove</button></div>${this._removeProductName === product.name ? `<div class="notice confirm"><strong>Remove ${escapeHTML(product.name)} from the catalog?</strong><p>Future matching stops. Existing queued, prepared, and submitted orders remain unchanged.</p><button class="secondary" data-keep-product>Keep product</button> <button class="primary" data-confirm-remove="${escapeHTML(product.name)}" ${this._busy ? "disabled" : ""}>Confirm removal</button></div>` : ""}</div>`).join("") || '<p>No products yet. Add one to start matching your Shopping List.</p>'}</section>`;
  }
  _settingsPage() {
    const settings = this._preferencesDraft || { strategy: "manual", weekday: 6, hour: 10, rolling_hours: 48, sync_shopping_list: true, ...this._data.preferences };
    return `<section class="card queue"><h3>Preferences</h3><form data-form="preferences"><div class="form-grid"><label>Batch preparation<select name="strategy">${[["manual", "Manual"], ["weekly", "Weekly"], ["rolling", "Rolling window"]].map(([key, name]) => `<option value="${key}" ${settings.strategy === key ? "selected" : ""}>${name}</option>`).join("")}</select></label><label>Day of week<select name="weekday">${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, index) => `<option value="${index}" ${Number(settings.weekday) === index ? "selected" : ""}>${day}</option>`).join("")}</select></label>${this._field("Hour (0–23, Home Assistant local time)", "hour", settings.hour, { type: "number", min: 0, max: 23, required: true })}${this._field("Rolling window (hours)", "rolling_hours", settings.rolling_hours, { type: "number", min: 1, max: 336, required: true })}<label class="check wide"><input name="sync_shopping_list" type="checkbox" ${settings.sync_shopping_list ? "checked" : ""}>Synchronize renames, completed items, and removals with unsubmitted orders</label></div><p class="hint">Checking off or removing an item cancels its unsubmitted order. A prepared batch containing it is invalidated; other lines return to the queue for fresh review. Submitted purchases are never changed. Unchecking can queue the item again unless it was manually canceled.</p><p class="hint">Schedules only prepare local batches. Day/hour apply to Weekly; rolling hours apply to Rolling window. No schedule submits a purchase.</p><button class="primary" type="submit" ${this._busy ? "disabled" : ""}>Save preferences</button></form><div class="editor"><h3>Zinc connection and delivery</h3><p>API keys, shipping details, and live purchasing controls remain in Home Assistant’s native integration configuration.</p><a class="settings" href="/config/integrations/integration/reorder">Open Zinc configuration</a></div></section>`;
  }
  _input(event) {
    const field = event.target;
    const form = field.closest("form");
    if (!form || !field.name) return;
    const value = field.type === "checkbox" ? field.checked : field.value;
    if (form.dataset.form === "product" && this._productDraft) this._productDraft[field.name] = value;
    if (form.dataset.form === "preferences") {
      this._preferencesDraft ||= { strategy: "manual", weekday: 6, hour: 10, rolling_hours: 48, sync_shopping_list: true, ...this._data.preferences };
      this._preferencesDraft[field.name] = value;
    }
  }
  _submit(event) {
    event.preventDefault();
    if (this._busy) return;
    if (event.target.dataset.form === "product") {
      const draft = this._productDraft;
      this._manage("reorder/product_save", { product: {
        name: draft.name, aliases: draft.aliases.split(",").map(alias => alias.trim()).filter(Boolean),
        retailer: draft.retailer, product_id: draft.product_id, quantity: Number(draft.quantity),
        max_price: Number(draft.max_price), cooldown_hours: Number(draft.cooldown_hours), enabled: draft.enabled,
        substitutes: [draft.substitute_1, draft.substitute_2].map(url => url.trim()).filter(Boolean),
      }, ...(this._originalProduct ? { original_name: this._originalProduct } : {}) }, "Product saved. Existing orders were not changed.");
    } else {
      const settings = this._preferencesDraft || { strategy: "manual", weekday: 6, hour: 10, rolling_hours: 48, sync_shopping_list: true, ...this._data.preferences };
      this._manage("reorder/preferences_save", { preferences: {
        strategy: settings.strategy, weekday: Number(settings.weekday), hour: Number(settings.hour),
        rolling_hours: Number(settings.rolling_hours), sync_shopping_list: settings.sync_shopping_list,
      } }, "Preferences saved. No purchase was made.");
    }
  }
  async _manage(type, data, notice) {
    if (this._busy || !["reorder/product_save", "reorder/product_remove", "reorder/preferences_save"].includes(type)) return;
    this._busy = true;
    this._error = "";
    this._notice = "";
    this._render();
    try {
      await this._hass.callWS({ type, entry_id: this._entryId, ...data });
      if (type === "reorder/preferences_save") this._preferencesDraft = null;
      else { this._productDraft = null; this._originalProduct = null; }
      this._removeProductName = null;
      this._notice = notice;
      await this._load();
    } catch (error) { this._error = error.message || "Settings could not be saved. Existing configuration was kept."; }
    finally { this._busy = false; this._render(); }
  }
  _render() {
    const data = this._data;
    this.shadowRoot.innerHTML = `<style>${css}</style><header><button class="menu" data-menu aria-label="Open Home Assistant menu">☰</button><h1>Reorder</h1><span class="grow"></span>${data ? this._mode(data.mode) : ""}<a class="settings" href="/config/integrations/integration/reorder">Connection</a></header><main><div class="top"><div><h2>Batches & orders</h2><p>Review your batches and track order progress.</p></div><button class="secondary" data-reload ${this._busy ? "disabled" : ""}>Reload</button></div>${this._error ? `<div class="notice error" role="alert">${escapeHTML(this._error)}</div>` : ""}${this._notice ? `<div class="notice" role="status">${escapeHTML(this._notice)}</div>` : ""}${data ? `<nav class="tabs" aria-label="Reorder sections"><button class="tab ${this._tab === "batches" ? "active" : ""}" data-tab="batches">Batches<span class="count">${data.batches.length}</span></button><button class="tab ${this._tab === "queue" ? "active" : ""}" data-tab="queue">Queue<span class="count">${data.queue.count}</span></button><button class="tab ${this._tab === "products" ? "active" : ""}" data-tab="products">Products</button><button class="tab ${this._tab === "settings" ? "active" : ""}" data-tab="settings">Settings</button></nav>${this._tab === "queue" ? this._queue() : this._tab === "products" ? this._productsPage() : this._tab === "settings" ? this._settingsPage() : `<div class="layout">${this._batchList()}${this._details()}</div>`}<p class="footer">${data.batches.filter(batch => batch.status === "ready").length} ready for review · ${data.product_count} enabled catalog product(s) · No purchases can be submitted from this app.</p>` : '<div class="card loading" role="status">Loading Reorder…</div>'}</main>`;
  }
  _click(event) {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (button.type === "submit" && button.closest("form")) return;
    const data = button.dataset;
    if ("menu" in data) {
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
      return;
    }
    if ("reload" in data) { this._error = ""; this._load(); return; }
    if (data.tab) { this._tab = data.tab; this._confirmCancel = null; this._removeProductName = null; this._error = ""; this._notice = ""; }
    if ("newProduct" in data) {
      this._originalProduct = null;
      this._productDraft = { name: "", aliases: "", retailer: "zinc", product_id: "", quantity: 1, max_price: 50, cooldown_hours: 168, enabled: true, substitute_1: "", substitute_2: "", can_rename: true };
    }
    if (data.editProduct) {
      const product = this._data.catalog.find(item => item.name === data.editProduct);
      this._originalProduct = product.name;
      this._productDraft = { ...product, aliases: product.aliases.join(", "), substitute_1: product.substitutes?.[0] || "", substitute_2: product.substitutes?.[1] || "" };
    }
    if ("closeProduct" in data) { this._productDraft = null; this._originalProduct = null; }
    if (data.toggleProduct) {
      const product = this._data.catalog.find(item => item.name === data.toggleProduct);
      const { can_rename, ...values } = product;
      this._manage("reorder/product_save", { product: { ...values, enabled: !product.enabled }, original_name: product.name }, "Product matching updated. Existing orders were not changed.");
      return;
    }
    if (data.removeProduct) this._removeProductName = data.removeProduct;
    if ("keepProduct" in data) this._removeProductName = null;
    if (data.confirmRemove && this._removeProductName === data.confirmRemove) {
      this._manage("reorder/product_remove", { name: data.confirmRemove }, "Product removed. Existing orders were not changed.");
      return;
    }
    if (data.filter) { this._filter = data.filter; }
    if (data.batch) { this._selectedId = data.batch; this._confirmCancel = null; }
    if (data.cancel) { this._confirmCancel = data.cancel; }
    if ("keep" in data) { this._confirmCancel = null; }
    if (data.action) { this._action(data.action, data.id); return; }
    this._render();
    if ("newProduct" in data || data.editProduct) this.shadowRoot.querySelector('form[data-form="product"] input:not(:disabled)')?.focus();
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
