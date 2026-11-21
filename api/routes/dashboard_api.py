import io
import os
import json
import time
import zipfile
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response, JSONResponse, StreamingResponse
import pandas as pd

from config.settings import settings
from pipeline.document_loader import load_document
from pipeline.extractor import InvoiceExtractor
from pipeline.output_writer import write_output, read_output
from ai_backends.router import get_backend
from eval.harness import run_evaluation
from eval.metrics import calculate_document_metrics
from pipeline.pii_shield import PIIShield
from pipeline.template_engine import TemplateEngine

router = APIRouter(prefix="/api", tags=["Enterprise Operations & Telemetry"])

# -------------------------------------------------------------
# 1. DOCUMENTS INTAKE & PREVIEW
# -------------------------------------------------------------

@router.get("/documents")
def list_documents():
    """List all available labelled and unlabelled sample documents with status metadata."""
    labelled_dir = settings.resolve_path(settings.labelled_dir)
    unlabelled_dir = settings.resolve_path(settings.unlabelled_dir)
    outputs_dir = settings.resolve_path(settings.outputs_dir)

    docs = []

    # 1. Labelled documents
    if labelled_dir.exists():
        for i in range(1, 11):
            doc_id = f"L{i:02d}"
            candidates = list(labelled_dir.glob(f"{doc_id}.*"))
            doc_file = next((f for f in candidates if f.suffix.lower() != ".json"), None)
            gt_file = labelled_dir / f"{doc_id}.json"

            if doc_file:
                out_file = outputs_dir / f"{doc_id}.json"
                docs.append({
                    "id": doc_id,
                    "filename": doc_file.name,
                    "category": "labelled",
                    "file_type": doc_file.suffix.lower().replace(".", "").upper(),
                    "size_kb": round(doc_file.stat().st_size / 1024, 1),
                    "has_ground_truth": gt_file.exists(),
                    "has_output": out_file.exists(),
                })

    # 2. Unlabelled documents
    if unlabelled_dir.exists():
        for i in range(1, 11):
            doc_id = f"U{i:02d}"
            candidates = list(unlabelled_dir.glob(f"{doc_id}.*"))
            doc_file = next((f for f in candidates if f.suffix.lower() != ".json"), None)

            if doc_file:
                out_file = outputs_dir / f"{doc_id}.json"
                docs.append({
                    "id": doc_id,
                    "filename": doc_file.name,
                    "category": "unlabelled",
                    "file_type": doc_file.suffix.lower().replace(".", "").upper(),
                    "size_kb": round(doc_file.stat().st_size / 1024, 1),
                    "has_ground_truth": False,
                    "has_output": out_file.exists(),
                })

    return {"documents": docs, "total": len(docs)}

