"use strict";

// ---- state ----
let token = localStorage.getItem("gemini_token");
let user = JSON.parse(localStorage.getItem("gemini_user") || "null");

// View definitions: nav label + the permission module that gates it.
// Dashboard has no module (any authenticated user sees it).
const VIEWS = [
  { key: "dashboard", label: "Dashboard", module: null, render: viewDashboard },
  { key: "outstanding", label: "Outstanding", module: "accounts", render: viewOutstanding },
  { key: "stock", label: "Stock", module: "items", render: viewStock },
  { key: "invoices", label: "Invoices", module: "sales_log", render: viewInvoices },
  { key: "gst", label: "GST", module: "gst", render: viewGst },
  { key: "documents", label: "Bills", module: "documents", render: viewDocuments },
];

// ---- helpers ----
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
};
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
const money = (n) =>
  n == null ? "—" : "₹" + Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (n) => (n == null ? "—" : Number(n).toLocaleString("en-IN"));

function toast(msg) {
  const t = el("div", "toast", esc(msg));
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch("/api" + path, Object.assign({}, opts, { headers }));
  if (res.status === 401) {
    doLogout();
    throw new Error("Session expired — please log in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function can(module) {
  if (!module) return true;
  return user && user.permitted_modules && user.permitted_modules.includes(module);
}

// ---- auth ----
function showLogin() {
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}

async function doLogin(e) {
  e.preventDefault();
  const btn = $("#login-btn");
  const errEl = $("#login-error");
  errEl.textContent = "";
  btn.disabled = true;
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("#login-username").value.trim(),
        password: $("#login-password").value,
      }),
    });
    token = data.access_token;
    user = data.user;
    localStorage.setItem("gemini_token", token);
    localStorage.setItem("gemini_user", JSON.stringify(user));
    $("#login-password").value = "";
    showApp();
  } catch (err) {
    errEl.textContent = err.message || "Login failed";
  } finally {
    btn.disabled = false;
  }
}

function doLogout() {
  token = null;
  user = null;
  localStorage.removeItem("gemini_token");
  localStorage.removeItem("gemini_user");
  showLogin();
}

// ---- app shell ----
function showApp() {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#user-chip").textContent = (user.full_name || user.username) + " · " + (user.role || "");
  $("#must-change").classList.toggle("hidden", !user.must_change_password);

  const nav = $("#nav");
  nav.innerHTML = "";
  const visible = VIEWS.filter((v) => can(v.module));
  visible.forEach((v) => {
    const b = el("button", "", esc(v.label));
    b.dataset.key = v.key;
    b.onclick = () => selectView(v.key);
    nav.appendChild(b);
  });
  if (visible.length) selectView(visible[0].key);
}

async function selectView(key) {
  document.querySelectorAll("#nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.key === key)
  );
  const view = VIEWS.find((v) => v.key === key);
  const content = $("#content");
  content.innerHTML = '<div class="loading">Loading…</div>';
  try {
    await view.render(content);
  } catch (err) {
    content.innerHTML = "";
    content.appendChild(el("div", "empty", esc(err.message || "Failed to load")));
  }
}

// ---- views ----
async function viewDashboard(root) {
  const d = await api("/dashboard");
  root.innerHTML = "";
  root.appendChild(el("h2", "view-title", "Today · " + esc(d.today)));
  const grid = el("div", "metrics");
  const metric = (label, value, small) => {
    const m = el("div", "metric");
    m.appendChild(el("div", "label", esc(label)));
    m.appendChild(el("div", "value" + (small ? " small" : ""), value));
    return m;
  };
  const sales = d.sales_today;
  grid.appendChild(metric("Sales today", sales ? money(sales.total) : "—", true));
  grid.appendChild(metric("Invoices today", sales ? num(sales.count) : "—"));
  grid.appendChild(metric("Receivable", money(d.receivable_total), true));
  grid.appendChild(metric("Payable", money(d.payable_total), true));
  grid.appendChild(metric("Low stock items", d.low_stock_count == null ? "—" : num(d.low_stock_count)));
  root.appendChild(grid);
}

function partyList(rows, kind) {
  if (!rows.length) return el("div", "empty", "Nothing outstanding.");
  const frag = document.createDocumentFragment();
  rows.forEach((r) => {
    const c = el("div", "card");
    const row = el("div", "row");
    const left = el("div");
    left.appendChild(el("div", "primary", esc(r.name)));
    left.appendChild(el("div", "muted", esc(r.gstin || "No GSTIN")));
    row.appendChild(left);
    row.appendChild(el("div", "amount primary", money(r.outstanding)));
    c.appendChild(row);
    frag.appendChild(c);
  });
  return frag;
}

async function viewOutstanding(root) {
  const [cust, supp] = await Promise.all([
    api("/outstanding/customers"),
    api("/outstanding/suppliers"),
  ]);
  root.innerHTML = "";
  root.appendChild(el("h2", "view-title", "Receivable (customers)"));
  root.appendChild(partyList(cust));
  root.appendChild(el("h2", "view-title", "Payable (suppliers)"));
  root.appendChild(partyList(supp));
}

