"""
Dynamic templates: extract user-defined fields from any document type
(hall tickets, waybills, receipts, claims ...).

Flow
  1. discover_fields(doc)   -> LLM lists every labelled field + every table on the page
                               (offline fallback: label/value parser that also handles
                               "Label:\\nValue" on the next line and several pairs per line)
  2. user edits/keeps fields -> TemplateStore.create / update   (server is the source of truth)
  3. extract(doc, template)  -> template-specific prompt + JSON object with exactly the
                               template keys -> type coercion -> missing/required check
"""
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from ai_backends.base import AIBackend, BackendError
from ai_backends.router import get_backend
from config.prompts import encode_images
from config.settings import settings
from pipeline.cost_tracker import CostTracker
from pipeline.document_loader import load_document
from pipeline.normalizer import normalize_date, parse_number
from pipeline.ocr_engine import get_best_document_text, has_embedded_text

DATA_TYPES = ("string", "number", "date", "boolean", "table")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,80}$")


def to_key(label: str) -> str:
    k = re.sub(r"[^a-z0-9]+", "_", str(label).lower()).strip("_")
    if not k or k[0].isdigit():
        k = f"field_{k}" if k else "field"
    return k[:64]


class TableColumn(BaseModel):
    key: str
    label: str = ""
    data_type: str = "string"

    @field_validator("key")
    @classmethod
    def _k(cls, v: str) -> str:
        v = to_key(v)
        return v

    @field_validator("data_type")
    @classmethod
    def _t(cls, v: str) -> str:
        return v if v in ("string", "number", "date", "boolean") else "string"


class TemplateField(BaseModel):
    key: str
    label: str = ""
    data_type: str = "string"
    description: Optional[str] = ""
    required: bool = False
    sample_value: Optional[Any] = None
    columns: List[TableColumn] = Field(default_factory=list)   # only for data_type == "table"

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = to_key(v)
        if not _KEY_RE.match(v):
            raise ValueError(f"invalid field key '{v}'")
        return v

    @field_validator("data_type")
    @classmethod
    def _dtype(cls, v: str) -> str:
        v = (v or "string").lower()
        aliases = {"array": "table", "list": "table", "int": "number", "float": "number", "bool": "boolean"}
        v = aliases.get(v, v)
        return v if v in DATA_TYPES else "string"