@router.post("/preview-file")
async def preview_uploaded_file(file: UploadFile = File(...)):
    """Render page 1 of any uploaded PDF or image file as a PNG preview."""
    temp_dir = settings.resolve_path("temp_upload")
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / f"preview_{int(time.time())}_{file.filename}"
    with open(temp_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    doc_content = load_document(temp_path)
    if not doc_content.is_readable or not doc_content.images:
        raise HTTPException(status_code=400, detail="Cannot render document preview.")

    buf = io.BytesIO()
    doc_content.images[0].save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")

@router.post("/batch/export-excel")
def export_batch_records_to_excel(payload: Dict[str, Any]):
    """Export currently processed batch records to Excel."""
    records = payload.get("records", [])
    if not records:
        raise HTTPException(status_code=400, detail="No records provided for export.")

    summary_rows = []
    line_item_rows = []

    for r in records:
        doc_id = r.get("doc_id", "—")
        filename = r.get("filename", "—")
        is_inv = r.get("is_invoice", False)
        vendor = r.get("vendor", "—")
        inv_num = r.get("invoice_number", "—")
        inv_date = r.get("invoice_date", "—")
        curr = r.get("currency", "—")
        tax = r.get("tax_total", 0.0)
        tot = r.get("total", 0.0)
        status = "PASSED" if is_inv else "NON-INVOICE"

        summary_rows.append({
            "Document ID": doc_id,
            "File Name": filename,
            "Is Invoice": "YES" if is_inv else "NO",
            "Vendor": vendor,
            "Invoice Number": inv_num,
            "Date": inv_date,
            "Currency": curr,
            "Tax Total": tax if tax is not None else 0.0,
            "Grand Total": tot if tot is not None else 0.0,
            "Status": status
        })

        items = r.get("data", {}).get("line_items", []) or []
        for idx, it in enumerate(items, 1):
            line_item_rows.append({
                "Document ID": doc_id,
                "Item #": idx,
                "Vendor": vendor,
                "Currency": curr,
                "Description": it.get("description", "—"),
                "Quantity": it.get("quantity", "—"),
                "Amount": it.get("amount", 0.0)
            })

    output_buffer = io.BytesIO()
    with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Batch Invoices", index=False)
        pd.DataFrame(line_item_rows if line_item_rows else [{"Info": "No line items"}]).to_excel(writer, sheet_name="Line Items", index=False)

    output_buffer.seek(0)
    filename = f"Batch_Extraction_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        output_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.post("/batch/export-zip")
def export_batch_records_to_zip(payload: Dict[str, Any]):
    """Export currently processed batch records to JSON zip archive."""
    records = payload.get("records", [])
    if not records:
        raise HTTPException(status_code=400, detail="No records provided for export.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in records:
            doc_id = r.get("doc_id", "doc")
            data = r.get("data") or r
            zf.writestr(f"{doc_id}.json", json.dumps(data, indent=2))

    zip_buffer.seek(0)
    filename = f"Batch_JSON_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/documents/{doc_id}/preview")
def get_document_preview(doc_id: str, page: int = Query(0, ge=0)):
    """Render and stream page preview as high-resolution PNG."""
    doc_id = doc_id.upper()
    labelled_dir = settings.resolve_path(settings.labelled_dir)
    unlabelled_dir = settings.resolve_path(settings.unlabelled_dir)
    upload_dir = settings.resolve_path("temp_upload")

    target_file = None
    for folder in [labelled_dir, unlabelled_dir, upload_dir]:
        if folder.exists():
            candidates = list(folder.glob(f"{doc_id}.*"))
            f = next((c for c in candidates if c.suffix.lower() != ".json"), None)
            if f:
                target_file = f
                break

    if not target_file:
        for folder in [upload_dir, labelled_dir, unlabelled_dir]:
            if folder.exists():
                for f in folder.iterdir():
                    if f.suffix.lower() != ".json" and (f.stem.lower() == doc_id.lower() or f.name.lower() == doc_id.lower()):
                        target_file = f
                        break
                if target_file:
                    break

    if not target_file:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found.")

    doc_content = load_document(target_file)
    if not doc_content.is_readable or not doc_content.images:
        raise HTTPException(status_code=400, detail="Document could not be rendered to an image.")

    page_idx = min(page, len(doc_content.images) - 1)
    img = doc_content.images[page_idx]

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")

@router.get("/documents/{doc_id}/ground-truth")
def get_ground_truth(doc_id: str):
    """Fetch ground-truth JSON for a labelled document."""
    doc_id = doc_id.upper()
    labelled_dir = settings.resolve_path(settings.labelled_dir)
    gt_file = labelled_dir / f"{doc_id}.json"

    if not gt_file.exists():
        raise HTTPException(status_code=404, detail="No ground truth available for this document.")

    with open(gt_file, "r", encoding="utf-8") as f:
        return json.load(f)

@router.get("/documents/{doc_id}/output")
def get_document_output(doc_id: str):
    """Retrieve saved extraction output JSON for a document."""
    doc_id = doc_id.upper()
    data = read_output(doc_id)
    if data is None:
        return {"data": None, "exists": False}
    return {"data": data, "exists": True}

# -------------------------------------------------------------
# 2. EXTRACTION & UPLOADS
# -------------------------------------------------------------

@router.post("/extract/{doc_id}")
def extract_single_sample(doc_id: str, mode: Optional[str] = Query(None)):
    """Trigger extraction on a specific sample document."""
    doc_id = doc_id.upper()
    labelled_dir = settings.resolve_path(settings.labelled_dir)
    unlabelled_dir = settings.resolve_path(settings.unlabelled_dir)
    upload_dir = settings.resolve_path("temp_upload")

    target_file = None
    for folder in [labelled_dir, unlabelled_dir, upload_dir]:
        if folder.exists():
            candidates = list(folder.glob(f"{doc_id}.*"))
            f = next((c for c in candidates if c.suffix.lower() != ".json"), None)
            if f:
                target_file = f
                break

    if not target_file:
        for folder in [upload_dir, labelled_dir, unlabelled_dir]:
            if folder.exists():
                for f in folder.iterdir():
                    if f.suffix.lower() != ".json" and (f.stem.lower() == doc_id.lower() or f.name.lower() == doc_id.lower()):
                        target_file = f
                        break
                if target_file:
                    break

    if not target_file:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found.")

    start_time = time.time()
    effective_mode = mode or settings.ai_mode

    backend = get_backend(effective_mode)
    extractor = InvoiceExtractor(backend)
    res = extractor.extract(target_file)
    elapsed_ms = round((time.time() - start_time) * 1000, 1)

    if res.data:
        write_output(doc_id, res.data)

    gt_data = None
    matches = None
    gt_file = labelled_dir / f"{doc_id}.json"
    if gt_file.exists():
        with open(gt_file, "r", encoding="utf-8") as f:
            gt_data = json.load(f)
            matches = calculate_document_metrics(res.data, gt_data)

    return {
        "doc_id": doc_id,
        "filename": target_file.name,
        "mode": backend.name,
        "elapsed_ms": elapsed_ms,
        "needs_review": res.needs_review,
        "review_reasons": res.review_reasons,
        "data": res.data,
        "matches": matches,
        "cost": {
            "tokens_in": res.cost.tokens_in if res.cost else 0,
            "tokens_out": res.cost.tokens_out if res.cost else 0,
            "cost_usd": res.cost.cost_usd if res.cost else 0.0,
        }
    }

@router.post("/upload-and-extract")
async def upload_and_extract(
    file: UploadFile = File(...),
    mode: Optional[str] = Form(None)
):
    """Handle drag-and-drop or custom uploaded files directly."""
    temp_dir = settings.resolve_path("temp_upload")
    temp_dir.mkdir(exist_ok=True)
    file_path = temp_dir / file.filename

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    doc_id = file_path.stem.upper()
    backend = get_backend(mode or settings.ai_mode)
    extractor = InvoiceExtractor(backend)
    res = extractor.extract(file_path)

    if res.data:
        write_output(doc_id, res.data)

    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "mode": backend.name,
        "needs_review": res.needs_review,
        "review_reasons": res.review_reasons,
        "data": res.data
    }

