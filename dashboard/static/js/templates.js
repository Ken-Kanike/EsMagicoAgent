/* Template studio: discover fields, edit, save (server is the single source of truth), test, use in batch. */
"use strict";

const T = { id: null, fields: [], docRef: null, zoom: 1, templates: [] };
const T_TYPES = ["string", "number", "date", "boolean", "table"];

function tRenderFields() {
  $("#tFieldCount").textContent = `${T.fields.filter(f => f.selected !== false).length} of ${T.fields.length} fields selected`;
  if (!T.fields.length) {
    $("#tFields").innerHTML = `<tr><td colspan="7"><div class="empty"><i data-lucide="list-plus"></i>No fields yet: auto-discover from a sample or add them below.</div></td></tr>`;
    icons(); return;
  }
  $("#tFields").innerHTML = T.fields.map((f, i) => `<tr>
    <td><input type="checkbox" data-i="${i}" data-k="selected" ${f.selected !== false ? "checked" : ""}></td>
    <td><input class="input mono" style="padding:4px 7px" data-i="${i}" data-k="key" value="${esc(f.key)}"></td>
    <td><input class="input" style="padding:4px 7px" data-i="${i}" data-k="label" value="${esc(f.label || "")}"></td>
    <td><select class="select" style="padding:4px 6px" data-i="${i}" data-k="data_type">${T_TYPES.map(t => `<option ${t === (f.data_type || "string") ? "selected" : ""}>${t}</option>`).join("")}</select></td>
    <td class="center"><input type="checkbox" data-i="${i}" data-k="required" ${f.required ? "checked" : ""}></td>
    <td class="truncate-1 muted" style="max-width:160px" title="${esc(f.sample_value ?? "")}">${esc(f.sample_value ?? "—")}</td>
    <td><button class="btn btn-sm btn-ghost btn-icon" data-del="${i}" title="Remove"><i data-lucide="trash-2"></i></button></td></tr>`).join("");
  $$("#tFields [data-k]").forEach(el => el.onchange = () => {
    const f = T.fields[+el.dataset.i];
    f[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value;
    if (el.dataset.k === "selected") tRenderFields();
  });
  $$("#tFields [data-del]").forEach(b => b.onclick = () => { T.fields.splice(+b.dataset.del, 1); tRenderFields(); });
  icons();
}

async function tLoadList(selectId) {
  const r = await api("/api/templates/list");
  T.templates = r.templates || [];
  $("#tSelect").innerHTML = `<option value="">New template (unsaved)</option>` + T.templates.map(t => `<option value="${esc(t.id)}">${esc(t.name)} · ${t.fields.length} fields</option>`).join("");
  $("#tSelect").value = selectId || "";
}

function tNew() {
  T.id = null; T.fields = [];
  $("#tName").value = ""; $("#tDesc").value = ""; $("#tSelect").value = ""; $("#tResult").innerHTML = "";
  tRenderFields();
}

async function tOpen(id) {
  if (!id) return tNew();
  const t = await api(`/api/templates/${encodeURIComponent(id)}`);
  T.id = t.id; T.fields = t.fields.map(f => ({ ...f, selected: true }));
  $("#tName").value = t.name; $("#tDesc").value = t.description || ""; $("#tResult").innerHTML = "";
  tRenderFields();
}

async function tSave() {
  const name = $("#tName").value.trim();
  if (!name) return toast("Give the template a name", "warn");
  const fields = T.fields.filter(f => f.selected !== false).map(({ selected, ...f }) => f);
  if (!fields.length) return toast("Select at least one field", "warn");
  const body = { name, description: $("#tDesc").value.trim(), fields };
  try {
    const r = T.id ? await api(`/api/templates/${encodeURIComponent(T.id)}`, { method: "PUT", body })
      : await api("/api/templates/save", { body });
    const created = !T.id;
    T.id = r.template.id;
    await tLoadList(T.id);
    await tOpen(T.id);
    toast(`Template "${r.template.name}" ${created ? "created" : "updated"}`, "ok");
  } catch (e) { toast(`Save failed: ${e.message}`, "err"); }
}

async function tDelete() {
  if (!T.id) return toast("Choose a saved template first", "warn");
  if (!(await confirmDialog("Delete template?", `"${$("#tName").value}" will be removed from templates/. This cannot be undone.`, "Delete", true))) return;
  try { await api(`/api/templates/${encodeURIComponent(T.id)}`, { method: "DELETE" }); toast("Template deleted", "ok"); await tLoadList(); tNew(); }
  catch (e) { toast(e.message, "err"); }
}

function tShowDoc(ref, label) {
  T.docRef = ref;
  T.zoom = 1;
  $("#tEmpty").classList.add("hidden");
  const img = $("#tImg");
  img.classList.remove("hidden");
  img.style.transform = "scale(1)";
  setPreviewImage(img, `/api/documents/${encodeURIComponent(ref)}/preview`);
  img.title = label || ref;
}

async function tUpload(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await api("/api/preview-file", { form: fd, blob: true });
    const stored = res.headers.get("X-Stored-As");
    $("#tSample").value = "";
    tShowDoc(stored, file.name);
    toast(`Loaded ${file.name}`, "ok");
  } catch (e) { toast(e.message, "err"); }
}

