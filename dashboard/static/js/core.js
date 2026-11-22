/* Core: API client, router, toasts, modal, preview drawer, shared formatting. */
"use strict";

const App = {
  pages: {},
  current: null,
  state: { mode: null, health: null, keys: null },
};

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function icons() { if (window.lucide) lucide.createIcons(); }

function fmtMoney(v, cur) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return esc(v);
  return `${cur ? esc(cur) + " " : ""}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtNum(v, digits = 0) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}
function fmtUsd(v, digits = 5) { return v === null || v === undefined ? "—" : `$${Number(v).toFixed(digits)}`; }
function fmtPct(fraction, digits = 1) { return fraction === null || fraction === undefined ? "n/a" : `${(fraction * 100).toFixed(digits)}%`; }
function fmtVal(v) {
  if (v === null || v === undefined || v === "") return `<span class="muted">null</span>`;
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return `<span class="mono">${esc(JSON.stringify(v))}</span>`;
  return esc(v);
}
function timeAgo(epochSec) {
  if (!epochSec) return "—";
  const s = Math.max(0, Date.now() / 1000 - epochSec);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(epochSec * 1000).toLocaleString();
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

/** Set a document preview image with a visible loading state (scans take 2-5 s to render). */
function setPreviewImage(img, url) {
  const viewer = img.closest(".viewer");
  let loader = viewer && viewer.querySelector(".viewer-loading");
  if (viewer && !loader) {
    loader = document.createElement("div");
    loader.className = "viewer-loading";
    viewer.appendChild(loader);
  }
  if (loader) {
    loader.innerHTML = `<div><i data-lucide="loader-2" class="spin"></i>Rendering page…</div>`;
    loader.style.display = "grid";
    icons();
  }
  img.style.opacity = "0.25";
  img.onload = () => { img.style.opacity = "1"; if (loader) loader.style.display = "none"; };
  img.onerror = () => { img.style.opacity = "1"; if (loader) loader.innerHTML = `<div class="err">Preview unavailable</div>`; };
  img.src = url;
}

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body || opts.form ? "POST" : "GET"), headers: {} };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, init);
  if (opts.blob) {
    if (!res.ok) throw new Error(await errorText(res));
    return res;
  }
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  if (!res.ok) {
    const d = json && json.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  return json;
}
async function errorText(res) {
  try { const j = await res.json(); return j.detail || `HTTP ${res.status}`; } catch { return `HTTP ${res.status}`; }
}

/** Poll a background job (batch / eval) until it finishes. onTick(job) is called each poll. */
async function pollJob(jobId, onTick, intervalMs = 1000) {
  for (;;) {
    await sleep(intervalMs);
    const job = await api(`/api/batch/jobs/${jobId}`);
    onTick && onTick(job);
    if (job.status === "completed") return job;
    if (job.status === "failed") throw new Error(job.error || "Job failed");
  }
}

async function downloadBlob(path, body, fallbackName) {
  const res = await api(path, { body, blob: true, method: body ? "POST" : "GET" });
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename=([^;]+)/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1].replace(/"/g, "") : fallbackName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function downloadJson(obj, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" }));
  a.download = name;
  a.click();
}
async function copyText(text, label = "Copied to clipboard") {
  try { await navigator.clipboard.writeText(text); toast(label, "ok"); }
  catch { toast("Copy failed - select the text manually", "warn"); }
}

// ------------------------------------------------------------------ toasts & modal
function toast(msg, kind = "info", ms = 4200) {
  const icon = { ok: "check-circle-2", warn: "alert-triangle", err: "x-circle", info: "info" }[kind] || "info";
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<i data-lucide="${icon}"></i><div>${esc(msg)}</div>`;
  $("#toasts").appendChild(el);
  icons();
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .2s"; setTimeout(() => el.remove(), 220); }, ms);
}

function confirmDialog(title, body, okLabel = "Confirm", danger = false) {
  return new Promise(resolve => {
    $("#modalTitle").textContent = title;
    $("#modalBody").textContent = body;
    const ok = $("#modalOk");
    ok.textContent = okLabel;
    ok.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    const close = v => { $("#modal").classList.remove("open"); $("#overlay").classList.remove("open"); resolve(v); };
    ok.onclick = () => close(true);
    $("#modalCancel").onclick = () => close(false);
    $("#overlay").onclick = () => close(false);
    $("#overlay").classList.add("open");
    $("#modal").classList.add("open");
  });
}