@router.post("/batch-upload-and-extract")
async def batch_upload_and_extract(
    files: List[UploadFile] = File(...),
    mode: Optional[str] = Form(None)
):
    """
    Handle multi-file batch upload (drag & drop or folder selection).
    Processes arbitrary new invoice documents in bulk and persists outputs.
    """
    temp_dir = settings.resolve_path("temp_upload")
    temp_dir.mkdir(exist_ok=True)
    backend = get_backend(mode or settings.ai_mode)
    extractor = InvoiceExtractor(backend)

    results = []

    for f in files:
        file_path = temp_dir / f.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)

        doc_id = file_path.stem.upper()
        res = extractor.extract(file_path)

        if res.data:
            write_output(doc_id, res.data)

        items = (res.data.get("line_items") or []) if res.data else []
        results.append({
            "doc_id": doc_id,
            "filename": f.filename,
            "mode": backend.name,
            "is_invoice": res.data.get("is_invoice") if res.data else False,
            "vendor": res.data.get("vendor") if res.data else None,
            "invoice_number": res.data.get("invoice_number") if res.data else None,
            "invoice_date": res.data.get("invoice_date") if res.data else None,
            "currency": res.data.get("currency") if res.data else None,
            "tax_total": res.data.get("tax_total") if res.data else None,
            "total": res.data.get("total") if res.data else None,
            "needs_review": res.needs_review,
            "review_reasons": res.review_reasons,
            "line_items_count": len(items),
            "data": res.data
        })

    return {
        "total_uploaded": len(files),
        "results": results
    }

# -------------------------------------------------------------
# 2b. ENTERPRISE PII SHIELD & GOVERNANCE
# -------------------------------------------------------------

