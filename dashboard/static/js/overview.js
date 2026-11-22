/* Overview: headline numbers, review queue, deliverable outputs. Reads only CLI artefacts. */
"use strict";

const FIELD_KEYS = ["is_invoice", "vendor", "invoice_number", "invoice_date", "currency", "line_items", "tax_total", "total"];
const FIELD_LABELS = ["is_invoice", "vendor", "inv. number", "date", "currency", "line items", "tax", "total"];
let ovChart = null;

function kpi(icon, label, value, foot, tone = "") {
  return `<div class="card kpi"><div class="kpi-label"><i data-lucide="${icon}"></i>${esc(label)}</div>
    <div class="kpi-value ${tone}">${value}</div><div class="kpi-foot">${foot || ""}</div></div>`;
}

function accuracyChart(canvas, fieldAccuracy, existing) {
  const data = FIELD_KEYS.map(k => fieldAccuracy ? fieldAccuracy[k] ?? 0 : 0);
  if (existing) { existing.data.datasets[0].data = data; existing.update(); return existing; }
  return new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: { labels: FIELD_LABELS, datasets: [{ data, backgroundColor: data.map(v => v >= 99.9 ? "#d4d4d4" : v >= 80 ? "#fbbf24" : "#f87171"), borderRadius: 3, maxBarThickness: 22 }] },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.parsed.y}%` } } },
      scales: { y: { beginAtZero: true, max: 100, grid: { color: "#161616" }, border: { color: "#2b2b2b" }, ticks: { color: "#666666", callback: v => v + "%" } },
        x: { grid: { display: false }, ticks: { color: "#a0a0a0", font: { size: 11, family: "Inter" } } } },
    },
  });
}

registerPage("overview", {
  title: "Overview",
  sub: "Measured accuracy, cost and what needs a human, from the last CLI runs",
  async show() {
    $("#ovKpis").innerHTML = Array(5).fill(`<div class="card kpi"><div class="kpi-label skeleton">loading</div><div class="kpi-value skeleton">00.0%</div></div>`).join("");
    const o = await api("/api/overview");
    const e = o.eval;
    const batch = o.runs.batch;
    const correctFields = e ? Math.round(e.overall_accuracy * e.total_docs * 8 / 100) : 0;
    $("#ovKpis").innerHTML = [
      e ? kpi("target", "Field accuracy · labelled", `${e.overall_accuracy}%`, `${correctFields}/${e.total_docs * 8} fields · ${e.docs_fully_correct}/${e.total_docs} docs fully correct`, "ok")
        : kpi("target", "Field accuracy · labelled", "—", "Run python scripts/eval.py"),
      e ? kpi("coins", "Cost per document", fmtUsd(e.avg_cost_per_doc, 4), `list price · ${fmtNum(e.total_tokens_in / e.total_docs)} in / ${fmtNum(e.total_tokens_out / e.total_docs)} out tokens`)
        : kpi("coins", "Cost per document", "—", ""),
      kpi("files", "Deliverable outputs", `${o.counts.outputs}`, `${o.counts.invoices} invoices · ${o.counts.non_invoices} non-invoices`),
      kpi("inbox", "Review queue", `${o.review_queue.length}`, o.review_queue.length ? "flagged by validation" : "nothing flagged", o.review_queue.length ? "warn" : "ok"),
      kpi("timer", "Last batch", batch ? `${batch.documents} docs` : "—", batch ? `${fmtUsd(batch.cost_usd, 4)} · ${timeAgo(batch.updated_at)}` : "python scripts/batch.py <folder>"),
    ].join("");

    const badge = $("#navReviewCount");
    badge.textContent = o.review_queue.length;
    badge.classList.toggle("hidden", !o.review_queue.length);

    $("#ovQueueSub").textContent = o.review_queue.length ? `${o.review_queue.length} document(s)` : "";
    $("#ovQueue").innerHTML = o.review_queue.length ? `<div class="table-wrap"><table class="table">
      <thead><tr><th>Doc</th><th>Source</th><th>Why it was flagged</th><th></th></tr></thead><tbody>
      ${o.review_queue.map((q, i) => `<tr class="clickable" data-q="${i}"><td class="mono">${esc(q.doc_id)}</td>
        <td><span class="badge badge-muted">${esc(q.source)}</span></td>
        <td style="max-width:520px">${q.error ? `<span class="err">${esc(q.error)}</span>` : esc(q.reasons.join(" · "))}</td>
        <td><button class="btn btn-sm btn-ghost">Open<i data-lucide="arrow-right"></i></button></td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty"><i data-lucide="check-circle-2"></i>No document needs review in the last batch and eval runs.</div>`;
    $$("#ovQueue tr[data-q]").forEach(tr => tr.onclick = async () => {
      const q = o.review_queue[+tr.dataset.q];
      let saved = null;
      try { saved = await api(`/api/documents/${q.doc_id}/output`); } catch { /* none */ }
      previewInvoiceResult({ filename: q.file, doc_id: q.doc_id, data: saved && saved.data, needs_review: !q.error, review_reasons: q.reasons, error: q.error }, q.doc_id);
    });

    ovChart = accuracyChart($("#ovChart"), e && e.field_accuracy, ovChart);

    const flagged = new Set(o.review_queue.map(q => q.doc_id));
    $("#ovOutputs").innerHTML = o.outputs.map(r => `<tr class="clickable" data-id="${esc(r.doc_id)}">
      <td class="mono">${esc(r.doc_id)}</td>
      <td>${r.error ? '<span class="badge badge-err">error</span>' : r.is_invoice ? '<span class="badge badge-info">invoice</span>' : '<span class="badge badge-muted">not invoice</span>'}
          ${flagged.has(r.doc_id.toUpperCase()) ? '<span class="badge badge-warn">review</span>' : ""}</td>
      <td class="truncate-1" style="max-width:240px">${esc(r.vendor || "—")}</td>
      <td class="mono">${esc(r.invoice_number || "—")}</td><td class="mono">${esc(r.invoice_date || "—")}</td>
      <td class="num">${r.is_invoice ? r.line_items : "—"}</td><td class="num">${r.is_invoice ? fmtMoney(r.total, r.currency) : "—"}</td>
      <td class="center">${r.balanced === true ? '<span class="tick">✓</span>' : r.balanced === false ? '<span class="cross">✗</span>' : '<span class="muted">—</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="8"><div class="empty">No outputs yet. Run <span class="mono">python scripts/batch.py</span>.</div></td></tr>`;
    $$("#ovOutputs tr[data-id]").forEach(tr => tr.onclick = () => navigate("workspace", { docId: tr.dataset.id.toUpperCase() }));
  },
});
