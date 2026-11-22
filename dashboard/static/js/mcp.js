/* MCP & agents: connect a client to scripts/mcp_server.py and try every tool live. */
"use strict";

const M = { tools: [], config: null, client: "claude_code", docs: [], templates: [] };

const CLIENT_HINTS = {
  claude_code: "Run once in a terminal. The server starts on demand over stdio; check it with  claude mcp list.",
  claude_desktop: "Paste into claude_desktop_config.json (Settings → Developer → Edit config), then restart Claude Desktop.",
  cursor: "Paste into ~/.cursor/mcp.json (or .cursor/mcp.json in a project) and reload Cursor.",
  inspector: "Opens the official MCP Inspector in your browser to list and call the tools interactively.",
};

function mcpShowClient(name) {
  M.client = name;
  $$("#mcpClientTabs .tab").forEach(t => t.classList.toggle("active", t.dataset.client === name));
  const v = M.config ? M.config[name] : "";
  $("#mcpConfig").textContent = typeof v === "string" ? v : JSON.stringify(v, null, 2);
  $("#mcpConfig").classList.toggle("wrap", typeof v === "string");
  $("#mcpClientHint").textContent = CLIENT_HINTS[name] || "";
}

function mcpField(name, schema, required) {
  const label = `<span class="label">${esc(name)}${required ? ' <span class="err">*</span>' : ""} <span class="muted mono">${esc(schema.type || "")}</span></span>`;
  const desc = schema.description ? `<div class="hint mt-1">${esc(schema.description)}</div>` : "";
  if (name === "doc_id") {
    return `<div>${label}<select class="select" data-arg="doc_id">${M.docs.map(d => `<option value="${esc(d.doc_id)}">${esc(d.doc_id)} · ${esc(d.category)}${d.has_ground_truth ? " · GT" : ""}</option>`).join("")}</select>${desc}</div>`;
  }
  if (name === "template_id") {
    return `<div>${label}<select class="select" data-arg="template_id">${M.templates.length ? M.templates.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("") : '<option value="">(no templates saved)</option>'}</select>${desc}</div>`;
  }
  if (schema.enum) {
    return `<div>${label}<select class="select" data-arg="${esc(name)}">${required ? "" : '<option value="">(default)</option>'}${schema.enum.map(v => `<option ${name === "mode" && v === currentMode() ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>${desc}</div>`;
  }
  if (schema.type === "object" || schema.type === "array") {
    const example = name === "data" ? JSON.stringify({ is_invoice: true, vendor: "Acme Supplies Pvt Ltd", invoice_number: "INV-2041", invoice_date: "2026-03-14", currency: "INR",
      line_items: [{ description: "A4 paper, 500 sheets", quantity: 10, amount: 3200.0 }], tax_total: 576.0, total: 3776.0 }, null, 2) : "{}";
    return `<div>${label}<textarea class="textarea" rows="9" data-arg="${esc(name)}" data-json="1">${esc(example)}</textarea>${desc}</div>`;
  }
  return `<div>${label}<input class="input" data-arg="${esc(name)}">${desc}</div>`;
}

function mcpSelectTool() {
  const t = M.tools.find(x => x.name === $("#mcpTool").value);
  if (!t) return;
  $("#mcpToolDesc").textContent = t.description;
  const props = (t.inputSchema && t.inputSchema.properties) || {};
  const req = new Set((t.inputSchema && t.inputSchema.required) || []);
  $("#mcpForm").innerHTML = Object.keys(props).length ? Object.entries(props).map(([k, s]) => mcpField(k, s, req.has(k))).join("")
    : `<div class="hint">This tool takes no arguments.</div>`;
}

function mcpArgs() {
  const args = {};
  for (const el of $$("#mcpForm [data-arg]")) {
    const v = el.value;
    if (v === "" || v === undefined) continue;
    if (el.dataset.json) {
      try { args[el.dataset.arg] = JSON.parse(v); } catch { throw new Error(`"${el.dataset.arg}" is not valid JSON`); }
    } else args[el.dataset.arg] = v;
  }
  return args;
}

async function mcpRun() {
  let args;
  try { args = mcpArgs(); } catch (e) { return toast(e.message, "warn"); }
  const tool = $("#mcpTool").value;
  const btn = $("#mcpRun");
  btn.disabled = true; btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i>Calling…`; icons();
  $("#mcpResult").textContent = `→ tools/call ${tool} ${JSON.stringify(args)}\n…`;
  $("#mcpElapsed").textContent = "";
  try {
    const r = await api("/api/mcp/call", { body: { tool, arguments: args } });
    $("#mcpResult").textContent = JSON.stringify(r.result, null, 2);
    $("#mcpElapsed").textContent = `${r.elapsed_ms} ms`;
  } catch (e) {
    $("#mcpResult").textContent = `Error: ${e.message}`;
  } finally { btn.disabled = false; btn.innerHTML = `<i data-lucide="play"></i>Call tool`; icons(); }
}

registerPage("mcp", {
  title: "MCP & agents",
  sub: "The pipeline as Model Context Protocol tools for Claude Code, Claude Desktop, Cursor and other agents",
  async init() {
    const [tools, config, docs, tmpl] = await Promise.all([
      api("/api/mcp/tools"), api("/api/mcp/config"),
      api("/api/mcp/call", { body: { tool: "list_documents", arguments: {} } }).catch(() => ({ result: { documents: [] } })),
      api("/api/templates/list").catch(() => ({ templates: [] })),
    ]);
    M.tools = tools.tools || []; M.config = config; M.docs = docs.result.documents || []; M.templates = tmpl.templates || [];

    const tile = (icon, label, value, foot) => `<div class="card kpi"><div class="kpi-label"><i data-lucide="${icon}"></i>${label}</div><div class="kpi-value" style="font-size:18px">${value}</div><div class="kpi-foot">${foot}</div></div>`;
    $("#mcpKpis").innerHTML = [
      tile("server", "Server", esc(tools.server), `<span class="mono">python scripts/mcp_server.py</span>`),
      tile("cable", "Transport", esc(tools.transport), "launched by the client; no port to open"),
      tile("wrench", "Tools", M.tools.length, "same functions as this playground"),
      tile("shield-check", "Safety", "doc_id only over HTTP", "local MCP clients may also pass a file path"),
    ].join("");

    $("#mcpToolCount").textContent = `${M.tools.length} tools`;
    $("#mcpTools").innerHTML = M.tools.map(t => {
      const props = Object.keys((t.inputSchema && t.inputSchema.properties) || {});
      const req = new Set((t.inputSchema && t.inputSchema.required) || []);
      return `<div class="field" style="cursor:pointer" data-tool="${esc(t.name)}"><div class="flex items-center justify-between gap-2">
        <span class="mono" style="font-weight:600;color:#c7d4ff">${esc(t.name)}</span>
        <span class="flex gap-1 flex-wrap justify-end">${props.map(p => `<span class="badge ${req.has(p) ? "badge-info" : "badge-muted"} mono">${esc(p)}</span>`).join("")}</span></div>
        <div class="hint mt-1">${esc(t.description)}</div></div>`;
    }).join("");
    $$("#mcpTools [data-tool]").forEach(el => el.onclick = () => { $("#mcpTool").value = el.dataset.tool; mcpSelectTool(); $("#mcpTool").scrollIntoView({ behavior: "smooth", block: "center" }); });

    $("#mcpTool").innerHTML = M.tools.map(t => `<option>${esc(t.name)}</option>`).join("");
    $("#mcpTool").onchange = mcpSelectTool;
    $("#mcpRun").onclick = mcpRun;
    $("#mcpCurl").onclick = () => {
      let args; try { args = mcpArgs(); } catch (e) { return toast(e.message, "warn"); }
      copyText(`curl -s -X POST ${location.origin}/api/mcp/call -H "Content-Type: application/json" -d '${JSON.stringify({ tool: $("#mcpTool").value, arguments: args })}'`, "curl command copied");
    };
    $$("#mcpClientTabs .tab").forEach(t => t.onclick = () => mcpShowClient(t.dataset.client));
    $("#mcpCopy").onclick = () => copyText($("#mcpConfig").textContent, "Configuration copied");
    mcpShowClient(M.client);
    mcpSelectTool();
  },
});