@router.get("/pii/status")
def get_pii_status():
    """Retrieve PII shield protection status."""
    return {
        "enabled": getattr(settings, "pii_shield_enabled", True),
        "protected_entities": [
            "Bank Account / IBAN Numbers",
            "Credit & Debit Cards",
            "SSN / National Identification",
            "PAN / Tax Registration IDs",
            "Personal Contact Numbers",
            "Personal Email Addresses"
        ]
    }

@router.post("/pii/toggle")
def toggle_pii_status(payload: Dict[str, Any]):
    """Toggle PII sanitization shield on/off."""
    enabled = bool(payload.get("enabled", True))
    settings.pii_shield_enabled = enabled

    # Persist in .env
    env_path = settings.resolve_path(".env")
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(env_path, "w", encoding="utf-8") as f:
            for l in lines:
                if l.startswith("PII_SHIELD_ENABLED="):
                    continue
                f.write(l)
            f.write(f"PII_SHIELD_ENABLED={str(enabled).lower()}\n")

    return {"status": "success", "enabled": enabled}

@router.post("/pii/scan")
def scan_text_pii(payload: Dict[str, Any]):
    """Scan arbitrary document or text for PII leaks."""
    text = payload.get("text", "")
    res = PIIShield.sanitize_text(text, mask_enabled=True)
    return {
        "has_pii": res.has_pii,
        "detected_types": res.detected_types,
        "redaction_count": res.redaction_count,
        "masked_sample": res.masked_text[:500]
    }

# -------------------------------------------------------------
# 2c. DYNAMIC CUSTOM EXTRACTION TEMPLATE STUDIO
# -------------------------------------------------------------

