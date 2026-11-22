"""
Agent tools: one implementation shared by

  * scripts/mcp_server.py    - a real MCP server (stdio) for Claude Desktop, Claude Code, Cursor, ...
  * /api/mcp/tools, /api/mcp/call - the dashboard's MCP page (live tool console)

so what you try in the UI is exactly what an agent gets.

Documents are addressed by `doc_id` (a sample-pack id such as "L01"/"U05", or an id returned by an
upload). The MCP server additionally accepts an absolute `path`, because it runs locally under the
user's own account; the HTTP endpoint does not (no arbitrary file reads through the web server).
"""
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ai_backends.router import VALID_MODES, get_backend
from config.settings import settings
from pipeline.document_loader import SUPPORTED_SUFFIXES
from pipeline.extractor import InvoiceExtractor
from pipeline.normalizer import normalize_payload
from pipeline.output_writer import result_metadata
from pipeline.template_engine import TemplateEngine, TemplateStore
from pipeline.validator import InvoiceValidator

_ID_RE = re.compile(r"[A-Za-z0-9_\-]{1,80}")
_extractors: Dict[str, InvoiceExtractor] = {}
_backends: Dict[str, Any] = {}
_lock = threading.Lock()


def _mode(mode: Optional[str]) -> str:
    return (mode or settings.ai_mode or "groq").lower()


def _extractor(mode: Optional[str]) -> InvoiceExtractor:
    """One extractor per backend, reused across calls so they share the rate-limit bucket and cache."""
    m = _mode(mode)
    with _lock:
        if m not in _extractors:
            _extractors[m] = InvoiceExtractor(get_backend(m))
        return _extractors[m]


def _backend(mode: Optional[str]):
    m = _mode(mode)
    with _lock:
        if m not in _backends:
            _backends[m] = get_backend(m)
        return _backends[m]


def _doc_dirs() -> List[Path]:
    return [settings.resolve_path(settings.labelled_dir), settings.resolve_path(settings.unlabelled_dir),
            settings.resolve_path(settings.upload_dir)]


def resolve_document(doc_id: Optional[str] = None, path: Optional[str] = None, allow_path: bool = False) -> Path:
    if path:
        if not allow_path:
            raise ValueError("'path' is not accepted here; pass a doc_id (see list_documents).")
        p = Path(path).expanduser()
        if not p.is_file():
            raise ValueError(f"File not found: {path}")
        if p.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported file type {p.suffix}; supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}")
        return p
    if not doc_id or not _ID_RE.fullmatch(doc_id.strip()):
        raise ValueError("Provide a doc_id such as 'L01' or 'U05' (see list_documents).")
    want = doc_id.strip().upper()
    for folder in _doc_dirs():
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in SUPPORTED_SUFFIXES and f.stem.upper() == want:
                return f
    raise ValueError(f"Document '{doc_id}' not found.")


# --------------------------------------------------------------------------- tools
def list_documents() -> Dict[str, Any]:
    """Sample-pack documents (and uploads) that the other tools can address by doc_id."""
    out = []
    labelled = settings.resolve_path(settings.labelled_dir)
    for category, folder in zip(("labelled", "unlabelled", "uploaded"), _doc_dirs()):
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in SUPPORTED_SUFFIXES:
                out.append({"doc_id": f.stem, "file": f.name, "category": category,
                            "has_ground_truth": category == "labelled" and (labelled / f"{f.stem}.json").exists()})
    return {"documents": out, "count": len(out)}


def extract_invoice(doc_id: Optional[str] = None, path: Optional[str] = None, mode: Optional[str] = None,
                    allow_path: bool = False) -> Dict[str, Any]:
    """Extract the 8-field invoice schema, validate it, and report needs_review, reasons and cost."""
    file_path = resolve_document(doc_id, path, allow_path)
    res = _extractor(mode).extract(file_path)
    meta = result_metadata(res)
    return {"data": res.data, **meta}


def validate_invoice_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the pipeline's schema + arithmetic checks on an invoice JSON produced elsewhere."""
    if isinstance(data, str):
        data = json.loads(data)
    norm = normalize_payload(data)
    rep = InvoiceValidator().check(norm)
    return {"valid": rep.ok, "errors": rep.errors, "warnings": rep.warnings,
            "normalized": rep.obj.model_dump() if rep.obj else None}


