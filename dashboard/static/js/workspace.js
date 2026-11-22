/* Workspace: one document, its extraction, validation status and the ground-truth comparison. */
"use strict";

const WS = { docId: null, previewId: null, page: 0, pages: 1, zoom: 1, result: null, gt: null, matches: null, evalRecords: null };

function wsSetTab(name) {
  $$("#page-workspace .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  $$("#page-workspace .tab-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === name));
}

function wsShowImage() {
  setPreviewImage($("#wsImg"), `/api/documents/${encodeURIComponent(WS.previewId)}/preview?page=${WS.page}`);
  $("#wsImg").style.transform = `scale(${WS.zoom})`;
  const pager = $("#wsPager");
  if (WS.pages > 1) {
    pager.innerHTML = `<button class="btn btn-sm btn-icon" id="wsPrev" ${WS.page === 0 ? "disabled" : ""}><i data-lucide="chevron-left"></i></button>
      <span class="kbd">${WS.page + 1}/${WS.pages}</span>
      <button class="btn btn-sm btn-icon" id="wsNext" ${WS.page >= WS.pages - 1 ? "disabled" : ""}><i data-lucide="chevron-right"></i></button>`;
    $("#wsPrev").onclick = () => { WS.page--; wsShowImage(); };
    $("#wsNext").onclick = () => { WS.page++; wsShowImage(); };
  } else pager.innerHTML = "";
  icons();
}

async function wsLoadPreview(previewId, label) {
  WS.previewId = previewId; WS.page = 0; WS.zoom = 1; WS.pages = 1;
  $("#wsDocName").textContent = label || previewId;
  try { WS.pages = (await api(`/api/documents/${encodeURIComponent(previewId)}/info`)).pages_rendered || 1; } catch { WS.pages = 1; }
  wsShowImage();
}

async function wsEvalRecords() {
  if (WS.evalRecords) return WS.evalRecords;
  try {
    const e = await api("/api/eval/latest");
    WS.evalRecords = {};
    if (e.available) for (const r of e.result.document_records) WS.evalRecords[r.doc_id] = r;
  } catch { WS.evalRecords = {}; }
  return WS.evalRecords;
}

function wsRender(meta) {
  const r = WS.result || {};
  const d = r.data;
  if (!d) {
    $("#wsBanner").innerHTML = r.error ? bannerHtml("err", `${r.error_type || "Error"}: ${r.error}`) :
      bannerHtml("muted", "No extraction yet for this document. Click “Extract & validate”.");
    ["#wsFields", "#wsItems", "#wsCompare"].forEach(s => $(s).innerHTML = "");
    $("#wsJson").textContent = "";
    $("#wsMeta").innerHTML = "";
    icons();
    return;
  }
  // banner
  let banner;
  if (meta.saved) banner = bannerHtml("muted", "Committed output from the last CLI run (outputs/). Click “Extract & validate” to re-run with the selected engine.");
  else if (d.is_invoice === false) banner = bannerHtml("info", "Classified as NOT an invoice: all other fields are null by design.");
  else if (r.needs_review) banner = bannerHtml("warn", "Needs review: these checks still fail after the corrective retries", r.review_reasons);
  else banner = bannerHtml("ok", "Schema valid, required fields present, and sum(line items) + tax = total.");
  $("#wsBanner").innerHTML = banner;

  // meta chips
  $("#wsMeta").innerHTML = r.cost ? [
    `<span class="badge badge-muted">${esc(r.mode || "")}</span>`,
    `<span class="badge badge-muted">${r.cost.calls ?? 0} LLM call(s)</span>`,
    `<span class="badge badge-muted">${fmtNum(r.cost.tokens_in)} in / ${fmtNum(r.cost.tokens_out)} out</span>`,
    `<span class="badge badge-muted">${fmtUsd(r.cost.cost_usd)}</span>`,
    r.elapsed_ms !== undefined ? `<span class="badge badge-muted">${(r.elapsed_ms / 1000).toFixed(1)} s</span>` : "",
    r.cached ? `<span class="badge badge-info">cached</span>` : "",
  ].join("") : "";

  // fields
  const showGt = WS.gt && !meta.upload;
  if (d.is_invoice === false) {
    $("#wsFields").innerHTML = `<div class="fields"><div class="field ${showGt && WS.matches ? (WS.matches.is_invoice ? "match" : "mismatch") : ""}"><div class="field-label">is_invoice</div><div class="field-value">false</div></div></div>`;
  } else {
    const f = invoiceFields(d, null, showGt ? WS.matches : null);
    $("#wsFields").innerHTML = `<div class="fields">${f.map(x => `<div class="field ${x.match === true ? "match" : x.match === false ? "mismatch" : ""}">
      <div class="field-label"><span>${esc(x.label)}</span>${x.match === true ? '<span class="tick">✓</span>' : x.match === false ? '<span class="cross">✗</span>' : ""}</div>
      <div class="field-value">${fmtVal(x.value)}</div></div>`).join("")}</div>
      <div class="h-3"></div>${lineItemsTable(d.line_items, d.currency)}`;
  }
  $("#wsItems").innerHTML = lineItemsTable(d.line_items, d.currency);

  // compare
  if (!showGt) {
    $("#wsCompare").innerHTML = `<div class="empty"><i data-lucide="git-compare"></i>Ground truth exists only for the labelled documents L01–L10.</div>`;
  } else {
    const gt = WS.gt;
    const row = (k, label, fmt = v => v) => {
      const m = WS.matches ? WS.matches[k] : undefined;
      return `<tr><td>${label}</td><td>${fmtVal(fmt(d[k]))}</td><td>${fmtVal(fmt(gt[k]))}</td>
        <td class="center">${m === true ? '<span class="tick">✓</span>' : m === false ? '<span class="cross">✗</span>' : "—"}</td></tr>`;
    };
    const money = v => v === null || v === undefined ? v : Number(v).toFixed(2);
    $("#wsCompare").innerHTML = `<div class="card table-wrap"><table class="table"><thead><tr><th>Field</th><th>Prediction</th><th>Ground truth</th><th class="center">Match</th></tr></thead><tbody>
      ${row("is_invoice", "is_invoice")}${row("vendor", "vendor")}${row("invoice_number", "invoice_number")}${row("invoice_date", "invoice_date")}
      ${row("currency", "currency")}${row("tax_total", "tax_total", money)}${row("total", "total", money)}
      <tr><td>line_items</td><td>${(d.line_items || []).length} rows</td><td>${(gt.line_items || []).length} rows</td>
      <td class="center">${WS.matches ? (WS.matches.line_items ? '<span class="tick">✓</span>' : '<span class="cross">✗</span>') : "—"}</td></tr>
      </tbody></table></div>
      <div class="grid gap-3 mt-3" style="grid-template-columns:1fr 1fr"><div><div class="label">Predicted rows</div>${lineItemsTable(d.line_items, d.currency)}</div>
      <div><div class="label">Ground-truth rows</div>${lineItemsTable(gt.line_items, gt.currency)}</div></div>
      <div class="hint mt-2">Matching rules are listed on the Evaluation page.</div>`;
  }
  $("#wsJson").textContent = JSON.stringify(d, null, 2);
  icons();
}

async function wsSelect(docId) {
  WS.docId = docId; WS.result = null; WS.gt = null; WS.matches = null;
  $("#wsDoc").value = docId;
  await wsLoadPreview(docId, docId);
  const [saved, gt, records] = await Promise.all([
    api(`/api/documents/${docId}/output`).catch(() => null),
    api(`/api/documents/${docId}/ground-truth`).catch(() => null),
    wsEvalRecords(),
  ]);
  WS.gt = gt;
  WS.result = saved && saved.exists ? { data: saved.data } : null;
  // the committed outputs/Lxx.json come from the same eval run, so its field verdicts apply
  const rec = records[docId];
  if (gt && rec && saved && saved.exists && JSON.stringify(rec.predicted) === JSON.stringify(saved.data)) WS.matches = rec.field_matches;
  wsRender({ saved: true });
}

async function wsExtract() {
  if (!WS.docId) return;
  const btn = $("#wsExtract");
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i>Extracting…`; icons();
  try {
    const r = await api(`/api/extract/${encodeURIComponent(WS.docId)}?mode=${encodeURIComponent(currentMode())}`, { method: "POST" });
    WS.result = r;
    if (r.ground_truth) WS.gt = r.ground_truth;
    WS.matches = r.matches || null;
    wsRender({});
    if (r.error) toast(r.error, "err");
    else toast(r.needs_review ? "Extracted - needs review" : "Extracted and validated", r.needs_review ? "warn" : "ok");
  } catch (e) { toast(e.message, "err"); }
  finally { btn.disabled = false; btn.innerHTML = `<i data-lucide="play"></i>Extract &amp; validate`; icons(); }
}

async function wsUpload(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", currentMode());
  toast(`Extracting ${file.name}…`);
  try {
    const r = await api("/api/upload-and-extract", { form: fd });
    WS.docId = null; WS.gt = null; WS.matches = null; WS.result = r;
    $("#wsDoc").value = "";
    await wsLoadPreview(r.stored_as || r.doc_id, file.name);
    wsRender({ upload: true });
    if (r.error) toast(r.error, "err");
    else toast(r.needs_review ? "Extracted - needs review" : "Extracted and validated", r.needs_review ? "warn" : "ok");
  } catch (e) { toast(e.message, "err"); }
}

registerPage("workspace", {
  title: "Workspace",
  sub: "Inspect one document: preview, extracted fields, validation and ground truth",
  async init() {
    const list = await api("/api/documents");
    const groups = { labelled: [], unlabelled: [] };
    for (const d of list.documents) (groups[d.category] || (groups[d.category] = [])).push(d);
    $("#wsDoc").innerHTML = `<option value="" disabled>Choose a document…</option>` + Object.entries(groups).filter(([, v]) => v.length).map(([g, docs]) =>
      `<optgroup label="${g === "labelled" ? "Labelled (ground truth)" : g === "unlabelled" ? "Unlabelled" : "Uploaded"}">
      ${docs.map(d => `<option value="${esc(d.id)}">${esc(d.id)} · ${esc(d.filename)}</option>`).join("")}</optgroup>`).join("");
    $("#wsDoc").onchange = () => wsSelect($("#wsDoc").value);
    $("#wsExtract").onclick = wsExtract;
    $("#wsUpload").onchange = e => { wsUpload(e.target.files[0]); e.target.value = ""; };
    $$("#page-workspace .tab").forEach(t => t.onclick = () => wsSetTab(t.dataset.tab));
    $("#wsZoomIn").onclick = () => { WS.zoom = Math.min(3, WS.zoom * 1.2); $("#wsImg").style.transform = `scale(${WS.zoom})`; };
    $("#wsZoomOut").onclick = () => { WS.zoom = Math.max(0.4, WS.zoom / 1.2); $("#wsImg").style.transform = `scale(${WS.zoom})`; };
    $("#wsZoomReset").onclick = () => { WS.zoom = 1; $("#wsImg").style.transform = "scale(1)"; };
    $("#wsCopy").onclick = () => WS.result && WS.result.data && copyText(JSON.stringify(WS.result.data, null, 2));
    $("#wsDownload").onclick = () => WS.result && WS.result.data && downloadJson(WS.result.data, `${WS.docId || "document"}.json`);
    // drag & drop onto the viewer
    const v = $("#wsViewer");
    v.addEventListener("dragover", e => { e.preventDefault(); v.style.outline = "2px dashed var(--accent)"; });
    v.addEventListener("dragleave", () => { v.style.outline = ""; });
    v.addEventListener("drop", e => { e.preventDefault(); v.style.outline = ""; wsUpload(e.dataTransfer.files[0]); });
  },
  async show(opts = {}) {
    const id = opts.docId || WS.docId || "L01";
    if (opts.docId || !WS.docId) await wsSelect(id);
  },
});
