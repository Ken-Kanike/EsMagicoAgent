import re
import json
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
from PIL import Image
from ai_backends.base import AIBackend
from pipeline.models import TokenUsage

class NoAIBackend(AIBackend):
    """
    Deterministic rule-based extractor using regular expressions, layout heuristics,
    and string normalization. Operates fully offline with zero AI API costs.
    """

    @property
    def name(self) -> str:
        return "No-AI (Rule-Based & Regex Engine)"

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
            model="deterministic-regex",
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

        currency = self._extract_currency(text)
        vendor = self._extract_vendor(text)
        invoice_number = self._extract_invoice_number(text)
        invoice_date = self._extract_date(text)
        line_items = self._extract_line_items(text)
        tax_total = self._extract_tax(text)
        total = self._extract_total(text)

        # Sanity check: If line items and tax exist but total is missing or out of balance
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
            "purchase order", "po no", "po-", "po date", "po total",
            "bank statement", "account statement", "harbor trust bank",
            "cover letter", "hiring manager", "dear hiring", "curriculum vitae", "resume",
            "bill of lading", "packing slip", "delivery challan"
        ]
        for cue in non_invoice_cues:
            if cue in lower:
                # If it's explicitly titled purchase order or account statement, it's NOT an invoice
                if any(strong in lower for strong in ["purchase order", "account statement", "hiring manager", "cover letter"]):
                    return False

        invoice_cues = [
            "tax invoice", "invoice", "inv no", "invoice no", "invoice #",
            "rechnung", "facture", "bill to", "invoice date", "amount payable", "total due"
        ]
        return any(cue in lower for cue in invoice_cues)

    def _extract_vendor(self, text: str) -> Optional[str]:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        # Typically vendor is within the first 6 non-empty lines
        company_indicators = [
            "ltd", "limited", "pvt", "llp", "inc", "corp", "corporation",
            "stationers", "studio", "logistics", "supplies", "associates",
            "seafoods", "mart", "store", "services", "solutions", "hardware"
        ]

        for line in lines[:8]:
            lower = line.lower()
            if any(term in lower for term in ["invoice", "tax invoice", "bill to", "ship to", "page", "date"]):
                continue
            if any(indicator in lower for indicator in company_indicators):
                return line

        # Fallback to the first capitalized line
        for line in lines[:4]:
            if line and not any(k in line.lower() for k in ["invoice", "bill to", "date"]):
                return line
        return None

    def _extract_invoice_number(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:invoice\s*(?:no|number|#)?[:\s]+)([A-Z0-9\/\-\_]+)",
            r"(?:inv\s*(?:no|#)?[:\s]+)([A-Z0-9\/\-\_]+)",
            r"([A-Z]{2,4}[-\/][A-Z0-9\/\-\_]{3,20})"
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                val = match.group(1).strip()
                if len(val) >= 3 and not val.lower().startswith("date"):
                    return val
        return None

    def _extract_date(self, text: str) -> Optional[str]:
        # Date patterns
        patterns = [
            r"(?:invoice\s*date|date)[:\s]+([0-9]{4}[-\/][0-9]{2}[-\/][0-9]{2})",  # YYYY-MM-DD
            r"(?:invoice\s*date|date)[:\s]+([0-9]{1,2}[-\/\.][0-9]{1,2}[-\/\.][0-9]{2,4})", # DD/MM/YYYY or MM/DD/YYYY
            r"(?:invoice\s*date|date)[:\s]+([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})", # DD Month YYYY
            r"([0-9]{4}[-\/][0-9]{2}[-\/][0-9]{2})",
            r"([0-9]{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+[0-9]{4})"
        ]

        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                raw_date = match.group(1).strip()
                normalized = self._normalize_date(raw_date)
                if normalized:
                    return normalized
        return None

    def _normalize_date(self, raw: str) -> Optional[str]:
        formats = [
            "%Y-%m-%d", "%Y/%m/%d",
            "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
            "%d %b %Y", "%d %B %Y",
            "%b %d, %Y", "%B %d, %Y",
            "%d/%m/%y", "%d-%m-%y"
        ]
        clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", raw)
        for fmt in formats:
            try:
                dt = datetime.strptime(clean, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _extract_currency(self, text: str) -> Optional[str]:
        upper = text.upper()
        if "₹" in text or "INR" in upper or "RS." in upper or "RUPEES" in upper:
            return "INR"
        if "£" in text or "GBP" in upper:
            return "GBP"
        if "$" in text or "USD" in upper:
            return "USD"
        if "€" in text or "EUR" in upper:
            return "EUR"
        return "USD"

    def _extract_line_items(self, text: str) -> Optional[List[Dict[str, Any]]]:
        lines = text.split("\n")
        items = []

        # Find rows with description and numeric amount at end
        # E.g. "Exam pad A4 (200 pages)   150   8700.0" or "Pallet freight Manchester 3 435.0"
        row_pattern = re.compile(
            r"^(?P<desc>.+?)\s+(?:(?P<qty>\d+(?:\.\d+)?)\s+)?(?:(?P<rate>\d+(?:\.\d+)?)\s+)?(?P<amt>-?\d+(?:,\d{3})*(?:\.\d{2})?)$"
        )

        in_table = False
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            lower = line_str.lower()

            if any(h in lower for h in ["description", "item", "particulars", "qty", "amount"]):
                in_table = True
                continue

            if in_table and any(t in lower for t in ["subtotal", "tax total", "total", "cgst", "sgst", "vat"]):
                in_table = False
                break

            if in_table:
                # Try parsing line
                # Look for amount at end of string
                parts = line_str.split()
                if len(parts) >= 2:
                    try:
                        amt_str = parts[-1].replace(",", "").replace("$", "").replace("£", "").replace("₹", "")
                        amt = float(amt_str)
                        # Check if second to last is quantity
                        qty = None
                        desc_parts = parts[:-1]
                        if len(parts) >= 3:
                            try:
                                possible_qty = float(parts[-2])
                                if possible_qty > 0 and possible_qty < 100000:
                                    qty = possible_qty
                                    desc_parts = parts[:-2]
                            except ValueError:
                                pass

                        desc = " ".join(desc_parts).strip()
                        if desc and not any(k in desc.lower() for k in ["total", "tax", "subtotal", "bank", "page"]):
                            items.append({
                                "description": desc,
                                "quantity": qty,
                                "amount": amt
                            })
                    except ValueError:
                        continue

        return items if items else None

    def _extract_tax(self, text: str) -> Optional[float]:
        patterns = [
            r"(?:tax\s*total|total\s*tax|tax|gst|vat|cgst\s*\+\s*sgst)[:\s]+(?:[\$£₹INR\s]*)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
            r"(?:tax\s*amount)[:\s]+(?:[\$£₹INR\s]*)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)"
        ]
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                try:
                    val = float(match.group(1).replace(",", ""))
                    return val
                except ValueError:
                    continue
        return 0.0

    def _extract_total(self, text: str) -> Optional[float]:
        patterns = [
            r"(?:grand\s*total|total\s*amount|final\s*total|amount\s*payable|total)[:\s]+(?:[\$£₹INR\s]*)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)",
            r"(?:total\s*due)[:\s]+(?:[\$£₹INR\s]*)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)"
        ]
        # Search from bottom to top to get the final total
        lines = text.split("\n")[::-1]
        for line in lines:
            for pat in patterns:
                match = re.search(pat, line, re.IGNORECASE)
                if match:
                    try:
                        return float(match.group(1).replace(",", ""))
                    except ValueError:
                        continue
        return None
