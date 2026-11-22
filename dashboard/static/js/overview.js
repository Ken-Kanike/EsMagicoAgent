/* Overview: headline numbers, charts, review queue, recent runs, deliverable outputs. Reads only CLI artefacts. */
"use strict";

const FIELD_KEYS = ["is_invoice", "vendor", "invoice_number", "invoice_date", "currency", "line_items", "tax_total", "total"];
const FIELD_LABELS = ["is_invoice", "vendor", "inv. number", "date", "currency", "line items", "tax", "total"];
const OV = { charts: {} };

if (window.Chart) {
  Chart.defaults.font.family = "'Plus Jakarta Sans', Inter, sans-serif";
  Chart.defaults.color = "#6d6961";
  Chart.defaults.plugins.tooltip.backgroundColor = "rgba(20,17,13,.95)";
  Chart.defaults.plugins.tooltip.borderColor = "rgba(255,255,255,.12)";
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 10;
  Chart.defaults.plugins.tooltip.titleColor = "#f2efe9";
  Chart.defaults.plugins.tooltip.bodyColor = "#a8a39a";
}

function vGradient(ctx, area, from, to) {
  const g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
  g.addColorStop(0, from); g.addColorStop(1, to);
  return g;
}

/** Field accuracy bars (shared with the Evaluation page). */
function accuracyChart(canvas, fieldAccuracy, existing) {
  const data = FIELD_KEYS.map(k => fieldAccuracy ? fieldAccuracy[k] ?? 0 : 0);
  if (existing) { existing.data.datasets[0].data = data; existing.update(); return existing; }
  return new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: { labels: FIELD_LABELS, datasets: [{
      data, borderRadius: 8, borderSkipped: false, maxBarThickness: 26,
      backgroundColor: c => {
        const { chart, raw } = c; const area = chart.chartArea;
        if (!area) return "#ffb547";
        if (raw < 80) return vGradient(chart.ctx, area, "#ff8b8b", "rgba(255,107,107,.15)");
        if (raw < 99.9) return vGradient(chart.ctx, area, "#ffd27a", "rgba(255,198,92,.12)");
        return vGradient(chart.ctx, area, "#ffd48a", "rgba(255,154,31,.12)");
      },
    }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 1100, easing: "easeOutQuart" },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.parsed.y}% correct` } } },
      scales: {
        y: { beginAtZero: true, max: 100, grid: { color: "rgba(255,255,255,.05)" }, border: { display: false }, ticks: { callback: v => v + "%", stepSize: 25 } },
        x: { grid: { display: false }, border: { display: false }, ticks: { color: "#a8a39a", font: { size: 11 } } },
      },
    },
  });
}

function kpiCard({ icon, label, value, delta, deltaKind = "up", spark, sparkColor, foot }) {
  const arrow = deltaKind === "up" ? "trending-up" : deltaKind === "down" ? "trending-down" : "minus";
  return `<div class="card kpi">
    <div class="kpi-row"><div class="kpi-label"><i data-lucide="${icon}"></i>${esc(label)}</div>${delta ? `<span class="delta ${deltaKind}"><i data-lucide="${arrow}"></i>${esc(delta)}</span>` : ""}</div>
    <div class="kpi-value" data-count>${value}</div>
    ${sparkline(spark, sparkColor)}
    <div class="kpi-foot">${foot || ""}</div></div>`;
}

function tlItem({ icon, tone = "", title, sub, meta, attrs = "" }) {
  return `<div class="tl-item ${attrs ? "clickable" : ""}" ${attrs}><div class="tl-icon ${tone}"><i data-lucide="${icon}"></i></div>
    <div class="min-w-0"><div class="tl-title truncate-1">${title}</div><div class="tl-sub">${sub}</div></div>${meta ? `<div class="tl-meta">${meta}</div>` : ""}</div>`;
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

registerPage("overview", {
  title: "Dashboard",
  sub: "Invoice extraction · validation · evaluation",
  async show() {
    $("#ovGreeting").textContent = greeting();
    $("#ovDate").innerHTML = `Today is <b>${new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</b>`;
    $("#ovKpis").innerHTML = Array(4).fill(`<div class="card kpi"><div class="kpi-label skeleton" style="width:60%">loading</div><div class="kpi-value skeleton" style="width:50%">000</div><div class="skeleton" style="height:46px;margin-top:12px"></div></div>`).join("");

    const [o, ev] = await Promise.all([api("/api/overview"), api("/api/eval/latest").catch(() => ({ available: false }))]);
    const e = o.eval;
    const recs = ev.available ? ev.result.document_records : [];
    const perDocCorrect = recs.map(r => Object.values(r.field_matches || {}).filter(Boolean).length);
    const perDocCost = recs.map(r => r.cost_usd || 0);
    const perDocTok = recs.map(r => (r.tokens_in || 0) + (r.tokens_out || 0));
    const evalAgo = e ? timeAgo(e.updated_at) : "";
    const correct = e ? Math.round(e.overall_accuracy * e.total_docs * 8 / 100) : 0;

    $("#ovKpis").innerHTML = [
      kpiCard({ icon: "target", label: "Accuracy", value: e ? `${e.overall_accuracy}%` : "—", delta: e ? `${e.docs_fully_correct}/${e.total_docs}` : "",
        deltaKind: e && e.docs_fully_correct === e.total_docs ? "up" : "flat", spark: perDocCorrect, sparkColor: "#5ee08f", foot: e ? `${correct}/${e.total_docs * 8} fields · eval ${evalAgo}` : "Run python scripts/eval.py" }),
      kpiCard({ icon: "coins", label: "Cost / doc", value: e ? fmtUsd(e.avg_cost_per_doc, 4) : "—", delta: "", deltaKind: "flat",
        spark: perDocCost, sparkColor: "#ffb547", foot: e ? `list price · ${fmtUsd(e.avg_cost_per_doc * 1000, 2)} per 1,000 invoices` : "" }),
      kpiCard({ icon: "zap", label: "Tokens / doc", value: e ? fmtNum((e.total_tokens_in + e.total_tokens_out) / e.total_docs) : "—",
        delta: "", deltaKind: "flat", spark: perDocTok, sparkColor: "#9b7bff",
        foot: e ? `${fmtNum(e.total_tokens_in / e.total_docs)} in · ${fmtNum(e.total_tokens_out / e.total_docs)} out` : "" }),
      kpiCard({ icon: "files", label: "Deliverables", value: `${o.counts.outputs}`, delta: o.review_queue.length ? `${o.review_queue.length} flagged` : "clear",
        deltaKind: o.review_queue.length ? "down" : "up", spark: o.outputs.map(x => x.line_items || 0), sparkColor: "#ff9a1f",
        foot: `${o.counts.invoices} invoices · ${o.counts.non_invoices} non-invoices` }),
    ].join("");
    $$("#ovKpis .kpi-value[data-count]").forEach(el => countUp(el));

    // gauge
    if (e) {
      $("#ovGaugeSub").textContent = evalAgo;
      $("#ovGauge").innerHTML = gaugeHtml(e.overall_accuracy, `${correct} of ${e.total_docs * 8} fields`, [
        { label: "Docs", value: `${e.docs_fully_correct}/${e.total_docs}`, color: "#ff9a1f" },
        { label: "Rows P", value: fmtPct(e.line_item_row_precision, 0), color: "#ffd48a" },
        { label: "Rows R", value: fmtPct(e.line_item_row_recall, 0), color: "#9b7bff" },
      ]);
      animateGauges($("#ovGauge"));
    } else $("#ovGauge").innerHTML = `<div class="empty">No evaluation yet</div>`;

    // tokens per document (smooth lines)
    const labels = recs.map(r => r.doc_id);
    const lineCanvas = $("#ovLine");
    if (OV.charts.line) OV.charts.line.destroy();
    OV.charts.line = new Chart(lineCanvas.getContext("2d"), {
      type: "line",
      data: { labels, datasets: [
        { label: "Input tokens", data: recs.map(r => r.tokens_in), borderColor: "#9b7bff", borderWidth: 2.2, tension: 0.42, pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: "#9b7bff", fill: true,
          backgroundColor: c => c.chart.chartArea ? vGradient(c.chart.ctx, c.chart.chartArea, "rgba(155,123,255,.28)", "rgba(155,123,255,0)") : "transparent" },
        { label: "Output tokens", data: recs.map(r => r.tokens_out), borderColor: "#ffb547", borderWidth: 2.2, tension: 0.42, pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: "#ffb547", fill: true,
          backgroundColor: c => c.chart.chartArea ? vGradient(c.chart.ctx, c.chart.chartArea, "rgba(255,181,71,.22)", "rgba(255,181,71,0)") : "transparent" },
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, layout: { padding: { left: 4, top: 6 } },
        animation: { duration: 1300, easing: "easeOutQuart" },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${fmtNum(c.parsed.y)}` } } },
        scales: { y: { beginAtZero: true, grid: { color: "rgba(255,255,255,.05)" }, border: { display: false }, ticks: { maxTicksLimit: 5 } },
          x: { grid: { display: false }, border: { display: false }, ticks: { color: "#a8a39a" } } },
      },
    });

    // field accuracy + cost per doc
    OV.charts.acc = accuracyChart($("#ovChart"), e && e.field_accuracy, OV.charts.acc);
    $("#ovCostSub").textContent = e ? `avg ${fmtUsd(e.avg_cost_per_doc, 4)}` : "";
    if (OV.charts.cost) OV.charts.cost.destroy();
    OV.charts.cost = new Chart($("#ovCost").getContext("2d"), {
      type: "bar",
      data: { labels, datasets: [{ data: perDocCost, borderRadius: 8, borderSkipped: false, maxBarThickness: 22,
        backgroundColor: c => c.chart.chartArea ? vGradient(c.chart.ctx, c.chart.chartArea, "#b9a2ff", "rgba(155,123,255,.12)") : "#9b7bff" }] },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 1100, easing: "easeOutQuart" },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${fmtUsd(c.parsed.y)} · ${recs[c.dataIndex].calls} call(s)` } } },
        scales: { y: { beginAtZero: true, grid: { color: "rgba(255,255,255,.05)" }, border: { display: false }, ticks: { maxTicksLimit: 5, callback: v => "$" + Number(v).toFixed(3) } },
          x: { grid: { display: false }, border: { display: false }, ticks: { color: "#a8a39a" } } } },
    });

    // review queue
    const badge = $("#navReviewCount");
    badge.textContent = o.review_queue.length;
    badge.classList.toggle("hidden", !o.review_queue.length);
    $("#ovQueueCount").textContent = o.review_queue.length;
    $("#ovQueueCount").className = `badge ${o.review_queue.length ? "badge-warn" : "badge-ok"}`;
    $("#ovQueue").innerHTML = o.review_queue.length ? o.review_queue.map((q, i) => tlItem({
      icon: q.error ? "x-octagon" : "alert-triangle", tone: "warn", title: `${esc(q.doc_id)} · ${esc(q.source)}`,
      sub: esc((q.error || q.reasons.join(" · ")).slice(0, 140)), meta: `<i data-lucide="arrow-up-right" style="width:14px;height:14px"></i>`, attrs: `data-q="${i}"`,
    })).join("") : `<div class="empty" style="padding:16px"><i data-lucide="check-circle-2"></i>Nothing flagged in the last runs</div>`;
    $$("#ovQueue [data-q]").forEach(el => el.onclick = async () => {
      const q = o.review_queue[+el.dataset.q];
      const saved = await api(`/api/documents/${q.doc_id}/output`).catch(() => null);
      previewInvoiceResult({ filename: q.file, doc_id: q.doc_id, data: saved && saved.data, needs_review: !q.error, review_reasons: q.reasons, error: q.error }, q.doc_id);
    });

    // recent runs
    const runs = [];
    if (o.runs.eval) runs.push(tlItem({ icon: "chart-no-axes-combined", tone: "ok", title: "Labelled evaluation",
      sub: `${o.runs.eval.documents} docs · ${fmtUsd(o.runs.eval.cost_usd, 4)} · ${o.runs.eval.needs_review} flagged`, meta: timeAgo(o.runs.eval.updated_at), attrs: `data-nav="evaluation"` }));
    if (o.runs.batch) runs.push(tlItem({ icon: "layers", title: "Batch · unlabelled set",
      sub: `${o.runs.batch.documents} docs · ${fmtUsd(o.runs.batch.cost_usd, 4)} · ${o.runs.batch.needs_review} flagged`, meta: timeAgo(o.runs.batch.updated_at), attrs: `data-nav="batch"` }));
    runs.push(tlItem({ icon: "scan-line", title: "Custom templates", sub: `${o.counts.templates} saved · usable in batch and over MCP`, attrs: `data-nav="templates"` }));
    runs.push(tlItem({ icon: "plug", title: "MCP server", sub: "6 tools · stdio · copy a setup prompt", attrs: `data-nav="mcp"` }));
    $("#ovRuns").innerHTML = runs.join("");
    $$("#ovRuns [data-nav]").forEach(el => el.onclick = () => navigate(el.dataset.nav));

    // outputs table
    const flagged = new Set(o.review_queue.map(q => q.doc_id));
    $("#ovOutputs").innerHTML = o.outputs.map(r => `<tr class="clickable" data-id="${esc(r.doc_id)}">
      <td class="mono amber">${esc(r.doc_id)}</td>
      <td>${r.error ? '<span class="badge badge-err">error</span>' : r.is_invoice ? '<span class="badge badge-info">invoice</span>' : '<span class="badge badge-muted">not invoice</span>'}
          ${flagged.has(r.doc_id.toUpperCase()) ? '<span class="badge badge-warn">review</span>' : ""}</td>
      <td class="truncate-1" style="max-width:260px;font-weight:600">${esc(r.vendor || "—")}</td>
      <td class="mono">${esc(r.invoice_number || "—")}</td><td class="mono muted">${esc(r.invoice_date || "—")}</td>
      <td class="num">${r.is_invoice ? r.line_items : "—"}</td><td class="num">${r.is_invoice ? fmtMoney(r.total, r.currency) : "—"}</td>
      <td class="center">${r.balanced === true ? '<span class="tick">✓</span>' : r.balanced === false ? '<span class="cross">✗</span>' : '<span class="muted">—</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="8"><div class="empty">No outputs yet. Run <span class="mono">python scripts/batch.py</span>.</div></td></tr>`;
    $$("#ovOutputs tr[data-id]").forEach(tr => tr.onclick = () => navigate("workspace", { docId: tr.dataset.id.toUpperCase() }));
  },
});