@router.post("/templates/discover")
async def discover_template_fields(
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None)
):
    """
    Auto-discover all keys, headers, numbers, and candidate fields from an uploaded
    or existing document to build a custom extraction template.
    """
    target_path = None
    if file:
        temp_dir = settings.resolve_path("temp_upload")
        temp_dir.mkdir(exist_ok=True)
        target_path = temp_dir / file.filename
        with open(target_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
    elif doc_id:
        doc_id = doc_id.upper()
        labelled_dir = settings.resolve_path(settings.labelled_dir)
        unlabelled_dir = settings.resolve_path(settings.unlabelled_dir)
        temp_dir = settings.resolve_path("temp_upload")
        for f in [labelled_dir, unlabelled_dir, temp_dir]:
            candidates = list(f.glob(f"{doc_id}.*"))
            hit = next((c for c in candidates if c.suffix.lower() != ".json"), None)
            if hit:
                target_path = hit
                break

    if not target_path or not target_path.exists():
        raise HTTPException(status_code=400, detail="Document could not be located for template discovery.")

    discovery = TemplateEngine.discover_fields(target_path)
    return discovery

@router.get("/templates/list")
def list_custom_templates():
    """List all user-defined custom extraction templates."""
    return {"templates": TemplateEngine.list_templates()}

@router.post("/templates/save")
def save_custom_template(template: Dict[str, Any]):
    """Save or update custom extraction schema."""
    saved = TemplateEngine.save_template(template)
    return {"status": "success", "template": saved}

@router.post("/templates/extract")
async def extract_with_custom_template(
    template_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    doc_id: Optional[str] = Form(None),
    mode: Optional[str] = Form(None)
):
    """Run extraction against target file using user's custom defined template."""
    tmpl = TemplateEngine.get_template(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found.")

    target_path = None
    if file:
        temp_dir = settings.resolve_path("temp_upload")
        temp_dir.mkdir(exist_ok=True)
        target_path = temp_dir / file.filename
        with open(target_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
    elif doc_id:
        doc_id = doc_id.upper()
        labelled_dir = settings.resolve_path(settings.labelled_dir)
        unlabelled_dir = settings.resolve_path(settings.unlabelled_dir)
        temp_dir = settings.resolve_path("temp_upload")
        for f in [labelled_dir, unlabelled_dir, temp_dir]:
            candidates = list(f.glob(f"{doc_id}.*"))
            hit = next((c for c in candidates if c.suffix.lower() != ".json"), None)
            if hit:
                target_path = hit
                break

    if not target_path or not target_path.exists():
        raise HTTPException(status_code=400, detail="Target document not found.")

    res = TemplateEngine.extract_with_custom_template(target_path, tmpl, backend_mode=mode)
    return res

# -------------------------------------------------------------
# 3. EXPORT EXCEL & JSON
# -------------------------------------------------------------

@router.get("/export/excel")
def export_all_to_excel():
    """Generate structured multi-tab Excel (.xlsx) report of all processed invoices."""
    outputs_dir = settings.resolve_path(settings.outputs_dir)
    json_files = sorted(list(outputs_dir.glob("*.json"))) if outputs_dir.exists() else []

    if not json_files:
        raise HTTPException(status_code=404, detail="No processed invoice outputs found in outputs/ directory.")

    summary_rows = []
    line_item_rows = []

    for jf in json_files:
        doc_id = jf.stem
        try:
            with open(jf, "r", encoding="utf-8") as f:
                d = json.load(f)

            is_inv = d.get("is_invoice", False)
            vendor = d.get("vendor")
            inv_num = d.get("invoice_number")
            inv_date = d.get("invoice_date")
            currency = d.get("currency")
            tax_total = d.get("tax_total")
            total = d.get("total")
            items = d.get("line_items") or []

            # Check math
            math_status = "N/A"
            if is_inv:
                l_sum = sum(i.get("amount", 0.0) for i in items)
                tax_val = tax_total or 0.0
                tot_val = total or 0.0
                if abs((l_sum + tax_val) - tot_val) <= settings.arithmetic_tolerance:
                    math_status = "BALANCED"
                else:
                    math_status = f"DIFF: {abs((l_sum + tax_val) - tot_val):.2f}"

            summary_rows.append({
                "Document ID": doc_id,
                "Is Invoice": "YES" if is_inv else "NO",
                "Vendor / Seller": vendor or "—",
                "Invoice Number": inv_num or "—",
                "Issue Date": inv_date or "—",
                "Currency": currency or "—",
                "Line Items Count": len(items),
                "Tax Total": tax_total if tax_total is not None else 0.0,
                "Grand Total": total if total is not None else 0.0,
                "Arithmetic Status": math_status
            })

            # Line items breakdown
            for idx, item in enumerate(items, start=1):
                line_item_rows.append({
                    "Document ID": doc_id,
                    "Item #": idx,
                    "Vendor": vendor or "—",
                    "Currency": currency or "—",
                    "Description": item.get("description", "—"),
                    "Quantity": item.get("quantity") if item.get("quantity") is not None else "—",
                    "Amount": item.get("amount", 0.0)
                })

        except Exception:
            continue

    df_summary = pd.DataFrame(summary_rows)
    df_items = pd.DataFrame(line_item_rows) if line_item_rows else pd.DataFrame(columns=["No Items"])

    output_buffer = io.BytesIO()
    with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="Invoices Summary", index=False)
        df_items.to_excel(writer, sheet_name="All Line Items", index=False)

    output_buffer.seek(0)
    filename = f"EsMagico_Invoices_Export_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"

    return StreamingResponse(
        output_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/export/zip")
def export_all_json_zip():
    """Download ZIP archive of all individual output JSON files."""
    outputs_dir = settings.resolve_path(settings.outputs_dir)
    json_files = list(outputs_dir.glob("*.json")) if outputs_dir.exists() else []

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for jf in json_files:
            zip_file.write(jf, arcname=jf.name)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=esmagico_outputs_json.zip"}
    )

@router.post("/templates/export-excel")
def export_custom_template_excel(payload: Dict[str, Any]):
    """Export custom defined template extraction records to Excel."""
    template_name = payload.get("template_name", "Custom_Template")
    records = payload.get("records", [])

    if not records:
        raise HTTPException(status_code=400, detail="No records provided for export.")

    df = pd.DataFrame(records)
    output_buffer = io.BytesIO()
    with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=template_name[:30], index=False)

    output_buffer.seek(0)
    filename = f"{re.sub(r'[^a-zA-Z0-9_-]', '_', template_name)}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        output_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# -------------------------------------------------------------
# 4. BENCHMARK & EVALUATION
# -------------------------------------------------------------

@router.get("/eval")
def get_evaluation_benchmark(mode: Optional[str] = Query(None)):
    """Run evaluation benchmark across labelled documents and return full summary."""
    summary = run_evaluation(mode=mode)
    return {
        "mode": summary.mode,
        "total_docs": summary.total_docs,
        "overall_accuracy": summary.overall_accuracy,
        "field_accuracy": summary.field_accuracy,
        "field_correct_counts": summary.field_correct_counts,
        "total_cost_usd": summary.total_cost_usd,
        "document_records": [
            {
                "doc_id": r.doc_id,
                "file_name": r.file_name,
                "field_matches": r.field_matches,
                "issues": r.issues
            }
            for r in summary.document_records
        ]
    }

# -------------------------------------------------------------
# 5. API KEYS & PROVIDER MANAGEMENT WITH LIVE CONNECTION TEST
# -------------------------------------------------------------

@router.get("/settings/keys")
def get_keys_status():
    """Get active provider status and masked key configuration."""
    def mask(k: Optional[str]) -> str:
        if not k or len(k) < 6:
            return ""
        return f"{k[:4]}...{k[-4:]}"

    groq_keys = [getattr(settings, f"groq_api_key_{i}", None) for i in range(1, 11)]
    groq_masked = [mask(k) for k in groq_keys if k]

    return {
        "active_mode": settings.ai_mode,
        "groq": {
            "keys_count": len(settings.groq_api_keys),
            "keys_masked": groq_masked,
            "text_model": settings.groq_text_model,
            "vision_model": settings.groq_vision_model,
        },
        "gemini": {
            "configured": bool(settings.gemini_api_key),
            "masked": mask(settings.gemini_api_key),
            "model": settings.gemini_model,
        },
        "openai": {
            "configured": bool(settings.openai_api_key),
            "masked": mask(settings.openai_api_key),
            "model": settings.openai_model,
            "base_url": settings.openai_base_url or "https://api.openai.com/v1"
        },
        "local": {
            "base_url": settings.local_llm_base_url,
            "model": settings.local_llm_model,
            "vision_enabled": settings.local_llm_vision_enabled
        }
    }

@router.post("/settings/save-keys")
def save_api_keys(payload: Dict[str, Any]):
    """Safely update .env file and reload runtime settings from the UI."""
    env_path = settings.resolve_path(".env")
    current_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            current_lines = f.readlines()

    env_map = {}
    for line in current_lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip()

    # Apply updates from payload
    if "ai_mode" in payload and payload["ai_mode"]:
        env_map["AI_MODE"] = str(payload["ai_mode"]).strip()

    # Groq keys
    if "groq_keys" in payload and isinstance(payload["groq_keys"], list):
        for idx in range(1, 11):
            key_name = f"GROQ_API_KEY_{idx}"
            if idx <= len(payload["groq_keys"]):
                val = str(payload["groq_keys"][idx - 1]).strip()
                if val:
                    env_map[key_name] = val
                else:
                    env_map[key_name] = ""
            else:
                env_map[key_name] = ""

    # Gemini
    if "gemini_key" in payload and payload["gemini_key"]:
        env_map["GEMINI_API_KEY"] = str(payload["gemini_key"]).strip()

    # OpenAI / Antigravity
    if "openai_key" in payload and payload["openai_key"]:
        env_map["OPENAI_API_KEY"] = str(payload["openai_key"]).strip()
    if "openai_base_url" in payload:
        env_map["OPENAI_BASE_URL"] = str(payload["openai_base_url"]).strip()

    # Local LLM
    if "local_url" in payload and payload["local_url"]:
        env_map["LOCAL_LLM_BASE_URL"] = str(payload["local_url"]).strip()
    if "local_model" in payload and payload["local_model"]:
        env_map["LOCAL_LLM_MODEL"] = str(payload["local_model"]).strip()

    # Write back to .env
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in env_map.items():
            f.write(f"{k}={v}\n")

    return {"status": "success", "message": "API configuration updated and saved to .env"}

@router.post("/settings/test-connection")
def test_connection(payload: Dict[str, Any]):
    """Perform a live ping against the chosen provider to verify key validity."""
    provider = payload.get("provider", "groq").lower()
    api_key = payload.get("api_key", "").strip()
    base_url = payload.get("base_url", "").strip()
    model = payload.get("model", "").strip()

    start_time = time.time()

    try:
        if provider == "groq":
            import groq
            key_to_use = api_key or (settings.groq_api_keys[0] if settings.groq_api_keys else None)
            if not key_to_use:
                return {"success": False, "message": "No Groq API key provided to test."}
            client = groq.Groq(api_key=key_to_use, timeout=10)
            res = client.chat.completions.create(
                model=model or settings.groq_text_model,
                messages=[{"role": "user", "content": "Respond with OK"}],
                max_tokens=5
            )
            elapsed = round((time.time() - start_time) * 1000, 1)
            return {"success": True, "latency_ms": elapsed, "message": f"Groq authentication verified ({elapsed}ms)."}

        elif provider in ("openai", "antigravity"):
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key or settings.openai_api_key or "sk-dummy",
                base_url=base_url or settings.openai_base_url or "https://api.openai.com/v1"
            )
            res = client.chat.completions.create(
                model=model or settings.openai_model,
                messages=[{"role": "user", "content": "Respond with OK"}],
                max_tokens=5,
                timeout=10
            )
            elapsed = round((time.time() - start_time) * 1000, 1)
            return {"success": True, "latency_ms": elapsed, "message": f"{provider.capitalize()} verified ({elapsed}ms)."}

        elif provider == "local":
            from openai import OpenAI
            client = OpenAI(
                base_url=base_url or settings.local_llm_base_url,
                api_key="local-key"
            )
            res = client.chat.completions.create(
                model=model or settings.local_llm_model,
                messages=[{"role": "user", "content": "Respond with OK"}],
                max_tokens=5,
                timeout=5
            )
            elapsed = round((time.time() - start_time) * 1000, 1)
            return {"success": True, "latency_ms": elapsed, "message": f"Local endpoint accessible ({elapsed}ms)."}

        else:
            return {"success": False, "message": f"Unknown provider: {provider}"}

    except Exception as e:
        elapsed = round((time.time() - start_time) * 1000, 1)
        return {"success": False, "latency_ms": elapsed, "message": f"Connection failed: {str(e)}"}