async function tDiscover() {
  if (!T.docRef) return toast("Choose a sample or upload a document first", "warn");
  const btn = $("#tDiscover");
  btn.disabled = true; btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i>Reading the document…`; icons();
  const fd = new FormData();
  fd.append("doc_id", T.docRef);
  fd.append("mode", currentMode());
  try {
    const r = await api("/api/templates/discover", { form: fd });
    const existing = new Set(T.fields.map(f => f.key));
    const found = (r.discovered_fields || []).filter(f => !existing.has(f.key)).map(f => ({ ...f, selected: true }));
    T.fields.push(...found);
    if (!$("#tName").value && r.document_type) $("#tName").value = r.document_type;
    tRenderFields();
    toast(`${found.length} field(s) discovered (${r.method === "llm" ? "LLM" : "offline parser"})`, "ok");
    if (r.warning) toast(r.warning, "warn", 7000);
  } catch (e) { toast(`Discovery failed: ${e.message}`, "err"); }
  finally { btn.disabled = false; btn.innerHTML = `<i data-lucide="wand-2"></i>Auto-discover fields`; icons(); }
}

async function tTest() {
  if (!T.id) return toast("Save the template first", "warn");
  if (!T.docRef) return toast("Choose a sample or upload a document", "warn");
  const btn = $("#tTest");
  btn.disabled = true; btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i>Extracting…`; icons();
  const fd = new FormData();
  fd.append("template_id", T.id); fd.append("doc_id", T.docRef); fd.append("mode", currentMode());
  try {
    const r = await api("/api/templates/extract", { form: fd });
    const missing = r.missing_fields || [];
    const banner = r.needs_review ? bannerHtml("warn", "Needs review", r.review_reasons || [`Missing: ${missing.join(", ")}`])
      : bannerHtml("ok", `All required fields found · ${r.method === "llm" ? "LLM" : "offline parser"}${missing.length ? ` · ${missing.length} optional field(s) empty` : ""}`);
    const cost = r.cost && r.cost.calls ? `<span class="badge badge-muted">${r.cost.tokens_in} in / ${r.cost.tokens_out} out · ${fmtUsd(r.cost.cost_usd)}</span>` : "";
    $("#tResult").innerHTML = `${banner}${r.warning ? bannerHtml("warn", r.warning) : ""}
      <div class="flex items-center justify-between mt-3 mb-2"><div class="flex gap-2">${cost}</div>
      <button class="btn btn-sm" id="tDl"><i data-lucide="download"></i>JSON</button></div>
      <div class="fields">${Object.entries(r.data || {}).map(([k, v]) => `<div class="field ${missing.includes(k) ? "mismatch" : ""}">
        <div class="field-label"><span>${esc(k)}</span></div><div class="field-value">${Array.isArray(v) ? `<span class="badge badge-muted">${v.length} rows</span>` : fmtVal(v)}</div></div>`).join("")}</div>
      <pre class="code mt-3">${esc(JSON.stringify(r.data, null, 2))}</pre>`;
    $("#tDl").onclick = () => downloadJson(r.data, `${T.id}_extract.json`);
    icons();
  } catch (e) { toast(`Extraction failed: ${e.message}`, "err"); }
  finally { btn.disabled = false; btn.innerHTML = `<i data-lucide="play"></i>Test extraction`; icons(); }
}

registerPage("templates", {
  title: "Template studio",
  sub: "Define custom fields for any document type, then use them in batch processing or over MCP",
  async init() {
    const docs = await api("/api/documents");
    $("#tSample").innerHTML = `<option value="">Choose a sample document…</option>` + docs.documents.map(d => `<option value="${esc(d.id)}">${esc(d.id)} · ${esc(d.filename)}</option>`).join("");
    $("#tSample").onchange = () => $("#tSample").value && tShowDoc($("#tSample").value, $("#tSample").value);
    $("#tUpload").onchange = e => { tUpload(e.target.files[0]); e.target.value = ""; };
    $("#tSelect").onchange = () => tOpen($("#tSelect").value).catch(e => toast(e.message, "err"));
    $("#tNew").onclick = tNew;
    $("#tSave").onclick = tSave;
    $("#tDelete").onclick = tDelete;
    $("#tDiscover").onclick = tDiscover;
    $("#tTest").onclick = tTest;
    $("#tUseBatch").onclick = () => T.id ? navigate("batch", { templateId: T.id }) : toast("Save the template first", "warn");
    $("#tZoomIn").onclick = () => { T.zoom = Math.min(3, T.zoom * 1.2); $("#tImg").style.transform = `scale(${T.zoom})`; };
    $("#tZoomOut").onclick = () => { T.zoom = Math.max(0.4, T.zoom / 1.2); $("#tImg").style.transform = `scale(${T.zoom})`; };
    $("#tAdd").onclick = () => {
      const key = $("#tNewKey").value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      if (!key || !/^[a-z]/.test(key)) return toast("Field keys start with a letter (a-z, 0-9, _)", "warn");
      if (T.fields.some(f => f.key === key)) return toast(`"${key}" already exists`, "warn");
      T.fields.push({ key, label: $("#tNewLabel").value.trim() || key, data_type: $("#tNewType").value, required: false, selected: true });
      $("#tNewKey").value = ""; $("#tNewLabel").value = "";
      tRenderFields();
    };
    tRenderFields();
  },
  async show() { await tLoadList(T.id); },
});