// ------------------------------------------------------------------ preview drawer
/**
 * openPreview({ title, subtitle, docId, badges:[html], banner:{kind,title,items[]},
 *               fields:[{label, value, gt?, match?}], items:[line items], json, extraHtml })
 */
async function openPreview(o) {
  $("#drawerTitle").textContent = o.title || "Preview";
  $("#drawerSub").innerHTML = o.subtitle || "";
  $("#drawerBadges").innerHTML = (o.badges || []).join(" ");
  const left = $("#drawerLeft");
  const right = $("#drawerRight");

  left.innerHTML = o.docId ? `
    <div class="flex items-center justify-between mb-2">
      <div class="card-sub">Document</div>
      <div class="flex gap-1" id="drawerPager"></div>
    </div>
    <div class="viewer"><img id="drawerImg" alt="document preview" /></div>` :
    `<div class="empty"><i data-lucide="image-off"></i>No preview available</div>`;

  let html = "";
  if (o.banner) html += bannerHtml(o.banner.kind, o.banner.title, o.banner.items) + `<div class="h-3"></div>`;
  if (o.fields && o.fields.length) {
    html += `<div class="fields">${o.fields.map(f => `
      <div class="field ${f.match === true ? "match" : f.match === false ? "mismatch" : ""}">
        <div class="field-label"><span>${esc(f.label)}</span>${f.match === true ? '<span class="tick">✓</span>' : f.match === false ? '<span class="cross">✗</span>' : ""}</div>
        <div class="field-value">${fmtVal(f.value)}</div>
        ${f.gt !== undefined ? `<div class="field-gt">ground truth: ${fmtVal(f.gt)}</div>` : ""}
      </div>`).join("")}</div>`;
  }
  if (o.items && o.items.length) html += `<div class="h-3"></div>` + lineItemsTable(o.items, o.currency);
  if (o.extraHtml) html += `<div class="h-3"></div>` + o.extraHtml;
  if (o.json !== undefined) {
    html += `<div class="h-3"></div><div class="code-wrap"><button class="btn btn-sm copy" onclick='copyText(${JSON.stringify(JSON.stringify(o.json, null, 2)).replace(/'/g, "&#39;")})'><i data-lucide="copy"></i>Copy</button><pre class="code">${esc(JSON.stringify(o.json, null, 2))}</pre></div>`;
  }
  right.innerHTML = html || `<div class="empty">Nothing to show</div>`;

  $("#overlay").classList.add("open");
  $("#drawer").classList.add("open");
  $("#overlay").onclick = closePreview;
  icons();

  if (o.docId) {
    let page = 0;
    const img = $("#drawerImg");
    const show = () => setPreviewImage(img, `/api/documents/${encodeURIComponent(o.docId)}/preview?page=${page}`);
    show();
    try {
      const info = await api(`/api/documents/${encodeURIComponent(o.docId)}/info`);
      const n = info.pages_rendered || 1;
      if (n > 1) {
        const pager = $("#drawerPager");
        const render = () => {
          pager.innerHTML = `<button class="btn btn-sm btn-icon" ${page === 0 ? "disabled" : ""} id="pgPrev"><i data-lucide="chevron-left"></i></button>
            <span class="kbd self-center">${page + 1} / ${n}</span>
            <button class="btn btn-sm btn-icon" ${page >= n - 1 ? "disabled" : ""} id="pgNext"><i data-lucide="chevron-right"></i></button>`;
          icons();
          $("#pgPrev").onclick = () => { page--; show(); render(); };
          $("#pgNext").onclick = () => { page++; show(); render(); };
        };
        render();
      }
    } catch { /* preview still works without page info */ }
  }
}
function closePreview() {
  $("#drawer").classList.remove("open");
  $("#overlay").classList.remove("open");
}
document.addEventListener("keydown", e => { if (e.key === "Escape") closePreview(); });