async function viewStock(root) {
  const items = await api("/stock");
  root.innerHTML = "";
  const low = items.filter((i) => i.low_stock).length;
  root.appendChild(el("h2", "view-title", `Stock · ${items.length} items · ${low} low`));
  if (!items.length) {
    root.appendChild(el("div", "empty", "No items."));
    return;
  }
  items.forEach((i) => {
    const c = el("div", "card");
    const row = el("div", "row");
    const left = el("div");
    left.appendChild(el("div", "primary", esc(i.name)));
    left.appendChild(el("div", "muted", esc(i.code) + " · reorder " + num(i.reorder_level)));
    row.appendChild(left);
    const right = el("div");
    right.style.textAlign = "right";
    right.appendChild(el("div", "amount primary", num(i.current_stock) + " " + esc(i.unit || "")));
    if (i.low_stock) right.appendChild(el("span", "badge low", "LOW"));
    row.appendChild(right);
    c.appendChild(row);
    root.appendChild(c);
  });
}

async function viewInvoices(root) {
  const rows = await api("/invoices/recent?limit=30");
  root.innerHTML = "";
  root.appendChild(el("h2", "view-title", "Recent invoices"));
  if (!rows.length) {
    root.appendChild(el("div", "empty", "No invoices."));
    return;
  }
  rows.forEach((inv) => {
    const c = el("div", "card");
    const row = el("div", "row");
    const left = el("div");
    left.appendChild(el("div", "primary", esc(inv.invoice_no)));
    left.appendChild(el("div", "muted", esc(inv.customer_name) + " · " + esc(inv.date)));
    row.appendChild(left);
    row.appendChild(el("div", "amount primary", money(inv.total)));
    c.appendChild(row);
    root.appendChild(c);
  });
}

function financialYear() {
  // Indian FY: Apr 1 -> Mar 31.
  const now = new Date();
  const y = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return { from: `${y}-04-01`, to: `${y + 1}-03-31` };
}

async function viewGst(root) {
  const fy = financialYear();
  root.innerHTML = "";
  root.appendChild(el("h2", "view-title", "GSTR-3B summary"));
  const filters = el("div", "filters");
  const fromI = el("input");
  fromI.type = "date";
  fromI.value = fy.from;
  const toI = el("input");
  toI.type = "date";
  toI.value = fy.to;
  const go = el("button");
  go.textContent = "Load";
  go.style.flex = "0 0 auto";
  filters.appendChild(fromI);
  filters.appendChild(toI);
  filters.appendChild(go);
  root.appendChild(filters);
  const out = el("div");
  root.appendChild(out);

  async function load() {
    out.innerHTML = '<div class="loading">Loading…</div>';
    try {
      const d = await api(`/gst/gstr3b?date_from=${fromI.value}&date_to=${toI.value}`);
      out.innerHTML = "";
      const section = (title, obj) => {
        const c = el("div", "card");
        c.appendChild(el("div", "primary", esc(title)));
        ["cgst", "sgst", "igst"].forEach((h) => {
          const r = el("div", "row muted");
          r.appendChild(el("div", "", h.toUpperCase()));
          r.appendChild(el("div", "amount", money(obj[h])));
          c.appendChild(r);
        });
        return c;
      };
      out.appendChild(section("Output tax (outward)", d.outward_taxable_supplies));
      out.appendChild(section("ITC available", d.itc_available));
      out.appendChild(section("Net tax payable", d.net_tax_payable));
      out.appendChild(section("ITC carried forward", d.itc_carried_forward));
    } catch (err) {
      out.innerHTML = "";
      out.appendChild(el("div", "empty", esc(err.message)));
    }
  }
  go.onclick = load;
  await load();
}

async function viewDocuments(root) {
  const docs = await api("/documents");
  root.innerHTML = "";
  const pending = docs.filter((d) => d.approval_status === "PENDING").length;
  root.appendChild(el("h2", "view-title", `Scanned bills · ${pending} pending`));
  if (!docs.length) {
    root.appendChild(el("div", "empty", "No documents."));
    return;
  }
  docs.forEach((d) => {
    const c = el("div", "card");
    const row = el("div", "row");
    const left = el("div");
    left.appendChild(el("div", "primary", esc(d.file_name)));
    const meta = "OCR " + esc(d.ocr_status) + (d.approved_by ? " · by " + esc(d.approved_by) : "");
    left.appendChild(el("div", "muted", meta));
    row.appendChild(left);
    row.appendChild(el("span", "badge " + esc(d.approval_status), esc(d.approval_status)));
    c.appendChild(row);
    if (d.approval_status === "PENDING") {
      const actions = el("div", "actions");
      const ap = el("button", "btn-approve", "Approve");
      const rj = el("button", "btn-reject", "Reject");
      ap.onclick = () => decide(d.id, "approve");
      rj.onclick = () => decide(d.id, "reject");
      actions.appendChild(ap);
      actions.appendChild(rj);
      c.appendChild(actions);
    }
    root.appendChild(c);
  });
}

async function decide(id, action) {
  try {
    await api(`/documents/${id}/${action}`, { method: "POST", body: JSON.stringify({}) });
    toast("Bill " + (action === "approve" ? "approved" : "rejected"));
    selectView("documents");
  } catch (err) {
    toast(err.message);
  }
}

// ---- boot ----
$("#login-form").addEventListener("submit", doLogin);
$("#logout-btn").addEventListener("click", doLogout);

if (token && user) showApp();
else showLogin();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
