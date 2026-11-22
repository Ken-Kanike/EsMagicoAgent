/* Batch processing: invoice schema or any saved template, background job with live progress. */
"use strict";

const B = { queue: [], records: [], template: null, templates: [], filter: "all", job: null, running: false };

function bSchemaChanged() {
  const id = $("#bSchema").value;
  B.template = B.templates.find(t => t.id === id) || null;
  const fields = B.template ? B.template.fields.map(f => ({ key: f.key, type: f.data_type, req: f.required }))
    : ["is_invoice", "vendor", "invoice_number", "invoice_date", "currency", "line_items", "tax_total", "total"].map(k => ({ key: k }));
  $("#bSchemaFields").innerHTML = fields.map(f => `<span class="badge ${f.req ? "badge-info" : "badge-muted"} mono" title="${esc(f.type || "")}">${esc(f.key)}</span>`).join("");
  $("#bSchemaHint").textContent = B.template
    ? `Custom template "${B.template.name}": ${B.template.fields.length} fields. Missing required fields set needs_review.`
    : "Standard invoice fields with arithmetic validation and needs_review flags.";
}

async function bLoadTemplates(selectId) {
  const r = await api("/api/templates/list");
  B.templates = r.templates || [];
  $("#bSchema").innerHTML = `<option value="">Invoice schema (8 fields, validated)</option>` +
    (B.templates.length ? `<optgroup label="Saved templates">${B.templates.map(t => `<option value="${esc(t.id)}">${esc(t.name)} · ${t.fields.length} fields</option>`).join("")}</optgroup>` : "");
  if (selectId !== undefined) $("#bSchema").value = selectId || "";
  bSchemaChanged();
}

function bRenderQueue() {
  $("#bQueue").innerHTML = B.queue.map((f, i) => `<span class="chip"><i data-lucide="file" style="width:12px;height:12px"></i>${esc(f.name)}
    <span class="muted">${(f.size / 1024).toFixed(0)} KB</span><button data-i="${i}" title="Remove"><i data-lucide="x" style="width:12px;height:12px"></i></button></span>`).join("");
  $$("#bQueue button").forEach(b => b.onclick = () => { B.queue.splice(+b.dataset.i, 1); bRenderQueue(); });
  $("#bRun").disabled = !B.queue.length || B.running;
  $("#bRunLabel").textContent = `Process ${B.queue.length} file${B.queue.length === 1 ? "" : "s"}`;
  icons();
}

function bAdd(files) {
  const ok = /\.(pdf|png|jpe?g|webp|tiff?)$/i;
  let skipped = 0;
  for (const f of files) {
    if (!ok.test(f.name)) { skipped++; continue; }
    if (!B.queue.some(q => q.name === f.name && q.size === f.size)) B.queue.push(f);
  }
  if (skipped) toast(`${skipped} file(s) skipped: unsupported type`, "warn");
  bRenderQueue();
}

function bIsTemplate() { return B.records.length && B.records[0].template_id !== undefined; }

function bKpis(job) {
  const rs = B.records;
  const cost = rs.reduce((a, r) => a + ((r.cost && r.cost.cost_usd) || 0), 0);
  const tin = rs.reduce((a, r) => a + ((r.cost && r.cost.tokens_in) || 0), 0);
  const tout = rs.reduce((a, r) => a + ((r.cost && r.cost.tokens_out) || 0), 0);
  const review = rs.filter(r => r.needs_review && !r.error).length;
  const errors = rs.filter(r => r.error).length;
  const tile = (icon, label, value, tone = "", foot = "") => `<div class="card kpi"><div class="kpi-label"><i data-lucide="${icon}"></i>${label}</div><div class="kpi-value ${tone}">${value}</div><div class="kpi-foot">${foot}</div></div>`;
  $("#bKpis").innerHTML = rs.length ? [
    tile("files", "Processed", rs.length, "", job ? `${job.elapsed_s}s wall time` : "committed outputs"),
    tile("check-circle-2", "Valid", rs.length - review - errors, "ok"),
    tile("alert-triangle", "Needs review", review, review ? "warn" : ""),
    tile("x-circle", "Errors", errors, errors ? "err" : ""),
    tile("coins", "Cost (list price)", fmtUsd(cost, 4), "", `${fmtNum(tin)} in / ${fmtNum(tout)} out tokens`),
  ].join("") : "";
}

function bFiltered() {
  return B.records.filter(r => B.filter === "all" ? true : B.filter === "error" ? !!r.error
    : B.filter === "review" ? (r.needs_review && !r.error) : (!r.error && !r.needs_review));
}

