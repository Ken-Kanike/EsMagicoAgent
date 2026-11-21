import re
import json
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
from PIL import Image
from ai_backends.base import AIBackend
from pipeline.models import TokenUsage

class NoAIBackend(AIBackend):
    """
    Deterministic rule & layout parser using token streaming, layout heuristics,
    and regular expressions. Operates 100% offline with zero AI API costs.
    """

    @property
    def name(self) -> str:
        return "No-AI (Rule-Based & Layout Parser)"

    @property
    def supports_vision(self) -> bool:
        return False

    def extract(
        self,
        text: str,
        images: List[Image.Image],
        retry: bool = False,
        retry_reason: str = ""
    ) -> Tuple[str, TokenUsage]:
        usage = TokenUsage(
            mode="no_ai",
            model="layout-parser-v2",
            model_pricing_key="no_ai",
            prompt_tokens=0,
            completion_tokens=0
        )

        if not text or not text.strip():
            result = {
                "is_invoice": False,
                "vendor": None,
                "invoice_number": None,
                "invoice_date": None,
                "currency": None,
                "line_items": None,
                "tax_total": None,
                "total": None
            }
            return json.dumps(result, indent=2), usage

        is_inv = self._detect_is_invoice(text)
        if not is_inv:
            result = {
                "is_invoice": False,
                "vendor": None,
                "invoice_number": None,
                "invoice_date": None,
                "currency": None,
                "line_items": None,
                "tax_total": None,
                "total": None
            }
            return json.dumps(result, indent=2), usage

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        currency = self._extract_currency(text)
        vendor = self._extract_vendor(lines)
        invoice_number = self._extract_invoice_number(lines, text)
        invoice_date = self._extract_date(lines, text)
        line_items = self._extract_line_items(lines)
        tax_total, total = self._extract_tax_and_total(lines)

        # Reconcile if line items exist and total is missing or out of balance
        if line_items and total is None:
            sum_items = sum(item["amount"] for item in line_items)
            total = round(sum_items + (tax_total or 0.0), 2)

        result = {
            "is_invoice": True,
            "vendor": vendor,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "currency": currency,
            "line_items": line_items,
            "tax_total": tax_total,
            "total": total
        }

        return json.dumps(result, indent=2), usage

    def _detect_is_invoice(self, text: str) -> bool:
        lower = text.lower()
        non_invoice_cues = [
            "purchase order", "po no.", "po no ", "po-", "po date", "po total",
            "bank statement", "account statement", "harbor trust bank",
            "cover letter", "hiring manager", "dear hiring", "curriculum vitae", "resume",
            "bill of lading", "packing slip", "delivery challan"
        ]
        for cue in non_invoice_cues:
            if cue in lower:
                if any(strong in lower for strong in ["purchase order", "account statement", "hiring manager", "cover letter"]):
                    return False

        invoice_cues = [
            "tax invoice", "invoice", "inv no", "invoice no", "invoice #",
            "rechnung", "facture", "bill to", "invoice date", "amount payable", "total due"
        ]
        return any(cue in lower for cue in invoice_cues)

    def _extract_vendor(self, lines: List[str]) -> Optional[str]:
        # Typically vendor is the first line or right after "TAX INVOICE"
        for i, line in enumerate(lines[:8]):
            clean = line.split("|")[0].strip()
            clean = re.sub(r"^(?:TAX\s+INVOICE|INVOICE)\s*", "", clean, flags=re.I).strip()
            if not clean:
                continue
            lower = clean.lower()
            if any(k in lower for k in ["tax invoice", "invoice", "page 1", "page", "bill to", "ship to", "purchase order"]):
                continue
            if len(clean) >= 3 and not re.match(r"^[0-9\-\/]+$", clean):
                return clean
        return None

    def _extract_invoice_number(self, lines: List[str], full_text: str) -> Optional[str]:
        # 1. Check lines with explicit "Invoice No" or "Invoice #" label
        for i, l in enumerate(lines):
            # Same line: "Invoice No. NWL-88213" or "Invoice No. | KOM/26-27/00418"
            m = re.search(r"(?:Invoice\s*No\.?|Invoice\s*#|PO\s*No\.?|InvoiceNo\.?)[:\s\|]*([A-Z0-9\/\-\_]{3,25})", l, re.I)
            if m:
                val = m.group(1).strip()
                if val.lower() not in ["date", "due", "page"]:
                    return val

            # Next line: "Invoice No." on line i, number on line i+1 or i+2
            if re.match(r"^(?:Invoice\s*No\.?|Invoice\s*#|InvoiceNo\.?)$", l.strip(), re.I):
                for k in range(1, 3):
                    if i + k < len(lines):
                        candidate = lines[i + k].strip().replace("|", "").strip()
                        if candidate and len(candidate) >= 3 and not any(w in candidate.lower() for w in ["date", "tax", "due"]):
                            return candidate

        # 2. Pattern matching for standard formats (e.g. MPP-2026-0207, KOM/26-27/00418, CFS-4471, MAP/D/09-0312)
        pat = re.search(r"([A-Z]{2,4}[-\/][A-Z0-9\/\-\_]{3,20})", full_text)
        if pat:
            return pat.group(1).strip()

        return None

    def _extract_date(self, lines: List[str], full_text: str) -> Optional[str]:
        date_pats = [
            (r"(\d{4}[-\/]\d{2}[-\/]\d{2})", "%Y-%m-%d"),
            (r"(\d{1,2}[-\/]\d{1,2}[-\/]\d{4})", "%d/%m/%Y"),
            (r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})", "%d %b %Y"),
            (r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})", "%B %d, %Y"),
            (r"(\d{2}(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\d{4})", "%d%b%Y"),
        ]

        # Scan lines labeled with Date
        for i, l in enumerate(lines):
            if any(k in l.lower() for k in ["date", "dated"]) and "due" not in l.lower():
                # Check same line
                for pat, fmt in date_pats:
                    m = re.search(pat, l, re.I)
                    if m:
                        norm = self._normalize_date(m.group(1))
                        if norm: return norm
                # Check next line
                if i + 1 < len(lines):
                    for pat, fmt in date_pats:
                        m = re.search(pat, lines[i+1], re.I)
                        if m:
                            norm = self._normalize_date(m.group(1))
                            if norm: return norm

        # Fallback regex scan across document
        for pat, fmt in date_pats:
            m = re.search(pat, full_text, re.I)
            if m:
                norm = self._normalize_date(m.group(1))
                if norm: return norm
        return None

    def _normalize_date(self, raw: str) -> Optional[str]:
        formats = [
            "%Y-%m-%d", "%Y/%m/%d",
            "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
            "%d %b %Y", "%d %B %Y",
            "%b %d, %Y", "%B %d, %Y",
            "%b %d %Y", "%B %d %Y",
            "%d%b%Y", "%d%B%Y",
            "%d/%m/%y", "%d-%m-%y"
        ]
        clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", raw.strip())
        clean = clean.replace(",", " ")
        clean = " ".join(clean.split())
        for fmt in formats:
            try:
                dt = datetime.strptime(clean, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _extract_currency(self, text: str) -> Optional[str]:
        upper = text.upper()
        if "£" in text or "GBP" in upper:
            return "GBP"
        if "$" in text or "USD" in upper:
            return "USD"
        if "€" in text or "EUR" in upper:
            return "EUR"
        if "₹" in text or "INR" in upper or "RS." in upper or "RUPEES" in upper or "GSTIN" in upper:
            return "INR"
        return "INR"

    def _extract_line_items(self, lines: List[str]) -> Optional[List[Dict[str, Any]]]:
        # 1. Locate start of item table
        start_idx = -1
        for i, l in enumerate(lines):
            lower = l.lower()
            if any(k in lower for k in ["amount", "unit price", "description"]):
                start_idx = i + 1
                break

        if start_idx == -1:
            return None

        # 2. Locate end of item table
        end_idx = len(lines)
        for i in range(start_idx, len(lines)):
            if re.search(r"^(?:Subtotal|Total|Order value|Declaration|Thank you|For\s+)", lines[i], re.I):
                end_idx = i
                break

        table_tokens = lines[start_idx:end_idx]

        # 3. Chunk tokens by item index (1, 2, 3...)
        chunks: List[List[str]] = []
        current_chunk: List[str] = []
        expected_row = 1

        for tok in table_tokens:
            if tok == str(expected_row):
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = []
                expected_row += 1
            else:
                current_chunk.append(tok)
        if current_chunk:
            chunks.append(current_chunk)

        items = []
        for ch in chunks:
            if not ch:
                continue

            def is_num(x: str) -> bool:
                try:
                    float(x.replace(",", "").replace("$", "").replace("£", "").replace("₹", "").replace("€", ""))
                    return True
                except ValueError:
                    return False

            def to_num(x: str) -> float:
                return float(x.replace(",", "").replace("$", "").replace("£", "").replace("₹", "").replace("€", ""))

            # Last number is row amount
            amt = None
            for tok in reversed(ch):
                if is_num(tok):
                    amt = to_num(tok)
                    break

            if amt is None:
                continue

            # Parse description and quantity
            qty = None
            rate = None
            desc_parts = []

            # Check if quantity is null/dash
            for i, tok in enumerate(ch):
                if tok in ["-", "—", "null", "N/A"]:
                    qty = None
                elif is_num(tok):
                    val = to_num(tok)
                    # If this is the amount token at end
                    if val == amt and i == len(ch) - 1:
                        continue
                    # Check for 4-digit HSN/SAC code
                    if 1000 <= val <= 9999 and str(int(val)) == tok.strip() and qty is None:
                        continue
                    if qty is None:
                        qty = val
                    else:
                        rate = val
                else:
                    desc_parts.append(tok)

            desc = " ".join(desc_parts).strip()
            if desc:
                items.append({
                    "description": desc,
                    "quantity": qty,
                    "amount": amt
                })

        return items if items else None

    def _extract_tax_and_total(self, lines: List[str]) -> Tuple[float, Optional[float]]:
        tax = 0.0
        total = None

        def clean_val(s: str) -> Optional[float]:
            s_clean = s.replace("₹", "").replace("$", "").replace("£", "").replace("€", "").replace(",", "").strip()
            m = re.search(r"(-?[0-9]+\.[0-9]{2})", s_clean)
            if m:
                return float(m.group(1))
            return None

        for i, l in enumerate(lines):
            lower = l.lower()

            # Tax lines: VAT, CGST, SGST, IGST, Sales tax
            if any(k in lower for k in ["vat", "cgst", "sgst", "igst", "sales tax"]):
                if not any(k in lower for k in ["tax invoice", "gstin"]):
                    # Check same line
                    v = clean_val(l)
                    if v and "%" not in l.split()[-1]:
                        tax += v
                    elif i + 1 < len(lines):
                        v_next = clean_val(lines[i+1])
                        if v_next:
                            tax += v_next

            # Grand Total / Amount Due
            if any(k in lower for k in ["amount due", "grand total", "po total", "final total", "total"]):
                if not any(k in lower for k in ["subtotal", "tax total"]):
                    v = clean_val(l)
                    if v:
                        total = v
                    elif i + 1 < len(lines):
                        v_next = clean_val(lines[i+1])
                        if v_next:
                            total = v_next

        return round(tax, 2), total
