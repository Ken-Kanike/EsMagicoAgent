import re
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from config.settings import settings
from pipeline.document_loader import load_document
from pipeline.ocr_engine import get_best_document_text
from ai_backends.router import get_backend

class TemplateField(BaseModel):
    key: str
    label: str
    sample_value: Optional[str] = None
    data_type: str = "string"  # string, number, date, array
    description: Optional[str] = None
    required: bool = False

class CustomTemplate(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    fields: List[TemplateField]
    created_at: float = Field(default_factory=time.time)

TEMPLATES_DIR = settings.resolve_path("templates")
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

class TemplateEngine:
    """
    Dynamic Field Extraction and OCR Template Studio Engine.
    Allows end-users to upload an arbitrary document, auto-discover all entities,
    select custom output schemas, and extract those exact fields across future batches.
    """

    @classmethod
    def list_templates(cls) -> List[Dict[str, Any]]:
        """List all saved custom extraction templates."""
        templates = []
        for file in sorted(TEMPLATES_DIR.glob("*.json")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    templates.append(json.load(f))
            except Exception:
                continue
        return templates

    @classmethod
    def save_template(cls, template_data: Dict[str, Any]) -> Dict[str, Any]:
        """Save a new or updated extraction template."""
        template_id = template_data.get("id")
        if not template_id:
            name_slug = re.sub(r'[^a-zA-Z0-9_-]', '_', template_data.get("name", "custom_template")).lower()
            template_id = f"{name_slug}_{int(time.time())}"
            template_data["id"] = template_id

        if "created_at" not in template_data:
            template_data["created_at"] = time.time()

        file_path = TEMPLATES_DIR / f"{template_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(template_data, f, indent=2)

        return template_data

    @classmethod
    def get_template(cls, template_id: str) -> Optional[Dict[str, Any]]:
        """Fetch template by ID."""
        file_path = TEMPLATES_DIR / f"{template_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def discover_fields(cls, file_path: Path) -> Dict[str, Any]:
        """
        Deep scan an uploaded document and auto-discover all available fields,
        headers, numbers, dates, payment terms, and entity candidates.
        """
        doc = load_document(file_path)
        text = get_best_document_text(doc)

        discovered: List[Dict[str, Any]] = []
        seen_keys = set()

        def add_field(key: str, label: str, sample: str, data_type: str = "string"):
            norm_key = re.sub(r'[^a-z0-9_]', '_', key.lower()).strip('_')
            if norm_key not in seen_keys and sample:
                seen_keys.add(norm_key)
                discovered.append({
                    "key": norm_key,
                    "label": label,
                    "sample_value": str(sample).strip(),
                    "data_type": data_type
                })

        # 1. Invoice Number / Document Reference
        inv_match = re.search(r'\b(?:Invoice|Bill|Inv|Receipt|PO|Order)\s*(?:No\.?|Number|#)?\s*[:\-]?\s*([A-Za-z0-9\-\/]+)', text, re.IGNORECASE)
        if inv_match:
            add_field("invoice_number", "Invoice / Document #", inv_match.group(1))

        # 2. Dates
        dates = re.findall(r'\b(?:\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}|\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b', text)
        if dates:
            add_field("invoice_date", "Document Date", dates[0], "date")
            if len(dates) > 1:
                add_field("due_date", "Due Date / Payment Date", dates[1], "date")

        # 3. Currency & Amounts
        curr_match = re.search(r'\b(USD|EUR|GBP|INR|AUD|CAD|\$|€|£|₹)\b', text)
        if curr_match:
            add_field("currency", "Currency Code", curr_match.group(0))

        tot_match = re.search(r'\b(?:Total|Grand Total|Balance Due|Net Amount|Amount Payable)\s*[:\-]?\s*[$€£₹]?\s*([\d,]+\.\d{2})', text, re.IGNORECASE)
        if tot_match:
            add_field("total_amount", "Grand Total Amount", tot_match.group(1), "number")

        tax_match = re.search(r'\b(?:Tax|VAT|GST|HST|Sales Tax)\s*[:\-]?\s*[$€£₹]?\s*([\d,]+\.\d{2})', text, re.IGNORECASE)
        if tax_match:
            add_field("tax_amount", "Total Tax / VAT / GST", tax_match.group(1), "number")

        subtot_match = re.search(r'\b(?:Subtotal|Net Total|Pre-Tax Total)\s*[:\-]?\s*[$€£₹]?\s*([\d,]+\.\d{2})', text, re.IGNORECASE)
        if subtot_match:
            add_field("subtotal", "Subtotal Pre-Tax", subtot_match.group(1), "number")

        # 4. Vendor / Supplier
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            vendor_cand = next((l for l in lines[:5] if len(l) > 3 and not re.search(r'invoice|tax|date|order', l, re.IGNORECASE)), lines[0])
            add_field("vendor_name", "Vendor / Supplier Name", vendor_cand)

        # 5. Customer / Bill-To
        bill_match = re.search(r'(?:Bill To|Billed To|Customer|Ship To|Buyer)\s*[:\-]?\s*([^\n]+)', text, re.IGNORECASE)
        if bill_match:
            add_field("customer_name", "Customer / Bill-To Entity", bill_match.group(1).strip())

        # 6. PO Number
        po_match = re.search(r'\b(?:PO\s*#?|Purchase\s*Order(?:\s*No\.?)?)\s*[:\-]?\s*([A-Za-z0-9\-_/]+)', text, re.IGNORECASE)
        if po_match:
            add_field("po_number", "Purchase Order Reference", po_match.group(1))

        # 7. Payment Terms
        terms_match = re.search(r'\b(?:Terms|Payment\s*Terms)\s*[:\-]?\s*([^\n]+)', text, re.IGNORECASE)
        if terms_match:
            add_field("payment_terms", "Payment Terms (e.g. Net 30)", terms_match.group(1).strip())

        # 8. Tax ID / GSTIN / VAT Number
        gstin_match = re.search(r'\b(?:GSTIN|GST|VAT|Tax ID|EIN)\s*[:\-]?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        if gstin_match:
            add_field("tax_identification_number", "Tax ID / GSTIN / VAT #", gstin_match.group(1))

        # 9. Line Items table placeholder
        add_field("line_items", "Line Items Table", "[Array of Descriptions, Qty, Rates, Amounts]", "array")

        # 10. Generic Key-Value Pair Discovery (Captures any Colon-separated fields like Seat No, PRN, College, PO, etc.)
        for line in lines:
            kv_match = re.match(r'^([A-Za-z0-9\s/_\.\(\)\-]{2,35})\s*[:=]\s*(.+)$', line)
            if kv_match:
                raw_k = kv_match.group(1).strip()
                raw_v = kv_match.group(2).strip()
                if raw_k.lower() in ("http", "https") or len(raw_v) < 1:
                    continue
                dtype = "number" if re.match(r'^-?[\d,]+(?:\.\d+)?$', raw_v) else "string"
                if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$', raw_v):
                    dtype = "date"
                add_field(raw_k, raw_k.title(), raw_v, dtype)

        # 11. URLs and Web Portals
        urls = re.findall(r'https?://[^\s]+', text)
        if urls:
            add_field("portal_url", "Portal URL / Website", urls[0])

        return {
            "file_name": file_path.name,
            "text_sample": text[:1200],
            "discovered_fields": discovered
        }

    @classmethod
    def extract_with_custom_template(
        cls, file_path: Path, template: Dict[str, Any], backend_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract arbitrary user-defined schema fields from a target document.
        Works via deterministic regex parsing or external LLMs using custom JSON schema.
        """
        doc = load_document(file_path)
        text = get_best_document_text(doc)

        fields = template.get("fields", [])
        field_keys = [f["key"] for f in fields]
        field_prompts = [f"- {f['key']} ({f.get('label', f['key'])}): {f.get('description', '')}" for f in fields]

        backend = get_backend(backend_mode or settings.ai_mode)

        # If rule engine or offline mode
        if backend.name == "No-AI (Rule-Based & Regex Engine)":
            extracted = {}
            disc = cls.discover_fields(file_path)["discovered_fields"]
            disc_map = {d["key"]: d["sample_value"] for d in disc}

            for f in fields:
                k = f["key"]
                if k in disc_map:
                    val = disc_map[k]
                    if f.get("data_type") == "number":
                        try:
                            val = float(str(val).replace(",", "").replace("$", ""))
                        except Exception:
                            pass
                    extracted[k] = val
                else:
                    # Generic search in text
                    m = re.search(rf'{re.escape(k)}\s*[:\-]?\s*([^\n]+)', text, re.IGNORECASE)
                    extracted[k] = m.group(1).strip() if m else None

            return {
                "template_id": template.get("id"),
                "template_name": template.get("name"),
                "file": file_path.name,
                "data": extracted
            }

        # For AI backends, construct a dynamic prompt instructing strict JSON output matching user's template
        system_instruction = (
            f"You are a specialized custom document extraction engine.\n"
            f"Extract ONLY the following custom fields from the document:\n"
            + "\n".join(field_prompts)
            + "\nReturn a valid JSON object where the top-level keys match EXACTLY these keys:\n"
            + json.dumps({f["key"]: f.get("sample_value") or "extracted_value" for f in fields}, indent=2)
            + "\nOutput strict JSON only. Do not add markdown or conversational filler."
        )

        try:
            raw_response, usage = backend.extract(f"{system_instruction}\n\nDocument Text:\n{text}", doc.images)
            from pipeline.extractor import parse_llm_json
            parsed = parse_llm_json(raw_response)
            return {
                "template_id": template.get("id"),
                "template_name": template.get("name"),
                "file": file_path.name,
                "data": parsed
            }
        except Exception as e:
            # Fallback to discovered regex
            disc = cls.discover_fields(file_path)["discovered_fields"]
            disc_map = {d["key"]: d["sample_value"] for d in disc}
            return {
                "template_id": template.get("id"),
                "template_name": template.get("name"),
                "file": file_path.name,
                "data": {f["key"]: disc_map.get(f["key"]) for f in fields},
                "warning": f"AI extraction encountered error ({str(e)}), populated via layout fallback."
            }
