/* Settings: backend selection, provider keys with live connection tests, PII shield. */
"use strict";

function sProviderCard(id, icon, title, status, body, note) {
  return `<div class="card"><div class="card-head"><div class="card-title"><i data-lucide="${icon}"></i>${esc(title)} ${status}</div>
    <button class="btn btn-sm" data-test="${id}"><i data-lucide="activity"></i>Test connection</button></div>
    <div class="card-pad grid gap-3">${body}${note ? `<div class="hint">${note}</div>` : ""}<div class="mono" style="font-size:11.5px" id="sTest-${id}"></div></div></div>`;
}
const sInput = (id, label, placeholder = "", value = "", type = "password") =>
  `<div><span class="label mono">${esc(label)}</span><input id="${id}" class="input mono" type="${type}" placeholder="${esc(placeholder)}" value="${esc(value)}" autocomplete="off"></div>`;
const sStatus = ok => ok ? '<span class="badge badge-ok">configured</span>' : '<span class="badge badge-muted">not set</span>';

async function sLoad() {
  const k = await api("/api/settings/keys");
  $("#sMode").innerHTML = k.valid_modes.map(m => `<option ${m === k.active_mode ? "selected" : ""}>${esc(m)}</option>`).join("");
  $("#sProviders").innerHTML = [
    sProviderCard("groq", "zap", "Groq", sStatus(k.groq.keys_count),
      `<div class="grid gap-3" style="grid-template-columns:1fr 1fr">${[1, 2, 3, 4].map(i => sInput(`sGroq${i}`, `GROQ_API_KEY_${i}`, k.groq.keys_masked[i - 1] || "gsk_…")).join("")}</div>
       <div class="flex flex-wrap gap-2"><span class="badge badge-muted">vision: ${esc(k.groq.vision_model)}</span><span class="badge badge-muted">text: ${esc(k.groq.text_model)}</span></div>`,
      esc(k.groq.note) + " Leave a box empty to keep the current key."),
    sProviderCard("openai", "bot", "OpenAI-compatible", sStatus(k.openai.configured),
      `<div class="grid gap-3" style="grid-template-columns:1fr 1fr">${sInput("sOpenAIKey", "OPENAI_API_KEY", k.openai.masked || "sk-…")}${sInput("sOpenAIBase", "OPENAI_BASE_URL", k.openai.base_url, "", "text")}</div>
       <span class="badge badge-muted">model: ${esc(k.openai.model)}</span>`),
    sProviderCard("gemini", "sparkles", "Google Gemini", sStatus(k.gemini.configured),
      `${sInput("sGeminiKey", "GEMINI_API_KEY", k.gemini.masked || "AIza…")}<span class="badge badge-muted">model: ${esc(k.gemini.model)}</span>`),
    sProviderCard("local", "server", "Local LLM (Ollama / LM Studio)", `<span class="badge badge-muted">${k.local.vision_enabled ? "vision on" : "text only"}</span>`,
      `<div class="grid gap-3" style="grid-template-columns:1fr 1fr">${sInput("sLocalUrl", "LOCAL_LLM_BASE_URL", "", k.local.base_url, "text")}${sInput("sLocalModel", "LOCAL_LLM_MODEL", "", k.local.model, "text")}</div>`,
      "Keeps documents on this machine: the only backend that sends nothing to a cloud API."),
  ].join("") + `<div class="flex justify-end"><button class="btn btn-primary" id="sSaveKeys"><i data-lucide="save"></i>Save keys to .env</button></div>`;

  $$("[data-test]").forEach(b => b.onclick = () => sTest(b.dataset.test));
  $("#sSaveKeys").onclick = sSaveKeys;

  const pii = await api("/api/pii/status");
  $("#sPii").checked = pii.enabled;
  $("#sPiiInfo").innerHTML = `Masks in the <b>text</b> sent to cloud models: ${pii.protected_entities.map(esc).join(", ")}.<br><span class="warn">${esc(pii.limitation)}</span>`;

  let rt = [];
  try { const o = await api("/api/overview"); rt = Object.entries(o.engine); } catch { /* optional */ }
  $("#sRuntime").innerHTML = `<div class="grid gap-2" style="font-size:12.5px">${rt.map(([a, b]) => `<div class="flex justify-between gap-3"><span class="muted mono">${esc(a)}</span><span class="mono">${esc(b)}</span></div>`).join("")}
    <div class="divider my-1"></div><div class="hint">Changes are written to <span class="mono">.env</span> and applied to the running server. Settings can only be changed from the machine running the server.</div></div>`;
  icons();
}

async function sTest(provider) {
  const out = $(`#sTest-${provider}`);
  out.innerHTML = `<span class="muted">testing…</span>`;
  const body = { provider };
  if (provider === "groq") body.api_key = $("#sGroq1").value.trim();
  if (provider === "openai") { body.api_key = $("#sOpenAIKey").value.trim(); body.base_url = $("#sOpenAIBase").value.trim(); }
  if (provider === "gemini") body.api_key = $("#sGeminiKey").value.trim();
  if (provider === "local") { body.base_url = $("#sLocalUrl").value.trim(); body.model = $("#sLocalModel").value.trim(); }
  try {
    const r = await api("/api/settings/test-connection", { body });
    out.innerHTML = r.success ? `<span class="ok">✓ ${esc(r.message)}</span>` : `<span class="err">✗ ${esc(r.message)}</span>`;
  } catch (e) { out.innerHTML = `<span class="err">✗ ${esc(e.message)}</span>`; }
}

async function sSaveKeys() {
  const groq = [1, 2, 3, 4].map(i => $(`#sGroq${i}`).value.trim()).filter(Boolean);
  const body = {
    gemini_key: $("#sGeminiKey").value.trim(), openai_key: $("#sOpenAIKey").value.trim(),
    openai_base_url: $("#sOpenAIBase").value.trim(), local_url: $("#sLocalUrl").value.trim(), local_model: $("#sLocalModel").value.trim(),
  };
  if (groq.length) body.groq_keys = groq;
  try {
    const r = await api("/api/settings/save-keys", { body });
    toast(r.updated.length ? `Saved: ${r.updated.join(", ")}` : "Nothing changed", r.updated.length ? "ok" : "info");
    await sLoad(); loadEngineStatus();
  } catch (e) { toast(e.message, "err"); }
}

registerPage("settings", {
  title: "Settings",
  sub: "Backends, API keys and privacy. Keys stay in your local .env and are never committed",
  init() {
    $("#sSaveMode").onclick = async () => {
      try { await api("/api/settings/save-keys", { body: { ai_mode: $("#sMode").value } }); toast(`AI_MODE = ${$("#sMode").value}`, "ok"); $("#modeSelect").value = $("#sMode").value; loadEngineStatus(); }
      catch (e) { toast(e.message, "err"); }
    };
    $("#sPii").onchange = async () => {
      try { await api("/api/pii/toggle", { body: { enabled: $("#sPii").checked } }); toast(`PII shield ${$("#sPii").checked ? "enabled" : "disabled"}`, "ok"); loadEngineStatus(); }
      catch (e) { toast(e.message, "err"); $("#sPii").checked = !$("#sPii").checked; }
    };
    $("#sPiiScan").onclick = async () => {
      try {
        const r = await api("/api/pii/scan", { body: { text: $("#sPiiText").value } });
        const out = $("#sPiiOut");
        out.classList.remove("hidden");
        out.textContent = `${r.redaction_count} redaction(s): ${r.detected_types.join(", ") || "none"}\n\n${r.masked_sample}`;
      } catch (e) { toast(e.message, "err"); }
    };
  },
  show: sLoad,
});
