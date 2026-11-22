/* Evaluation: labelled-set accuracy, per-document matrix, error groups, needs_review check, cost. */
"use strict";

let evChart = null;
let EV = null;

function evRender(s) {
  EV = s;
  const fieldsTotal = s.total_docs * 8;
  const correct = Object.values(s.field_correct_counts || {}).reduce((a, b) => a + b, 0);
  $("#evMeta").innerHTML = `Backend <span class="mono">${esc(s.mode)}</span> · ${s.total_docs} documents · ${s.wall_time_s}s wall time · same harness as <span class="mono">python scripts/eval.py</span>`;
  const tile = (icon, label, value, foot = "", tone = "") => `<div class="card kpi"><div class="kpi-label"><i data-lucide="${icon}"></i>${label}</div><div class="kpi-value ${tone}">${value}</div><div class="kpi-foot">${foot}</div></div>`;
  $("#evKpis").innerHTML = [
    tile("target", "Field accuracy", `${s.overall_accuracy}%`, `${correct} / ${fieldsTotal} fields`, s.overall_accuracy >= 95 ? "ok" : s.overall_accuracy >= 80 ? "warn" : "err"),
    tile("file-check-2", "Docs fully correct", `${s.docs_fully_correct} / ${s.total_docs}`),
    tile("rows-3", "Line-item rows", `${fmtPct(s.line_item_row_recall)}`, `precision ${fmtPct(s.line_item_row_precision)} · recall ${fmtPct(s.line_item_row_recall)}`),
    tile("coins", "Cost per document", fmtUsd(s.avg_cost_per_doc, 4), `${fmtUsd(s.total_cost_usd, 4)} for ${s.total_docs} docs`),
    tile("arrow-left-right", "Avg tokens", `${fmtNum(s.total_tokens_in / s.total_docs)} / ${fmtNum(s.total_tokens_out / s.total_docs)}`, "in / out per document"),
  ].join("");

  evChart = accuracyChart($("#evChart"), s.field_accuracy, evChart);

  const rv = s.review || {};
  const cell = (n, tone = "") => `<td class="center ${n ? tone : ""}" style="font-size:18px;font-weight:650">${n ?? 0}</td>`;
  $("#evReview").innerHTML = `<div class="card table-wrap"><table class="table"><thead><tr><th></th><th class="center">has errors</th><th class="center">no errors</th></tr></thead><tbody>
      <tr><td>flagged</td>${cell(rv.true_positive, "ok")}${cell(rv.false_positive, "warn")}</tr>
      <tr><td>not flagged</td>${cell(rv.false_negative, "err")}${cell(rv.true_negative)}</tr></tbody></table></div>
    <div class="grid gap-1 mt-3 text-2" style="font-size:12px">
      <div>Flag precision: <b>${rv.precision ?? "n/a"}</b> · recall: <b>${rv.recall ?? "n/a"}</b></div>
      <div>Field errors inside flagged documents: <b>${rv.error_fields_in_flagged_docs ?? 0}</b> of ${rv.error_fields_total ?? 0}</div>
      <div class="hint mt-1">${rv.docs_with_errors ? "" : "No labelled document has an error in this run, so the flag cannot be scored on this set. See REPORT.md for the flag checked on the rule baseline and on the unlabelled set."}</div>
    </div>`;

  const mark = v => v ? '<span class="tick">✓</span>' : '<span class="cross">✗</span>';
  $("#evMatrix").innerHTML = s.document_records.map((r, i) => {
    const m = r.field_matches || {};
    return `<tr class="clickable" data-i="${i}"><td class="mono">${esc(r.doc_id)}</td>
      ${["is_invoice", "vendor", "invoice_number", "invoice_date", "currency", "line_items", "tax_total", "total"].map(k => `<td class="center">${mark(m[k])}</td>`).join("")}
      <td class="center">${r.error ? '<span class="badge badge-err">error</span>' : r.needs_review ? '<span class="badge badge-warn">flag</span>' : '<span class="muted">—</span>'}</td>
      <td class="num">${fmtNum(r.tokens_in)} / ${fmtNum(r.tokens_out)}</td><td class="num">${fmtUsd(r.cost_usd)}</td><td class="num">${(r.elapsed_s || 0).toFixed(1)}</td></tr>`;
  }).join("");
  $$("#evMatrix tr[data-i]").forEach(tr => tr.onclick = () => evPreview(s.document_records[+tr.dataset.i]));

  const groups = Object.entries(s.error_groups || {});
  $("#evErrors").innerHTML = groups.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Field: cause</th><th class="num">Count</th><th>Documents</th></tr></thead><tbody>
    ${groups.sort((a, b) => b[1].length - a[1].length).map(([k, docs]) => `<tr><td>${esc(k)}</td><td class="num">${docs.length}</td><td class="mono">${esc(docs.join(", "))}</td></tr>`).join("")}
    </tbody></table></div>` : `<div class="empty"><i data-lucide="party-popper"></i>No field errors on the labelled set in this run.</div>`;

  const pr = Object.entries(s.pricing || {});
  $("#evCost").innerHTML = `<div class="text-2" style="font-size:12.5px;line-height:1.6">For every API call: <span class="mono">prompt_tokens × input price + completion_tokens × output price</span>, using the token counts the API returns (corrective retries included), summed per document. Free-tier usage is billed $0; these are list prices a paid account would pay.</div>
    ${pr.length ? `<div class="card table-wrap mt-3"><table class="table"><thead><tr><th>Model</th><th class="num">$ / 1M in</th><th class="num">$ / 1M out</th><th>Source</th></tr></thead><tbody>
    ${pr.map(([m, p]) => `<tr><td class="mono">${esc(m)}</td><td class="num">${(p.input_per_1k * 1000).toFixed(3)}</td><td class="num">${(p.output_per_1k * 1000).toFixed(3)}</td><td class="muted">${esc(p.source || "")}</td></tr>`).join("")}
    </tbody></table></div>` : `<div class="hint mt-2">No priced model calls in this run (rule baseline).</div>`}`;
  icons();
}

function evPreview(r) {
  const p = r.predicted || {};
  const g = r.ground_truth || {};
  const m = r.field_matches || {};
  const errs = Object.entries(r.errors || {});
  openPreview({
    title: `${r.doc_id} · ${r.file_name}`,
    subtitle: `${r.calls} call(s) · ${fmtNum(r.tokens_in)} in / ${fmtNum(r.tokens_out)} out · ${fmtUsd(r.cost_usd)}`,
    docId: r.doc_id,
    badges: [errs.length ? `<span class="badge badge-err">${errs.length} field error(s)</span>` : `<span class="badge badge-ok">all fields correct</span>`, r.needs_review ? '<span class="badge badge-warn">flagged</span>' : ""],
    banner: r.error ? { kind: "err", title: r.error } : errs.length ? { kind: "warn", title: "Mismatches (cause tags from eval/metrics.py)", items: errs.map(([f, c]) => `${f}: ${c}`) }
      : r.issues && r.issues.length ? { kind: "muted", title: "Validator notes", items: r.issues } : null,
    fields: [{ label: "is_invoice", value: p.is_invoice, gt: g.is_invoice, match: m.is_invoice }, ...invoiceFields(p, g, m)],
    extraHtml: `<div class="grid gap-3" style="grid-template-columns:1fr 1fr"><div><div class="label">Predicted rows ${m.line_items ? '<span class="tick">✓</span>' : '<span class="cross">✗</span>'}</div>${lineItemsTable(p.line_items, p.currency)}</div>
      <div><div class="label">Ground-truth rows</div>${lineItemsTable(g.line_items, g.currency)}</div></div>`,
    json: { predicted: p, ground_truth: g },
  });
}

async function evRun() {
  const mode = currentMode();
  const ok = await confirmDialog("Run the labelled-set evaluation?",
    `Backend: ${mode}. This calls the model for up to 10 documents (≈$0.02 at list price on Groq; free tier bills $0) and rewrites reports/accuracy_table.md and reports/eval_results.json with this run.`, "Run evaluation");
  if (!ok) return;
  const btn = $("#evRun");
  btn.disabled = true;
  try {
    const { job_id } = await api(`/api/eval/jobs?mode=${encodeURIComponent(mode)}&cache=${$("#evCache").checked}`, { method: "POST" });
    $("#evBanner").innerHTML = bannerHtml("info", "Evaluation running… the Groq free tier is rate-limited, so a fresh run takes 2-3 minutes.");
    icons();
    const job = await pollJob(job_id, j => { btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i>Running · ${j.elapsed_s}s`; icons(); }, 2000);
    $("#evBanner").innerHTML = "";
    evRender(job.result);
    toast(`Evaluation finished: ${job.result.overall_accuracy}% field accuracy`, "ok");
  } catch (e) {
    $("#evBanner").innerHTML = bannerHtml("err", `Evaluation failed: ${e.message}`); icons();
  } finally { btn.disabled = false; btn.innerHTML = `<i data-lucide="play"></i>Run evaluation`; icons(); }
}

registerPage("evaluation", {
  title: "Evaluation",
  sub: "Field-by-field accuracy against the 10 labelled documents, with cost and error causes",
  init() { $("#evRun").onclick = evRun; },
  async show() {
    const r = await api("/api/eval/latest");
    if (r.available) evRender(r.result);
    else $("#evBanner").innerHTML = bannerHtml("muted", "No evaluation yet. Run one here or with: python scripts/eval.py");
    icons();
  },
});