function bRenderTable() {
  const rows = bFiltered();
  const tmpl = bIsTemplate();
  if (tmpl) {
    const fields = (B.job && B.job.template && B.job.template.fields) || (B.template ? B.template.fields : Object.keys(B.records[0].data || {}).map(k => ({ key: k })));
    const cols = fields.slice(0, 6);
    $("#bHead").innerHTML = `<tr><th>File</th>${cols.map(c => `<th>${esc(c.label || c.key)}</th>`).join("")}<th class="num">Missing</th><th>Status</th><th class="num">Cost</th></tr>`;
    $("#bBody").innerHTML = rows.map(r => `<tr class="clickable" data-i="${B.records.indexOf(r)}"><td class="truncate-1" style="max-width:220px">${esc(r.filename)}</td>
      ${cols.map(c => { const v = (r.data || {})[c.key]; return `<td class="truncate-1" style="max-width:200px">${Array.isArray(v) ? `<span class="badge badge-muted">${v.length} rows</span>` : fmtVal(v)}</td>`; }).join("")}
      <td class="num">${(r.missing_fields || []).length}</td><td>${tmplStatus(r, fields.length)}</td><td class="num">${fmtUsd(r.cost && r.cost.cost_usd)}</td></tr>`).join("");
  } else {
    $("#bHead").innerHTML = `<tr><th>File</th><th>Type</th><th>Vendor</th><th>Invoice #</th><th>Date</th><th class="num">Items</th><th class="num">Tax</th><th class="num">Total</th><th>Status</th><th class="num">Cost</th><th class="num">Sec</th></tr>`;
    $("#bBody").innerHTML = rows.map(r => `<tr class="clickable" data-i="${B.records.indexOf(r)}">
      <td class="truncate-1" style="max-width:220px">${esc(r.filename)}</td>
      <td>${r.error ? "—" : r.is_invoice ? '<span class="badge badge-info">invoice</span>' : '<span class="badge badge-muted">not invoice</span>'}</td>
      <td class="truncate-1" style="max-width:200px">${esc(r.vendor || "—")}</td><td class="mono">${esc(r.invoice_number || "—")}</td><td class="mono">${esc(r.invoice_date || "—")}</td>
      <td class="num">${r.is_invoice ? r.line_items_count ?? (r.data && r.data.line_items || []).length : "—"}</td>
      <td class="num">${r.is_invoice ? fmtMoney(r.tax_total) : "—"}</td><td class="num">${r.is_invoice ? fmtMoney(r.total, r.currency) : "—"}</td>
      <td>${statusBadge(r)}</td><td class="num">${r.cost ? fmtUsd(r.cost.cost_usd) : "—"}</td><td class="num">${r.elapsed_ms !== undefined ? (r.elapsed_ms / 1000).toFixed(1) : "—"}</td></tr>`).join("");
  }
  if (!rows.length) $("#bBody").innerHTML = `<tr><td colspan="12"><div class="empty"><i data-lucide="inbox"></i>${B.records.length ? "No rows match this filter." : "No results yet. Add files above and click Process."}</div></td></tr>`;
  $$("#bBody tr[data-i]").forEach(tr => tr.onclick = () => bPreview(B.records[+tr.dataset.i]));
  $("#bExcel").disabled = $("#bZip").disabled = !B.records.length;
  icons();
}

/** Template rows: "Valid" only when something was actually extracted. */
function tmplStatus(r, nFields) {
  const missing = (r.missing_fields || []).length;
  if (!r.error && !r.needs_review && nFields && missing >= nFields)
    return `<span class="badge badge-warn" title="None of the template's fields were found"><i data-lucide="search-x"></i>Nothing found</span>`;
  if (!r.error && !r.needs_review && missing)
    return `<span class="badge badge-ok" title="${missing} optional field(s) empty"><i data-lucide="check"></i>Valid · ${missing} empty</span>`;
  return statusBadge(r);
}