class CustomTemplate(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = ""
    fields: List[TemplateField]
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("template name is required")
        return v[:120]

    @field_validator("fields")
    @classmethod
    def _fields(cls, v: List[TemplateField]) -> List[TemplateField]:
        if not v:
            raise ValueError("a template needs at least one field")
        seen, out = set(), []
        for f in v:
            if f.key in seen:
                continue  # de-duplicate keys
            seen.add(f.key)
            out.append(f)
        return out


# --------------------------------------------------------------------------- storage
class TemplateStore:
    """JSON files in templates/ (atomic writes, validated ids)."""

    @staticmethod
    def _dir() -> Path:
        d = settings.resolve_path("templates")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _path(cls, template_id: str) -> Path:
        if not template_id or not _ID_RE.match(template_id):
            raise ValueError("invalid template id")
        return cls._dir() / f"{template_id}.json"

    @classmethod
    def list(cls) -> List[Dict[str, Any]]:
        out = []
        for f in sorted(cls._dir().glob("*.json")):
            try:
                out.append(CustomTemplate(**json.loads(f.read_text(encoding="utf-8"))).model_dump())
            except Exception:
                continue
        return sorted(out, key=lambda t: -t.get("updated_at", 0))

    @classmethod
    def get(cls, template_id: str) -> Optional[Dict[str, Any]]:
        try:
            p = cls._path(template_id)
        except ValueError:
            return None
        if not p.exists():
            return None
        return CustomTemplate(**json.loads(p.read_text(encoding="utf-8"))).model_dump()

    @classmethod
    def _write(cls, tmpl: CustomTemplate) -> Dict[str, Any]:
        p = cls._path(tmpl.id or "")
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(tmpl.model_dump(), fh, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
        return tmpl.model_dump()

    @classmethod
    def create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        data = {k: v for k, v in data.items() if k not in ("id", "created_at", "updated_at")}
        tmpl = CustomTemplate(**data)
        base = re.sub(r"[^a-z0-9]+", "_", tmpl.name.lower()).strip("_")[:50] or "template"
        tid, n = base, 2
        while cls._path(tid).exists():
            tid, n = f"{base}_{n}", n + 1
        tmpl.id = tid
        return cls._write(tmpl)

    @classmethod
    def update(cls, template_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        existing = cls.get(template_id)
        if existing is None:
            return None
        merged = {**existing, **{k: v for k, v in data.items() if k not in ("id", "created_at")}}
        merged["id"], merged["updated_at"] = template_id, time.time()
        return cls._write(CustomTemplate(**merged))

    @classmethod
    def delete(cls, template_id: str) -> bool:
        try:
            p = cls._path(template_id)
        except ValueError:
            return False
        if p.exists():
            p.unlink()
            return True
        return False


# --------------------------------------------------------------------------- prompts
DISCOVERY_PROMPT = """You analyse one document of ANY type (invoice, hall ticket, waybill, receipt, ID card, form, certificate, statement...).
List every piece of labelled data a user may want to extract into a spreadsheet.

Rules:
- One entry per distinct field: printed labels ("Seat Number", "PRN", "Exam Center") or obvious unlabelled items (document title, issuing organisation, person's name).
- key: snake_case from the label (seat_number). label: the label as printed. sample_value: the value exactly as printed.
- data_type: "string" | "number" (quantities/amounts only; identifiers such as PRN, roll, phone, account numbers are "string") | "date" | "boolean".
- Repeating rows (item tables, subject schedules, transactions) are ONE entry with data_type "table" and "columns": [{"key","label","data_type"}]; sample_value = the first row as an object.
- Skip decorative text, instructions paragraphs, signatures.
Return ONLY JSON: {"document_type": string, "fields": [{"key","label","data_type","sample_value","columns"?}]}"""

EXTRACT_PROMPT = """You extract data from ONE document into a fixed JSON object defined by the user's template.

Template fields:
{field_spec}

Rules:
- Return a JSON object with EXACTLY these top-level keys: {keys}. No other keys.
- Read every value from the document. If a field is not present, use null. Never copy example values; never invent.
- string: as printed (fix only obvious OCR spacing). number: plain JSON number, no separators/symbols. date: YYYY-MM-DD. boolean: true/false.
- table fields: an array with one object per row in printed order, using exactly the listed column keys; [] if the table is absent.
Return ONLY the JSON object."""


def _field_spec(fields: List[TemplateField]) -> str:
    lines = []
    for f in fields:
        line = f'- "{f.key}" ({f.data_type}) - {f.label or f.key}'
        if f.description:
            line += f": {f.description}"
        if f.required:
            line += " [required]"
        if f.data_type == "table":
            cols = ", ".join(f'"{c.key}" ({c.data_type}{", " + c.label if c.label else ""})' for c in f.columns) or "infer columns"
            line += f"\n    columns: {cols}"
        lines.append(line)
    return "\n".join(lines)


def _doc_inputs(doc, backend: AIBackend) -> Tuple[str, List[str]]:
    """Digital PDFs: layout text (text model). Scans/photos: page images (vision model), OCR if text-only."""
    if has_embedded_text(doc) and (settings.route_digital_to_text or not backend.supports_vision):
        return doc.layout_text, []
    if backend.supports_vision:
        return "", encode_images(doc.images, settings.max_image_side)
    return get_best_document_text(doc, layout="lines"), []


def _messages(system: str, text: str, images: List[str]) -> List[Dict[str, Any]]:
    intro = "Document text (exact text layer; table cells separated by |):\n" + text[:15000] if text else \
        "The document is attached as page image(s). Read it carefully."
    content: Any = intro
    if images:
        content = [{"type": "text", "text": intro}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images]
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def _cost_dict(tracker: CostTracker, name: str) -> Dict[str, Any]:
    c = tracker.total(name)
    return {"calls": c.calls, "tokens_in": c.tokens_in, "tokens_out": c.tokens_out, "cost_usd": c.cost_usd} if c else {}


# --------------------------------------------------------------------------- offline parser
_TIME_OR_NUM_KEY = re.compile(r"^[\d\s:.\-/]+$")
_SKIP_KEYS = {"http", "https", "www", "page", "note", "important"}


def offline_pairs(text: str) -> List[Tuple[str, str]]:
    """
    Label/value pairs from plain text. Handles
      "Seat Number: 1234567"            (same line)
      "Seat Number:" \\n "1234567"       (value on next line)
      "College: X   PRN: 123"           (several pairs on one line)
    and drops time/number fragments such as "10:30 AM" -> ("10", "30 AM").
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    pairs: List[Tuple[str, str]] = []
    i = 0
    label_re = r"([A-Za-z][A-Za-z0-9 .()/&'_\-]{1,40}?)"
    while i < len(lines):
        line = lines[i]
        if re.fullmatch(label_re + r"\s*[:.]", line) and i + 1 < len(lines) and not re.search(r":\s*$", lines[i + 1]):
            pairs.append((line.rstrip(":. "), lines[i + 1]))
            i += 2
            continue
        for m in re.finditer(label_re + r"\s*:\s*(.+?)(?=\s{2,}[A-Za-z][A-Za-z .()/]{1,40}:|\s*\|\s*|$)", line):
            k, v = m.group(1).strip(), m.group(2).strip()
            if v:
                pairs.append((k, v))
        i += 1
    out, seen = [], set()
    for k, v in pairs:
        key = to_key(k)
        if _TIME_OR_NUM_KEY.match(k) or key in seen or k.lower() in _SKIP_KEYS or len(v) > 200:
            continue
        seen.add(key)
        out.append((k, v))
    return out


def _guess_type(v: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[\-/.]\d{1,2}[\-/.]\d{2,4}|\d{1,2}\s?[A-Za-z]{3,9}\s?\d{4}", v.strip()):
        return "date"
    if re.fullmatch(r"-?[\d,]+\.\d{1,2}", v.strip()):
        return "number"
    return "string"


# --------------------------------------------------------------------------- engine
class TemplateEngine:
    # kept for backwards compatibility with older callers
    list_templates = staticmethod(lambda: TemplateStore.list())
    get_template = staticmethod(lambda tid: TemplateStore.get(tid))
    save_template = staticmethod(lambda data: TemplateStore.update(data["id"], data) if data.get("id")
                                 and TemplateStore.get(data["id"]) else TemplateStore.create(data))

    @classmethod
    def discover_fields(cls, file_path: Path, backend_mode: Optional[str] = None) -> Dict[str, Any]:
        doc = load_document(file_path)
        if not doc.is_readable:
            raise ValueError(doc.error or "Unreadable document")
        backend = get_backend(backend_mode)
        warning = None
        if backend.is_llm:
            tracker = CostTracker()
            try:
                text, images = _doc_inputs(doc, backend)
                raw, usage = backend.chat(_messages(DISCOVERY_PROMPT, text, images), max_tokens=4096)
                tracker.record(file_path.name, usage)
                from pipeline.extractor import parse_llm_json
                parsed = parse_llm_json(raw)
                fields = []
                for f in parsed.get("fields", []) or []:
                    try:
                        tf = TemplateField(**{**f, "sample_value": f.get("sample_value")})
                        fields.append(tf.model_dump())
                    except Exception:
                        continue
                return {"file_name": file_path.name, "method": "llm", "document_type": parsed.get("document_type"),
                        "discovered_fields": fields, "cost": _cost_dict(tracker, file_path.name)}
            except (BackendError, ValueError) as e:
                warning = f"LLM discovery failed ({e}); used offline parser."

        text = doc.layout_text if has_embedded_text(doc) else get_best_document_text(doc, layout="lines")
        fields = [TemplateField(key=to_key(k), label=k, sample_value=v, data_type=_guess_type(v)).model_dump()
                  for k, v in offline_pairs(text)]
        res = {"file_name": file_path.name, "method": "offline", "document_type": None,
               "discovered_fields": fields, "text_sample": text[:1500]}
        if warning:
            res["warning"] = warning
        return res

    @staticmethod
    def _coerce(f: TemplateField, v: Any) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if f.data_type == "number":
            if isinstance(v, str) and re.fullmatch(r"0\d+|\d{16,}", v.strip()):
                return v.strip()  # identifier-like: keep leading zeros / precision
            n = parse_number(v)
            return n if n is not None else v
        if f.data_type == "date":
            return normalize_date(v)
        if f.data_type == "boolean":
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ("true", "yes", "y", "1")
        if f.data_type == "table":
            if not isinstance(v, list):
                return []
            cols = {c.key: c for c in f.columns}
            rows = []
            for row in v:
                if not isinstance(row, dict):
                    continue
                if cols:
                    rows.append({k: TemplateEngine._coerce(TemplateField(key=k, data_type=c.data_type), row.get(k))
                                 for k, c in cols.items()})
                else:
                    rows.append(row)
            return rows
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)

    @classmethod
    def extract_with_custom_template(cls, file_path: Path, template: Dict[str, Any],
                                     backend_mode: Optional[str] = None, backend=None) -> Dict[str, Any]:
        """`backend` may be passed in so parallel batch workers share one rate-limit bucket."""
        tmpl = CustomTemplate(**template)
        doc = load_document(file_path)
        if not doc.is_readable:
            raise ValueError(doc.error or "Unreadable document")
        backend = backend or get_backend(backend_mode)
        raw_data: Dict[str, Any] = {}
        method, warning, cost = "offline", None, {}

        if backend.is_llm:
            tracker = CostTracker()
            system = EXTRACT_PROMPT.format(field_spec=_field_spec(tmpl.fields),
                                           keys=", ".join(f'"{f.key}"' for f in tmpl.fields))
            try:
                text, images = _doc_inputs(doc, backend)
                from pipeline.extractor import parse_llm_json
                raw, usage = backend.chat(_messages(system, text, images), max_tokens=6000)
                tracker.record(file_path.name, usage)
                raw_data = parse_llm_json(raw)
                method = "llm"
            except (BackendError, ValueError) as e:
                warning = f"LLM extraction failed ({e}); used offline parser."
            cost = _cost_dict(tracker, file_path.name)

        if method == "offline":
            text = doc.layout_text if has_embedded_text(doc) else get_best_document_text(doc, layout="lines")
            pairs = {to_key(k): v for k, v in offline_pairs(text)}
            labels = {to_key(k): v for k, v in offline_pairs(text)}
            for f in tmpl.fields:
                raw_data[f.key] = pairs.get(f.key) or labels.get(to_key(f.label or "")) or None

        data = {f.key: cls._coerce(f, raw_data.get(f.key)) for f in tmpl.fields}
        missing = [f.key for f in tmpl.fields if data[f.key] in (None, [], "")]
        missing_required = [f.key for f in tmpl.fields if f.required and f.key in missing]
        res = {
            "template_id": tmpl.id, "template_name": tmpl.name, "file": file_path.name, "method": method,
            "data": data, "missing_fields": missing,
            "needs_review": bool(missing_required) or warning is not None,
            "cost": cost,
        }
        if missing_required:
            res["review_reasons"] = [f"Required field '{k}' not found." for k in missing_required]
        if warning:
            res["warning"] = warning
        return res
