"""REST API used by the dashboard (dashboard/static/index.html)."""
import io
import json
import re
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from ai_backends.base import BackendNotConfigured
from ai_backends.router import VALID_MODES, get_backend
from config.settings import settings
from eval.metrics import calculate_document_metrics
from pipeline.batch_runner import run_many
from pipeline.document_loader import SUPPORTED_SUFFIXES, load_document
from pipeline.extractor import InvoiceExtractor
from pipeline.models import ExtractionResult
from pipeline.output_writer import read_output, result_metadata, write_output
from pipeline.pii_shield import PIIShield
from pipeline.template_engine import TemplateEngine, TemplateStore

router = APIRouter(prefix="/api", tags=["Dashboard"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_job_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job")
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------- helpers
def _dirs() -> List[Path]:
    return [settings.resolve_path(settings.labelled_dir), settings.resolve_path(settings.unlabelled_dir),
            settings.resolve_path(settings.upload_dir)]


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", Path(name).stem).strip("_")[:60]
    return stem or "document"


def _save_upload(file: UploadFile) -> Path:
    """Store an upload under a unique, sanitised name (no path traversal, no collisions)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type '{suffix or '(none)'}'. Use PDF, JPG, PNG, WEBP, TIFF.")
    up = settings.resolve_path(settings.upload_dir)
    up.mkdir(parents=True, exist_ok=True)
    dest = up / f"{_safe_stem(file.filename or 'upload')}__{uuid.uuid4().hex[:8]}{suffix}"
    size = 0
    with open(dest, "wb") as out:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "File larger than 25 MB.")
            out.write(chunk)
    return dest


def _doc_id_for(path: Path) -> str:
    return path.stem.split("__")[0].upper()


def _ui_write(doc_id: str, data: Dict[str, Any]) -> None:
    """
    Results produced from the dashboard go to outputs/dashboard/, never to outputs/<id>.json.
    The deliverable outputs/*.json are written only by scripts/batch.py and scripts/eval.py,
    so trying a different backend in the UI can't silently replace them.
    """
    write_output(doc_id, data, output_dir=settings.resolve_path(settings.outputs_dir) / "dashboard")


def _find_document(doc_id: str) -> Optional[Path]:
    doc_id = doc_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,80}", doc_id):
        return None
    for folder in _dirs():
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in SUPPORTED_SUFFIXES and (
                    f.stem.upper() == doc_id.upper() or _doc_id_for(f) == doc_id.upper()):
                return f
    return None


def _extractor(mode: Optional[str], use_cache: bool = True) -> InvoiceExtractor:
    try:
        return InvoiceExtractor(get_backend(mode or None), use_cache=use_cache)
    except BackendNotConfigured as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _result_payload(doc_id: str, filename: str, res: ExtractionResult) -> Dict[str, Any]:
    d = res.data or {}
    return {
        "doc_id": doc_id, "filename": filename, "mode": res.backend,
        "is_invoice": d.get("is_invoice"), "vendor": d.get("vendor"),
        "invoice_number": d.get("invoice_number"), "invoice_date": d.get("invoice_date"),
        "currency": d.get("currency"), "tax_total": d.get("tax_total"), "total": d.get("total"),
        "line_items_count": len(d.get("line_items") or []),
        "needs_review": res.needs_review, "review_reasons": res.review_reasons,
        "error": res.error, "error_type": res.error_type, "elapsed_ms": round(res.elapsed_s * 1000, 1),
        "cached": res.cached, "attempts": res.attempts,
        "cost": {"tokens_in": res.cost.tokens_in if res.cost else 0,
                 "tokens_out": res.cost.tokens_out if res.cost else 0,
                 "cost_usd": res.cost.cost_usd if res.cost else 0.0,
                 "calls": res.cost.calls if res.cost else 0},
        "data": res.data,
    }


def _require_local(request: Request):
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "Settings can only be changed from the machine running the server.")


def _update_env(updates: Dict[str, str]):
    """Update keys in .env in place (keeps comments and ordering)."""
    env_path = settings.resolve_path(".env")
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in remaining:
            out.append(f"{k}={remaining.pop(k)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _new_job(kind: str, total: int) -> str:
    jid = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[jid] = {"id": jid, "kind": kind, "status": "queued", "done": 0, "total": total,
                      "started_at": time.time(), "results": [], "error": None}
    return jid


def _job_update(jid: str, **kw):
    with _jobs_lock:
        _jobs[jid].update(kw)


# ---------------------------------------------------------------- documents
@router.get("/documents")
def list_documents():
    outputs = settings.resolve_path(settings.outputs_dir)
    docs = []
    for category, folder in (("labelled", _dirs()[0]), ("unlabelled", _dirs()[1])):
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            docs.append({
                "id": f.stem.upper(), "filename": f.name, "category": category,
                "file_type": f.suffix.lstrip(".").upper(), "size_kb": round(f.stat().st_size / 1024, 1),
                "has_ground_truth": (folder / f"{f.stem}.json").exists(),
                "has_output": (outputs / f"{f.stem}.json").exists(),
            })
    return {"documents": docs, "total": len(docs)}


def _render_png(path: Path, page: int = 0) -> bytes:
    doc = load_document(path)
    if not doc.is_readable or not doc.images:
        raise HTTPException(400, doc.error or "Cannot render document preview.")
    img = doc.images[min(page, len(doc.images) - 1)]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.post("/preview-file")
def preview_uploaded_file(file: UploadFile = File(...)):
    path = _save_upload(file)
    return Response(content=_render_png(path), media_type="image/png",
                    headers={"X-Doc-Id": _doc_id_for(path), "X-Stored-As": path.name})


@router.get("/documents/{doc_id}/preview")
def get_document_preview(doc_id: str, page: int = Query(0, ge=0)):
    path = _find_document(doc_id)
    if not path:
        raise HTTPException(404, f"Document {doc_id} not found.")
    return Response(content=_render_png(path, page), media_type="image/png")


@router.get("/documents/{doc_id}/ground-truth")
def get_ground_truth(doc_id: str):
    gt = settings.resolve_path(settings.labelled_dir) / f"{doc_id.upper()}.json"
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", doc_id) or not gt.exists():
        raise HTTPException(404, "No ground truth for this document.")
    return json.loads(gt.read_text(encoding="utf-8"))


@router.get("/documents/{doc_id}/output")
def get_document_output(doc_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", doc_id):
        raise HTTPException(400, "Invalid id")
    data = read_output(doc_id.upper())
    return {"data": data, "exists": data is not None}


# ---------------------------------------------------------------- extraction
def _with_gt(payload: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
    gt_file = settings.resolve_path(settings.labelled_dir) / f"{doc_id}.json"
    if gt_file.exists() and payload.get("data"):
        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        payload["ground_truth"] = gt
        payload["matches"] = calculate_document_metrics(payload["data"], gt)
    return payload


@router.post("/extract/{doc_id}")
def extract_single_sample(doc_id: str, mode: Optional[str] = Query(None), cache: bool = Query(True)):
    path = _find_document(doc_id)
    if not path:
        raise HTTPException(404, f"Document {doc_id} not found.")
    res = _extractor(mode, cache).extract(path)
    did = _doc_id_for(path)
    if res.data:
        _ui_write(did, res.data)
    return _with_gt(_result_payload(did, path.name, res), did)


@router.post("/upload-and-extract")
def upload_and_extract(file: UploadFile = File(...), mode: Optional[str] = Form(None)):
    path = _save_upload(file)
    res = _extractor(mode).extract(path)
    did = _doc_id_for(path)
    if res.data:
        _ui_write(did, res.data)
    return _result_payload(did, file.filename or path.name, res)


def _run_batch_job(jid: str, paths: List[Path], names: List[str], mode: Optional[str]):
    try:
        ex = InvoiceExtractor(get_backend(mode or None))
    except Exception as e:
        _job_update(jid, status="failed", error=str(e))
        return
    _job_update(jid, status="running")
    index = {p: i for i, p in enumerate(paths)}
    results: List[Optional[Dict[str, Any]]] = [None] * len(paths)

    def progress(done: int, total: int, r: ExtractionResult):
        p = next(p for p in paths if p.name == r.file)
        did = _doc_id_for(p)
        if r.data:
            _ui_write(did, r.data)
        results[index[p]] = _result_payload(did, names[index[p]], r)
        _job_update(jid, done=done, results=[x for x in results if x is not None], last_file=names[index[p]])

    run_many(paths, ex, on_progress=progress)
    _job_update(jid, status="completed", finished_at=time.time(), results=[x for x in results if x is not None])


@router.post("/batch/jobs")
def create_batch_job(files: List[UploadFile] = File(...), mode: Optional[str] = Form(None)):
    """Start a background batch; poll GET /api/batch/jobs/{id} for real progress."""
    if mode:
        _extractor(mode)  # validate backend before accepting the upload
    paths = [_save_upload(f) for f in files]
    jid = _new_job("batch", len(paths))
    _job_pool.submit(_run_batch_job, jid, paths, [f.filename or p.name for f, p in zip(files, paths)], mode)
    return {"job_id": jid, "total": len(paths)}


@router.get("/batch/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown job")
        job = dict(job)
    job["elapsed_s"] = round((job.get("finished_at") or time.time()) - job["started_at"], 1)
    return job


@router.post("/batch-upload-and-extract")
def batch_upload_and_extract(files: List[UploadFile] = File(...), mode: Optional[str] = Form(None)):
    """Synchronous variant (kept for API clients); processes files in parallel."""
    ex = _extractor(mode)
    paths = [_save_upload(f) for f in files]
    results = run_many(paths, ex)
    out = []
    for f, p, r in zip(files, paths, results):
        if r.data:
            _ui_write(_doc_id_for(p), r.data)
        out.append(_result_payload(_doc_id_for(p), f.filename or p.name, r))
    return {"total_uploaded": len(files), "results": out}


# ---------------------------------------------------------------- exports
def _xlsx_response(sheets: Dict[str, pd.DataFrame], filename: str) -> StreamingResponse:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


def _sheets_from_records(records: List[Dict[str, Any]]) -> Dict[str, pd.DataFrame]:
    summary, items = [], []
    for r in records:
        d = r.get("data") or {}
        lis = d.get("line_items") or []
        line_sum = round(sum((i.get("amount") or 0) for i in lis), 2)
        balanced = None
        if d.get("is_invoice") and d.get("total") is not None:
            balanced = abs(line_sum + (d.get("tax_total") or 0) - d["total"]) <= max(settings.arithmetic_tolerance,
                                                                                     0.01 * len(lis))
        summary.append({
            "Document": r.get("doc_id"), "File": r.get("filename"), "Is invoice": d.get("is_invoice"),
            "Vendor": d.get("vendor"), "Invoice number": d.get("invoice_number"),
            "Invoice date": d.get("invoice_date"), "Currency": d.get("currency"), "Line items": len(lis),
            "Sum of items": line_sum if lis else None, "Tax total": d.get("tax_total"), "Total": d.get("total"),
            "Totals balance": balanced, "Needs review": r.get("needs_review"),
            "Review reasons": "; ".join(r.get("review_reasons") or []), "Error": r.get("error"),
        })
        for i, it in enumerate(lis, 1):
            items.append({"Document": r.get("doc_id"), "Vendor": d.get("vendor"), "Currency": d.get("currency"),
                          "#": i, "Description": it.get("description"), "Quantity": it.get("quantity"),
                          "Amount": it.get("amount")})
    return {"Invoices": pd.DataFrame(summary),
            "Line items": pd.DataFrame(items or [{"Info": "No line items"}])}


@router.post("/batch/export-excel")
def export_batch_records_to_excel(payload: Dict[str, Any]):
    records = payload.get("records") or []
    if not records:
        raise HTTPException(400, "No records provided.")
    return _xlsx_response(_sheets_from_records(records), f"batch_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")


@router.post("/batch/export-zip")
def export_batch_records_to_zip(payload: Dict[str, Any]):
    records = payload.get("records") or []
    if not records:
        raise HTTPException(400, "No records provided.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in records:
            if r.get("data"):
                zf.writestr(f"{_safe_stem(str(r.get('doc_id') or 'doc'))}.json",
                            json.dumps(r["data"], indent=2, ensure_ascii=False))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename=batch_{time.strftime('%Y%m%d_%H%M%S')}.zip"})


def _saved_records() -> List[Dict[str, Any]]:
    out_dir = settings.resolve_path(settings.outputs_dir)
    recs = []
    for jf in sorted(out_dir.glob("*.json")) if out_dir.exists() else []:
        try:
            recs.append({"doc_id": jf.stem, "filename": jf.name, "data": json.loads(jf.read_text(encoding="utf-8"))})
        except Exception:
            continue
    return recs


@router.get("/export/excel")
def export_all_to_excel():
    recs = _saved_records()
    if not recs:
        raise HTTPException(404, "No outputs yet.")
    return _xlsx_response(_sheets_from_records(recs), f"outputs_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")


@router.get("/export/zip")
def export_all_json_zip():
    out_dir = settings.resolve_path(settings.outputs_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for jf in sorted(out_dir.glob("*.json")) if out_dir.exists() else []:
            zf.write(jf, arcname=jf.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=outputs_json.zip"})


# ---------------------------------------------------------------- PII
@router.get("/pii/status")
def get_pii_status():
    return {"enabled": settings.pii_shield_enabled,
            "protected_entities": ["IBAN", "Labelled bank account numbers", "Card numbers (Luhn-checked)",
                                   "Emails", "Labelled / international phone numbers", "US SSN", "Indian PAN"],
            "limitation": "Only the text sent to the model is masked; page images sent to vision models are not."}


@router.post("/pii/toggle")
def toggle_pii_status(payload: Dict[str, Any], request: Request):
    _require_local(request)
    enabled = bool(payload.get("enabled", False))
    settings.pii_shield_enabled = enabled
    _update_env({"PII_SHIELD_ENABLED": str(enabled).lower()})
    return {"status": "success", "enabled": enabled}


@router.post("/pii/scan")
def scan_text_pii(payload: Dict[str, Any]):
    res = PIIShield.sanitize_text(str(payload.get("text", "")), mask_enabled=True)
    return {"has_pii": res.has_pii, "detected_types": res.detected_types,
            "redaction_count": res.redaction_count, "masked_sample": res.masked_text[:1000]}


# ---------------------------------------------------------------- templates
def _template_target(file: Optional[UploadFile], doc_id: Optional[str]) -> Path:
    if file is not None and file.filename:
        return _save_upload(file)
    if doc_id:
        p = _find_document(doc_id)
        if p:
            return p
    raise HTTPException(400, "Upload a document or choose an existing one.")


@router.post("/templates/discover")
def discover_template_fields(file: Optional[UploadFile] = File(None), doc_id: Optional[str] = Form(None),
                             mode: Optional[str] = Form(None)):
    path = _template_target(file, doc_id)
    try:
        res = TemplateEngine.discover_fields(path, backend_mode=mode or None)
    except BackendNotConfigured as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    res["doc_id"] = _doc_id_for(path)
    return res


@router.get("/templates/list")
def list_custom_templates():
    return {"templates": TemplateStore.list()}


@router.get("/templates/{template_id}")
def get_custom_template(template_id: str):
    t = TemplateStore.get(template_id)
    if not t:
        raise HTTPException(404, "Template not found.")
    return t


@router.post("/templates/save")
def save_custom_template(template: Dict[str, Any]):
    """Create (no id) or update (existing id) a template."""
    try:
        tid = template.get("id")
        saved = TemplateStore.update(tid, template) if tid and TemplateStore.get(tid) else TemplateStore.create(template)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"status": "success", "template": saved}


@router.put("/templates/{template_id}")
def update_custom_template(template_id: str, template: Dict[str, Any]):
    try:
        saved = TemplateStore.update(template_id, template)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not saved:
        raise HTTPException(404, "Template not found.")
    return {"status": "success", "template": saved}


@router.delete("/templates/{template_id}")
def delete_custom_template(template_id: str):
    if not TemplateStore.delete(template_id):
        raise HTTPException(404, "Template not found.")
    return {"status": "deleted", "id": template_id}


@router.post("/templates/extract")
def extract_with_custom_template(template_id: str = Form(...), file: Optional[UploadFile] = File(None),
                                 doc_id: Optional[str] = Form(None), mode: Optional[str] = Form(None)):
    tmpl = TemplateStore.get(template_id)
    if not tmpl:
        raise HTTPException(404, f"Template {template_id} not found.")
    path = _template_target(file, doc_id)
    try:
        return TemplateEngine.extract_with_custom_template(path, tmpl, backend_mode=mode or None)
    except BackendNotConfigured as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/templates/export-excel")
def export_custom_template_excel(payload: Dict[str, Any]):
    name = str(payload.get("template_name") or "template")
    records = payload.get("records") or []
    if not records:
        raise HTTPException(400, "No records provided.")
    flat, tables = [], {}
    for r in records:
        row = {"file": r.get("file")}
        for k, v in (r.get("data") or {}).items():
            if isinstance(v, list):
                tables.setdefault(k, []).extend({"file": r.get("file"), **x} for x in v if isinstance(x, dict))
                row[k] = f"{len(v)} rows"
            else:
                row[k] = v
        flat.append(row)
    sheets = {"Records": pd.DataFrame(flat)}
    for k, rows in tables.items():
        sheets[k[:31]] = pd.DataFrame(rows or [{}])
    return _xlsx_response(sheets, f"{_safe_stem(name)}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")


# ---------------------------------------------------------------- evaluation
def _run_eval_job(jid: str, mode: Optional[str], use_cache: bool):
    from eval.harness import run_evaluation, summary_to_dict
    from eval.report import generate_markdown_report, save_reports
    _job_update(jid, status="running")
    try:
        s = run_evaluation(mode=mode, use_cache=use_cache, save_outputs=False)
        save_reports(generate_markdown_report(s), s)
        _job_update(jid, status="completed", done=s.total_docs, result=summary_to_dict(s), finished_at=time.time())
    except Exception as e:
        _job_update(jid, status="failed", error=f"{type(e).__name__}: {e}", finished_at=time.time())


@router.post("/eval/jobs")
def start_eval_job(mode: Optional[str] = Query(None), cache: bool = Query(True)):
    _extractor(mode)
    jid = _new_job("eval", 10)
    _job_pool.submit(_run_eval_job, jid, mode, cache)
    return {"job_id": jid}


@router.get("/eval/latest")
def latest_eval():
    p = settings.resolve_path("reports") / "eval_results.json"
    if not p.exists():
        return {"available": False}
    return {"available": True, "result": json.loads(p.read_text(encoding="utf-8"))}


@router.get("/eval")
def get_evaluation_benchmark(mode: Optional[str] = Query(None), cache: bool = Query(True)):
    """Synchronous evaluation (can take minutes on the Groq free tier; prefer POST /api/eval/jobs)."""
    from eval.harness import run_evaluation, summary_to_dict
    try:
        s = run_evaluation(mode=mode, use_cache=cache)
    except BackendNotConfigured as e:
        raise HTTPException(400, str(e))
    return summary_to_dict(s)


# ---------------------------------------------------------------- settings
def _mask(k: Optional[str]) -> str:
    return f"{k[:4]}...{k[-4:]}" if k and len(k) > 10 else ""


@router.get("/settings/keys")
def get_keys_status():
    return {
        "active_mode": settings.ai_mode, "valid_modes": VALID_MODES,
        "groq": {"keys_count": len(settings.groq_api_keys), "keys_masked": [_mask(k) for k in settings.groq_api_keys],
                 "text_model": settings.groq_text_model, "vision_model": settings.groq_vision_model,
                 "note": "All keys of one Groq organisation share the same per-model rate limit."},
        "gemini": {"configured": bool(settings.gemini_api_key), "masked": _mask(settings.gemini_api_key),
                   "model": settings.gemini_model},
        "openai": {"configured": bool(settings.openai_api_key), "masked": _mask(settings.openai_api_key),
                   "model": settings.openai_model, "base_url": settings.openai_base_url or "https://api.openai.com/v1"},
        "local": {"base_url": settings.local_llm_base_url, "model": settings.local_llm_model,
                  "vision_enabled": settings.local_llm_vision_enabled},
        "pii_shield_enabled": settings.pii_shield_enabled,
    }


@router.post("/settings/save-keys")
def save_api_keys(payload: Dict[str, Any], request: Request):
    _require_local(request)
    upd: Dict[str, str] = {}
    if payload.get("ai_mode"):
        if payload["ai_mode"] not in VALID_MODES:
            raise HTTPException(400, f"ai_mode must be one of {VALID_MODES}")
        upd["AI_MODE"] = payload["ai_mode"]
    if isinstance(payload.get("groq_keys"), list):
        keys = [str(k).strip() for k in payload["groq_keys"] if str(k).strip() and "..." not in str(k)]
        if keys:
            for i in range(1, 11):
                upd[f"GROQ_API_KEY_{i}"] = keys[i - 1] if i <= len(keys) else ""
    for src, env in (("gemini_key", "GEMINI_API_KEY"), ("openai_key", "OPENAI_API_KEY"),
                     ("openai_base_url", "OPENAI_BASE_URL"), ("local_url", "LOCAL_LLM_BASE_URL"),
                     ("local_model", "LOCAL_LLM_MODEL")):
        v = payload.get(src)
        if isinstance(v, str) and v.strip() and "..." not in v:
            upd[env] = v.strip()
    if upd:
        _update_env(upd)
        for k, v in upd.items():  # apply to the running process too
            attr = k.lower()
            if hasattr(settings, attr):
                setattr(settings, attr, v)
    return {"status": "success", "updated": sorted(upd)}


@router.post("/settings/test-connection")
def test_connection(payload: Dict[str, Any]):
    provider = str(payload.get("provider", "groq")).lower()
    api_key = str(payload.get("api_key") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()
    t = time.time()
    try:
        if provider == "groq":
            import groq
            key = api_key or (settings.groq_api_keys[0] if settings.groq_api_keys else None)
            if not key:
                return {"success": False, "message": "No Groq key to test."}
            groq.Groq(api_key=key, timeout=15).chat.completions.create(
                model=model or settings.groq_text_model, messages=[{"role": "user", "content": "Reply OK"}],
                max_tokens=5)
        elif provider in ("openai", "gemini", "local"):
            from openai import OpenAI
            defaults = {
                "openai": (settings.openai_api_key, settings.openai_base_url or None, settings.openai_model),
                "gemini": (settings.gemini_api_key, "https://generativelanguage.googleapis.com/v1beta/openai/",
                           settings.gemini_model),
                "local": (settings.local_llm_api_key, settings.local_llm_base_url, settings.local_llm_model),
            }[provider]
            client = OpenAI(api_key=api_key or defaults[0] or "missing", base_url=base_url or defaults[1], timeout=15)
            client.chat.completions.create(model=model or defaults[2],
                                           messages=[{"role": "user", "content": "Reply OK"}], max_tokens=5)
        else:
            return {"success": False, "message": f"Unknown provider: {provider}"}
        ms = round((time.time() - t) * 1000, 1)
        return {"success": True, "latency_ms": ms, "message": f"{provider} OK ({ms} ms)"}
    except Exception as e:
        return {"success": False, "latency_ms": round((time.time() - t) * 1000, 1),
                "message": f"Connection failed: {type(e).__name__}: {str(e)[:200]}"}


# ---------------------------------------------------------------- tool schema
@router.get("/mcp/manifest")
def get_mcp_manifest():
    """JSON tool descriptions for agent frameworks. This is a schema only, not a running MCP server."""
    return {
        "name": "invoice-extraction-tools",
        "note": "Tool schemas that map 1:1 to this REST API. Not an MCP server process.",
        "tools": [
            {"name": "extract_invoice", "http": "POST /extract (multipart file)",
             "description": "Extract the 8-field invoice schema from a PDF/image; returns needs_review + reasons.",
             "parameters": {"type": "object", "properties": {
                 "file": {"type": "string", "format": "binary"},
                 "mode": {"type": "string", "enum": VALID_MODES}}, "required": ["file"]}},
            {"name": "start_batch", "http": "POST /api/batch/jobs",
             "description": "Process many files in the background; poll GET /api/batch/jobs/{id}."},
            {"name": "extract_with_template", "http": "POST /api/templates/extract",
             "description": "Extract user-defined fields with a saved template."},
            {"name": "evaluate", "http": "POST /api/eval/jobs",
             "description": "Run the labelled-set evaluation and return field accuracy."},
        ],
    }
