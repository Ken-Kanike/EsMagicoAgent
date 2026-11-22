/* MCP & agents: connect a client to scripts/mcp_server.py and try every tool live. */
"use strict";

const M = { tools: [], config: null, client: "claude_code", docs: [], templates: [] };

const CLIENT_HINTS = {
  agent_prompt: "Paste this into the agent chat of any IDE (Claude Code, Cursor, Windsurf, VS Code, Zed…). The agent installs the server in its own config, starts it and checks the tools.",
  claude_code: "Run once in a terminal. The server starts on demand over stdio. Check it with: claude mcp list",
  claude_desktop: "Paste into claude_desktop_config.json (Settings → Developer → Edit config), then restart Claude Desktop.",
  cursor: "Paste into ~/.cursor/mcp.json (all projects) or .cursor/mcp.json (this project), then reload Cursor.",
  vscode: "Paste into .vscode/mcp.json in your workspace (VS Code 1.99+ agent mode), then start the server from the file's code lens.",
  inspector: "Opens the official MCP Inspector in your browser to list and call the tools by hand.",
};

/** Server launch details, taken from /api/mcp/config so the paths are this machine's. */
function mcpServerSpec() {
  const s = M.config && M.config.claude_desktop && M.config.claude_desktop.mcpServers && M.config.claude_desktop.mcpServers["invoice-pipeline"];
  return s || { command: "python", args: ["scripts/mcp_server.py"] };
}

function mcpSetupPrompt() {
  const { command, args } = mcpServerSpec();
  const script = args[0] || "scripts/mcp_server.py";
  const root = script.replace(/[\\/]scripts[\\/]mcp_server\.py$/, "");
  const sep = script.includes("\\") ? "\\" : "/";
  const toolNames = M.tools.map(t => t.name).join(", ");
  const block = JSON.stringify({ mcpServers: { "invoice-pipeline": { command, args } } }, null, 2);
  return `Set up the "invoice-pipeline" MCP server in this editor for me, then verify it works.

Server
- Name: invoice-pipeline
- Transport: stdio (the client starts the process itself; there is no URL or port)
- Command: ${command}
- Args: ${JSON.stringify(args)}
- Project folder: ${root}
- Python packages: ${root}${sep}requirements.txt (install with: "${command}" -m pip install -r "${root}${sep}requirements.txt" if imports fail)
- Extraction tools need a Groq key in ${root}${sep}.env (GROQ_API_KEY_1=...). Never print, copy or commit that file.

Steps
1. Work out which client you are running in and use its own MCP configuration. Merge into the existing file and keep every other server:
   - Claude Code: claude mcp add --scope user invoice-pipeline -- "${command}" "${script}"
   - Cursor: ~/.cursor/mcp.json under "mcpServers"
   - Windsurf: ~/.codeium/windsurf/mcp_config.json under "mcpServers"
   - VS Code (Copilot agent mode): .vscode/mcp.json under "servers", with "type": "stdio"
   - Claude Desktop: claude_desktop_config.json under "mcpServers" (Windows: %APPDATA%\\Claude, macOS: ~/Library/Application Support/Claude); tell me to restart it
   - Any other client: its documented stdio MCP config, with the same command and args
2. Check that the command and the script path exist, then run: "${command}" "${script}" --print-config
   It should print a JSON config and exit. If it fails, install the requirements (above) and try again.
3. Reload the MCP servers and list the tools. Expect these ${M.tools.length}: ${toolNames}.
4. Smoke test: call list_documents, then get_latest_evaluation. Do not call extract_invoice or extract_with_template unless I ask, because they spend API credits.
5. Tell me which file you changed and what the smoke test returned.

Config block (for clients that use "mcpServers"):
${block}`;
}

function mcpShowClient(name) {
  M.client = name;
  $$("#mcpClientTabs .tab").forEach(t => t.classList.toggle("active", t.dataset.client === name));
  let v;
  if (name === "agent_prompt") v = mcpSetupPrompt();
  else if (name === "vscode") { const { command, args } = mcpServerSpec(); v = { servers: { "invoice-pipeline": { type: "stdio", command, args } } }; }
  else v = M.config ? M.config[name] : "";
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
    $("#mcpCopy").onclick = () => copyText($("#mcpConfig").textContent, "Copied");
    $("#mcpPromptBtn").onclick = () => { mcpShowClient("agent_prompt"); copyText(mcpSetupPrompt(), "Setup prompt copied. Paste it into your IDE's agent chat."); };
    mcpShowClient(M.client);
    mcpSelectTool();
  },
});