def list_templates() -> Dict[str, Any]:
    """Saved custom-field templates (Template Studio)."""
    return {"templates": [
        {"id": t["id"], "name": t["name"], "description": t.get("description"),
         "fields": [{"key": f["key"], "label": f.get("label"), "data_type": f.get("data_type"),
                     "required": f.get("required", False)} for f in t["fields"]]}
        for t in TemplateStore.list()]}


def extract_with_template(template_id: str, doc_id: Optional[str] = None, path: Optional[str] = None,
                          mode: Optional[str] = None, allow_path: bool = False) -> Dict[str, Any]:
    """Extract the fields of a saved template from any document (not only invoices)."""
    tmpl = TemplateStore.get(template_id)
    if not tmpl:
        raise ValueError(f"Template '{template_id}' not found (see list_templates).")
    file_path = resolve_document(doc_id, path, allow_path)
    return TemplateEngine.extract_with_custom_template(file_path, tmpl, backend=_backend(mode))


def get_latest_evaluation() -> Dict[str, Any]:
    """Headline numbers of the most recent labelled-set evaluation (python scripts/eval.py)."""
    p = settings.resolve_path("reports") / "eval_results.json"
    if not p.exists():
        return {"available": False, "hint": "Run: python scripts/eval.py"}
    s = json.loads(p.read_text(encoding="utf-8"))
    return {
        "available": True, "backend": s.get("mode"), "documents": s.get("total_docs"),
        "overall_accuracy_pct": s.get("overall_accuracy"), "field_accuracy_pct": s.get("field_accuracy"),
        "docs_fully_correct": s.get("docs_fully_correct"),
        "avg_cost_per_doc_usd": s.get("avg_cost_per_doc"),
        "tokens_in": s.get("total_tokens_in"), "tokens_out": s.get("total_tokens_out"),
        "error_groups": s.get("error_groups"), "needs_review_check": s.get("review"),
    }


# --------------------------------------------------------------------------- registry
_DOC = {"doc_id": {"type": "string", "description": "Document id, e.g. 'L01' or 'U05' (see list_documents)."}}
_MODE = {"mode": {"type": "string", "enum": VALID_MODES, "description": "Backend; default AI_MODE from .env."}}


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    fn: Callable[..., Dict[str, Any]]
    takes_path: bool = False


TOOLS: List[ToolSpec] = [
    ToolSpec("list_documents", "List the documents the other tools can read, with their doc_id.",
             {"type": "object", "properties": {}}, list_documents),
    ToolSpec("extract_invoice",
             "Extract vendor, invoice number, date, currency, line items, tax and total from an invoice "
             "(PDF/image). Returns validated JSON, needs_review + reasons, tokens and USD cost.",
             {"type": "object", "properties": {**_DOC, **_MODE}, "required": ["doc_id"]},
             extract_invoice, takes_path=True),
    ToolSpec("validate_invoice_json",
             "Check an invoice JSON against the schema and the arithmetic rule sum(items) + tax = total.",
             {"type": "object", "properties": {"data": {"type": "object", "description": "Invoice JSON."}},
              "required": ["data"]}, validate_invoice_json),
    ToolSpec("list_templates", "List saved custom-field templates (Template Studio).",
             {"type": "object", "properties": {}}, list_templates),
    ToolSpec("extract_with_template",
             "Extract the fields of a saved template from any document (hall tickets, waybills, ...).",
             {"type": "object", "properties": {"template_id": {"type": "string"}, **_DOC, **_MODE},
              "required": ["template_id", "doc_id"]}, extract_with_template, takes_path=True),
    ToolSpec("get_latest_evaluation",
             "Accuracy per field, cost per document and needs_review precision/recall from the last eval run.",
             {"type": "object", "properties": {}}, get_latest_evaluation),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def describe_tools() -> List[Dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in TOOLS]


def call_tool(name: str, arguments: Optional[Dict[str, Any]] = None, allow_path: bool = False) -> Dict[str, Any]:
    spec = TOOLS_BY_NAME.get(name)
    if not spec:
        raise ValueError(f"Unknown tool '{name}'. Available: {', '.join(TOOLS_BY_NAME)}")
    args = dict(arguments or {})
    allowed = set(spec.input_schema.get("properties", {})) | ({"path"} if spec.takes_path else set())
    unknown = set(args) - allowed
    if unknown:
        raise ValueError(f"Unknown argument(s) for {name}: {', '.join(sorted(unknown))}")
    if spec.takes_path:
        args["allow_path"] = allow_path
    return spec.fn(**args)