# -------------------------------------------------------------
# 6. MODEL CONTEXT PROTOCOL (MCP) & LOCAL HARNESS CAPABILITIES
# -------------------------------------------------------------

@router.get("/mcp/manifest")
def get_mcp_manifest():
    """
    Exposes Model Context Protocol (MCP) server manifest.
    Allows external autonomous agents (OpenCode, Hermes 3, Claude, Antigravity)
    to discover and invoke invoice extraction tools natively.
    """
    return {
        "mcp_version": "1.0",
        "name": "esmagico-invoice-engine",
        "description": "Enterprise Model Context Protocol (MCP) tools for invoice extraction, validation, and accounting reconciliation.",
        "capabilities": {
            "tools": True,
            "resources": True
        },
        "tools": [
            {
                "name": "extract_invoice",
                "description": "Extracts structured vendor, dates, currency, line items, and totals from a document file path or base64 stream.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute or workspace path to PDF or image file."},
                        "backend_mode": {"type": "string", "enum": ["no_ai", "groq", "local", "gemini", "openai"]}
                    },
                    "required": ["file_path"]
                }
            },
            {
                "name": "verify_invoice_math",
                "description": "Verifies arithmetic integrity between line items, taxes, and grand totals with configurable tolerance.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "line_items": {"type": "array"},
                        "tax_total": {"type": "number"},
                        "grand_total": {"type": "number"}
                    },
                    "required": ["line_items", "grand_total"]
                }
            },
            {
                "name": "reconcile_purchase_order",
                "description": "Performs 3-way matching between invoice payload and expected Purchase Order data.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "invoice_number": {"type": "string"},
                        "po_number": {"type": "string"},
                        "vendor_name": {"type": "string"},
                        "total_amount": {"type": "number"}
                    },
                    "required": ["invoice_number", "total_amount"]
                }
            }
        ],
        "local_harness_enhancements": [
            {
                "feature": "100% On-Premise Air-Gapped Privacy",
                "details": "With Local LLMs (Ollama / llama.cpp / Nous Hermes 3), zero financial information, customer names, or bank account numbers leave the organization's firewall."
            },
            {
                "feature": "Autonomous 3-Way ERP Reconciliation",
                "details": "Agents use MCP tool calling to query enterprise databases (Postgres, SAP, QuickBooks, Tally), cross-checking invoice line items against purchase orders and receipts."
            },
            {
                "feature": "Self-Correcting Reasoning Loops",
                "details": "When mathematical or schema discrepancies occur, local agent harnesses re-prompt models with structured error messages to resolve ambiguous table rows automatically."
            }
        ]
    }