function bPreview(r) {
  if (r.template_id === undefined) return previewInvoiceResult(r, r.stored_as || r.doc_id);
  const fields = (B.job && B.job.template && B.job.template.fields) || Object.keys(r.data || {}).map(k => ({ key: k }));
  const missing = new Set(r.missing_fields || []);
  let banner;
  if (r.error) banner = { kind: "err", title: r.error };
  else if (r.needs_review) banner = { kind: "warn", title: "Needs review", items: r.review_reasons && r.review_reasons.length ? r.review_reasons : [`Missing: ${[...missing].join(", ")}`] };
  else banner = { kind: "ok", title: `All required fields found (${r.method === "llm" ? "LLM" : "offline parser"}).` };
  const tables = fields.filter(f => Array.isArray((r.data || {})[f.key]));
  openPreview({
    title: r.filename, subtitle: `Template: ${esc(r.template_name || "")}`, docId: r.stored_as, badges: [statusBadge(r)], banner,
    fields: fields.filter(f => !Array.isArray((r.data || {})[f.key])).map(f => ({ label: f.label || f.key, value: (r.data || {})[f.key], match: missing.has(f.key) ? false : undefined })),
    extraHtml: tables.map(t => {
      const rows = r.data[t.key];
      const cols = rows.length ? Object.keys(rows[0]) : [];
      return `<div class="label">${esc(t.label || t.key)} (${rows.length} rows)</div><div class="card table-wrap"><table class="table"><thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map(x => `<tr>${cols.map(c => `<td>${fmtVal(x[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }).join("") + (r.warning ? bannerHtml("warn", r.warning) : ""),
    json: r.data,
  });
}

async function bRun() {
  if (!B.queue.length) return;
  const fd = new FormData();
  B.queue.forEach(f => fd.append("files", f));
  fd.append("mode", currentMode());
  if (B.template) fd.append("template_id", B.template.id);
  B.running = true; B.records = []; B.job = null;
  $("#bRun").disabled = true;
  $("#bProgressWrap").classList.remove("hidden");
  const setP = (done, total, text) => {
    const pct = total ? Math.round(done / total * 100) : 0;
    $("#bProgress").style.width = `${pct}%`; $("#bProgressPct").textContent = `${pct}%`; $("#bProgressText").textContent = text;
  };
  setP(0, B.queue.length, `Uploading ${B.queue.length} file(s)…`);
  try {
    const { job_id, total } = await api("/api/batch/jobs", { form: fd });
    B.queue = []; bRenderQueue();
    const job = await pollJob(job_id, j => {
      B.job = j; B.records = j.results || [];
      setP(j.done, j.total || total, `${j.status === "queued" ? "Queued" : "Processing"} · ${j.done}/${j.total || total} done · ${j.elapsed_s}s${j.last_file ? ` · last: ${j.last_file}` : ""}`);
      bKpis(j); bRenderTable();
    });
    const flagged = B.records.filter(r => r.needs_review || r.error).length;
    setP(job.total, job.total, `Finished ${job.total} document(s) in ${job.elapsed_s}s · ${flagged} need attention`);
    toast(`Batch finished: ${job.total} documents, ${flagged} need attention`, flagged ? "warn" : "ok");
  } catch (e) { toast(e.message, "err"); setP(0, 1, `Failed: ${e.message}`); }
  finally { B.running = false; bRenderQueue(); }
}

async function bLoadSamples() {
  const o = await api("/api/overview");
  const flagged = Object.fromEntries(o.review_queue.map(q => [q.doc_id, q]));
  const records = await Promise.all(o.outputs.map(async x => {
    const out = await api(`/api/documents/${x.doc_id}/output`).catch(() => ({ data: null }));
    const d = out.data || {};
    const q = flagged[x.doc_id.toUpperCase()];
    return { doc_id: x.doc_id, stored_as: x.doc_id, filename: `${x.doc_id} (committed output)`, ...d, data: d,
      line_items_count: (d.line_items || []).length, needs_review: q ? true : undefined, review_reasons: q ? q.reasons : [] };
  }));
  B.job = null; B.records = records; B.filter = "all";
  $$("#bFilter button").forEach(x => x.classList.toggle("active", x.dataset.f === "all"));
  bKpis(null); bRenderTable();
}

async function bExport(kind) {
  try {
    if (kind === "zip") return await downloadBlob("/api/batch/export-zip", { records: B.records }, "batch.zip");
    if (bIsTemplate()) {
      return await downloadBlob("/api/templates/export-excel", {
        template_name: B.records[0].template_name || "template",
        records: B.records.map(r => ({ file: r.filename, data: r.data || {} })),
      }, "template_batch.xlsx");
    }
    await downloadBlob("/api/batch/export-excel", { records: B.records }, "batch.xlsx");
  } catch (e) { toast(e.message, "err"); }
}

registerPage("batch", {
  title: "Batch processing",
  sub: "Process many documents with the invoice schema or one of your templates",
  async init() {
    const dz = $("#bDrop");
    dz.onclick = () => $("#bFiles").click();
    $("#bFiles").onchange = e => { bAdd(e.target.files); e.target.value = ""; };
    dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("drag"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
    dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("drag"); bAdd(e.dataTransfer.files); });
    $("#bRun").onclick = bRun;
    $("#bClear").onclick = () => { B.queue = []; bRenderQueue(); };
    $("#bSchema").onchange = bSchemaChanged;
    $("#bSamples").onclick = () => bLoadSamples().catch(e => toast(e.message, "err"));
    $("#bExcel").onclick = () => bExport("excel");
    $("#bZip").onclick = () => bExport("zip");
    $$("#bFilter button").forEach(b => b.onclick = () => {
      B.filter = b.dataset.f;
      $$("#bFilter button").forEach(x => x.classList.toggle("active", x === b));
      bRenderTable();
    });
    bRenderQueue();
    bRenderTable();
  },
  async show(opts = {}) {
    await bLoadTemplates(opts.templateId !== undefined ? opts.templateId : $("#bSchema").value);
    if (opts.templateId) toast(`Batch will use template "${B.template ? B.template.name : opts.templateId}"`, "ok");
  },
});