function bannerHtml(kind, title, items) {
  const icon = { ok: "check-circle-2", warn: "alert-triangle", err: "x-octagon", info: "info", muted: "file-check" }[kind] || "info";
  return `<div class="banner banner-${kind}"><i data-lucide="${icon}"></i><div><div style="font-weight:600">${esc(title)}</div>
    ${items && items.length ? `<ul>${items.map(i => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}</div></div>`;
}

function lineItemsTable(items, currency) {
  if (!items || !items.length) return `<div class="empty">No line items</div>`;
  const sum = items.reduce((a, i) => a + (Number(i.amount) || 0), 0);
  return `<div class="card table-wrap"><table class="table">
    <thead><tr><th>#</th><th>Description</th><th class="num">Qty</th><th class="num">Amount</th></tr></thead>
    <tbody>${items.map((it, i) => `<tr><td class="muted">${i + 1}</td><td>${esc(it.description)}</td>
      <td class="num">${it.quantity === null || it.quantity === undefined ? '<span class="muted">null</span>' : fmtNum(it.quantity, 2)}</td>
      <td class="num ${Number(it.amount) < 0 ? "err" : ""}">${fmtMoney(it.amount)}</td></tr>`).join("")}
      <tr><td></td><td class="muted">Sum of line items</td><td></td><td class="num" style="font-weight:600">${fmtMoney(sum, currency)}</td></tr>
    </tbody></table></div>`;
}

/** Status badge for an extraction result row. */
function statusBadge(r) {
  if (r.error) return `<span class="badge badge-err" title="${esc(r.error)}"><i data-lucide="x-circle"></i>Error</span>`;
  if (r.needs_review) return `<span class="badge badge-warn" title="${esc((r.review_reasons || []).join(" | "))}"><i data-lucide="alert-triangle"></i>Needs review</span>`;
  if (r.needs_review === undefined) return `<span class="badge badge-muted">Saved</span>`;
  return `<span class="badge badge-ok"><i data-lucide="check"></i>Valid</span>`;
}

function invoiceFields(d, gt, matches) {
  const keys = [["vendor", "Vendor"], ["invoice_number", "Invoice number"], ["invoice_date", "Invoice date"],
    ["currency", "Currency"], ["tax_total", "Tax total"], ["total", "Total"]];
  return keys.map(([k, label]) => ({
    label, value: (k === "tax_total" || k === "total") && d[k] !== null && d[k] !== undefined ? fmtMoney(d[k], d.currency) : d[k],
    gt: gt ? ((k === "tax_total" || k === "total") && gt[k] !== null && gt[k] !== undefined ? fmtMoney(gt[k], gt.currency) : gt[k]) : undefined,
    match: matches ? matches[k] : undefined,
  }));
}

/** Preview an invoice extraction result (batch row, upload, saved output). */
function previewInvoiceResult(r, docId) {
  const d = r.data || {};
  let banner;
  if (r.error) banner = { kind: "err", title: `${r.error_type || "Error"}: ${r.error}` };
  else if (d.is_invoice === false) banner = { kind: "info", title: "Not an invoice: every other field is null by design." };
  else if (r.needs_review) banner = { kind: "warn", title: "Needs review: validation issues survived the corrective retries", items: r.review_reasons };
  else if (r.needs_review === false) banner = { kind: "ok", title: "Schema valid and totals balance (sum of items + tax = total)." };
  const cost = r.cost ? `<div class="flex flex-wrap gap-2">
      <span class="badge badge-muted">${esc(r.mode || "")}</span>
      <span class="badge badge-muted">${r.cost.calls ?? 0} LLM call(s)</span>
      <span class="badge badge-muted">${fmtNum(r.cost.tokens_in)} in / ${fmtNum(r.cost.tokens_out)} out tokens</span>
      <span class="badge badge-muted">${fmtUsd(r.cost.cost_usd)}</span>
      ${r.elapsed_ms !== undefined ? `<span class="badge badge-muted">${(r.elapsed_ms / 1000).toFixed(1)} s</span>` : ""}
      ${r.cached ? '<span class="badge badge-info">cached</span>' : ""}</div>` : "";
  openPreview({
    title: r.filename || docId, subtitle: `<span class="mono muted">${esc(docId || r.doc_id || "")}</span>`,
    docId: docId || r.stored_as || r.doc_id, badges: [statusBadge(r)], banner,
    fields: d.is_invoice === false ? [] : invoiceFields(d, r.ground_truth, r.matches),
    items: d.line_items, currency: d.currency, extraHtml: cost, json: d,
  });
}

// ------------------------------------------------------------------ router
function registerPage(name, def) { App.pages[name] = def; }

async function navigate(name, opts = {}) {
  if (!App.pages[name]) name = "overview";
  const def = App.pages[name];
  $$(".page").forEach(p => p.classList.toggle("active", p.id === `page-${name}`));
  $$(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.page === name));
  $("#pageTitle").textContent = def.title;
  $("#pageSub").textContent = def.sub || "";
  App.current = name;
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  if (!def._inited && def.init) { def._inited = true; try { await def.init(); } catch (e) { toast(e.message, "err"); } }
  if (def.show) { try { await def.show(opts); } catch (e) { toast(e.message, "err"); } }
  icons();
  window.scrollTo({ top: 0 });
}

function currentMode() { return $("#modeSelect").value; }

async function loadEngineStatus() {
  const orb = $("#statusOrb"), label = $("#footStatusLabel");
  try {
    const [h, k] = await Promise.all([api("/health"), api("/api/settings/keys")]);
    App.state.health = h; App.state.keys = k;
    const sel = $("#modeSelect");
    if (!App.state.mode && h.active_mode && [...sel.options].some(o => o.value === h.active_mode)) sel.value = h.active_mode;
    App.state.mode = sel.value;
    orb.className = "status-orb ok";
    const llm = sel.value === "groq" ? `${k.groq.keys_count} Groq key(s)` : sel.value;
    label.textContent = `API online · ${llm} · PII shield ${k.pii_shield_enabled ? "on" : "off"}`;
  } catch (e) {
    orb.className = "status-orb err";
    label.textContent = "API unreachable";
  }
  icons();
}

// ------------------------------------------------------------------ visual helpers
/** Animate the number inside el from 0 to its final text (keeps prefixes/suffixes like $ and %). */
function countUp(el, duration = 1100) {
  if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const final = el.textContent;
  const m = final.match(/-?[\d,]*\.?\d+/);
  if (!m) return;
  const target = parseFloat(m[0].replace(/,/g, ""));
  const decimals = (m[0].split(".")[1] || "").length;
  const useComma = m[0].includes(",");
  const t0 = performance.now();
  const step = now => {
    const p = Math.min(1, (now - t0) / duration);
    const v = target * (1 - Math.pow(1 - p, 3));
    let txt = v.toFixed(decimals);
    if (useComma) txt = Number(txt).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    el.textContent = final.replace(m[0], txt);
    if (p < 1) requestAnimationFrame(step); else el.textContent = final;
  };
  requestAnimationFrame(step);
}

/** Smooth SVG sparkline with a gradient area. */
function sparkline(values, color = "#5ee08f") {
  const vals = (values || []).map(Number).filter(v => !Number.isNaN(v));
  if (vals.length < 2) return `<svg class="spark" viewBox="0 0 200 46"></svg>`;
  const w = 200, h = 46, pad = 4;
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const pts = vals.map((v, i) => [pad + i * (w - 2 * pad) / (vals.length - 1),
    h - pad - (max === min ? (h - 2 * pad) / 2 : (v - min) / span * (h - 2 * pad))]);
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
    const cx = (x0 + x1) / 2;
    d += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
  }
  const id = "g" + Math.random().toString(36).slice(2, 8);
  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path class="area" d="${d} L${last[0]},${h} L${pts[0][0]},${h} Z" fill="url(#${id})"/>
    <path class="line" d="${d}" stroke="${color}" style="filter:drop-shadow(0 0 6px ${color}66)"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="3" fill="${color}" style="filter:drop-shadow(0 0 6px ${color})"/></svg>`;
}

/** Radial gauge (240 degree arc) with tick marks; value 0-100. Call animateGauges() after inserting. */
function gaugeHtml(value, sub, legend) {
  const r = 92, cx = 120, cy = 118, sweep = 240, start = 150;
  const rad = a => (a * Math.PI) / 180;
  const pt = (a, rr = r) => [cx + rr * Math.cos(rad(a)), cy + rr * Math.sin(rad(a))];
  const [sx, sy] = pt(start), [ex, ey] = pt(start + sweep);
  const arcPath = `M${sx},${sy} A${r},${r} 0 1 1 ${ex},${ey}`;
  const len = (Math.PI * 2 * r * sweep) / 360;
  let ticks = "";
  for (let i = 0; i <= 40; i++) {
    const a = start + (sweep * i) / 40;
    const [x1, y1] = pt(a, r + 14), [x2, y2] = pt(a, r + (i % 5 === 0 ? 22 : 18));
    ticks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`;
  }
  const id = "ga" + Math.random().toString(36).slice(2, 7);
  const clamped = Math.max(0, Math.min(100, Number(value) || 0));
  return `<div class="gauge-wrap">
    <svg class="gauge" viewBox="0 0 240 200">
      <defs><linearGradient id="${id}" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#ff9a1f"/><stop offset=".55" stop-color="#ffd48a"/><stop offset="1" stop-color="#9b7bff"/></linearGradient></defs>
      <g class="ticks">${ticks}</g>
      <path class="track" d="${arcPath}" fill="none" stroke-width="14" stroke-linecap="round"/>
      <path class="arc" d="${arcPath}" fill="none" stroke="url(#${id})" stroke-width="14" stroke-linecap="round"
        stroke-dasharray="${len.toFixed(1)}" stroke-dashoffset="${len.toFixed(1)}" data-target="${(len * (1 - clamped / 100)).toFixed(1)}"/>
    </svg>
    <div class="gauge-center"><div class="v" data-count>${esc(value)}%</div><div class="s">${esc(sub || "")}</div></div>
  </div>
  ${legend ? `<div class="gauge-legend">${legend.map(l => `<div><div class="k"><i style="background:${l.color}"></i>${esc(l.label)}</div><div class="n">${esc(l.value)}</div></div>`).join("")}</div>` : ""}`;
}
function animateGauges(root = document) {
  requestAnimationFrame(() => setTimeout(() => {
    $$(".gauge .arc", root).forEach(a => a.setAttribute("stroke-dashoffset", a.dataset.target));
    $$(".gauge-center [data-count]", root).forEach(el => countUp(el, 1500));
  }, 60));
}

// ------------------------------------------------------------------ document search (Ctrl+K)
const Search = { items: null, sel: 0 };
async function searchIndex() {
  if (Search.items) return Search.items;
  try {
    const o = await api("/api/overview");
    Search.items = o.outputs.map(x => ({
      id: x.doc_id.toUpperCase(),
      vendor: x.vendor || (x.is_invoice === false ? "Not an invoice" : "—"),
      num: x.invoice_number || "",
      total: x.is_invoice ? fmtMoney(x.total, x.currency) : "",
    }));
  } catch { Search.items = []; }
  return Search.items;
}
async function renderSearch() {
  const q = $("#docSearch").value.trim().toLowerCase();
  const items = (await searchIndex()).filter(x => !q || `${x.id} ${x.vendor} ${x.num}`.toLowerCase().includes(q)).slice(0, 12);
  Search.sel = Math.min(Search.sel, Math.max(0, items.length - 1));
  const pop = $("#searchPop");
  pop.innerHTML = items.length ? items.map((x, i) => `<div class="search-item ${i === Search.sel ? "sel" : ""}" data-id="${esc(x.id)}">
      <span class="id">${esc(x.id)}</span><div class="min-w-0 flex-1"><div class="truncate-1" style="font-weight:600">${esc(x.vendor)}</div>
      <div class="hint mono truncate-1">${esc(x.num)}</div></div><span class="hint mono">${x.total}</span></div>`).join("")
    : `<div class="empty" style="padding:18px">No matching document</div>`;
  pop.classList.add("open");
  $$(".search-item", pop).forEach(el => el.onmousedown = e => { e.preventDefault(); openSearchResult(el.dataset.id); });
}
function openSearchResult(id) {
  $("#searchPop").classList.remove("open");
  $("#docSearch").value = "";
  $("#docSearch").blur();
  navigate("workspace", { docId: id });
}
function initSearch() {
  const input = $("#docSearch");
  input.addEventListener("focus", () => { Search.sel = 0; renderSearch(); });
  input.addEventListener("input", () => { Search.sel = 0; renderSearch(); });
  input.addEventListener("blur", () => setTimeout(() => $("#searchPop").classList.remove("open"), 120));
  input.addEventListener("keydown", e => {
    const n = $$("#searchPop .search-item").length;
    if (e.key === "ArrowDown") { Search.sel = Math.min(n - 1, Search.sel + 1); renderSearch(); e.preventDefault(); }
    if (e.key === "ArrowUp") { Search.sel = Math.max(0, Search.sel - 1); renderSearch(); e.preventDefault(); }
    if (e.key === "Enter") { const el = $$("#searchPop .search-item")[Search.sel]; if (el) openSearchResult(el.dataset.id); }
    if (e.key === "Escape") input.blur();
  });
  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); input.focus(); }
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  $$(".nav-item").forEach(b => b.addEventListener("click", () => navigate(b.dataset.page)));
  $("#modeSelect").addEventListener("change", () => { App.state.mode = currentMode(); toast(`Engine for this session: ${$("#modeSelect").selectedOptions[0].text}`); loadEngineStatus(); });
  $("#drawerClose").addEventListener("click", closePreview);
  initSearch();
  await loadEngineStatus();
  icons();
  navigate((location.hash || "#overview").slice(1));
});
window.addEventListener("hashchange", () => {
  const n = location.hash.slice(1);
  if (n && n !== App.current) navigate(n);
});
