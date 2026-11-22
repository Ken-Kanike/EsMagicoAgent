"""
Deterministic clean-up applied to every model answer before validation.
It never invents values; it only converts formats (e.g. "1.136,25" -> 1136.25,
"₹" -> "INR", "14 Mar 2026" -> "2026-03-14").
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pipeline.models import NON_INVOICE_FIELDS

_CURRENCY_SYMBOLS = {
    "₹": "INR", "RS": "INR", "RS.": "INR", "INR": "INR", "RUPEES": "INR",
    "$": "USD", "US$": "USD", "USD": "USD",
    "€": "EUR", "EUR": "EUR", "EURO": "EUR",
    "£": "GBP", "GBP": "GBP",
    "¥": "JPY", "JPY": "JPY", "AED": "AED", "SGD": "SGD", "AUD": "AUD", "CAD": "CAD", "CHF": "CHF",
}

_DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%d %b, %Y",
    "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y",
    "%d.%m.%Y",  # dotted numeric dates are day-first in practice (DE/NL/EU)
]


def parse_number(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s.lower() in ("null", "none", "-", "—", "n/a", "na"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.count("-") and not s.startswith("-"):
        s = s.replace("-", "")
    if s.startswith("-"):
        neg, s = True, s[1:]
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):          # 1.136,25  (European)
            s = s.replace(".", "").replace(",", ".")
        else:                                     # 1,136.25 / 12,00,000.00
            s = s.replace(",", "")
    elif "," in s:
        tail = s.split(",")[-1]
        if len(tail) == 2 and s.count(",") == 1:  # 340,00 -> decimal comma
            s = s.replace(",", ".")
        else:                                     # 1,200 -> thousands
            s = s.replace(",", "")
    elif s.count(".") > 1:                        # 1.200.000 -> thousands dots
        s = s.replace(".", "")
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


def normalize_currency(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().upper()
    if not s:
        return None
    if s in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[s]
    if re.fullmatch(r"[A-Z]{3}", s):
        return s
    for sym, code in _CURRENCY_SYMBOLS.items():
        if sym in s:
            return code
    return s


def normalize_date(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    clean = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    clean = re.sub(r"\s+", " ", clean.replace(",", ", ")).replace(" ,", ",").strip()
    for fmt in _DATE_FORMATS:
        for cand in (clean, clean.replace(",", "")):
            try:
                return datetime.strptime(cand, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return s  # leave as-is; the validator will flag it


def _clean_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _to_bool(v: Any) -> Any:
    if isinstance(v, str):
        if v.strip().lower() in ("true", "yes", "1"):
            return True
        if v.strip().lower() in ("false", "no", "0"):
            return False
    return v


def normalize_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data
    # some models wrap the answer: {"invoice": {...}}
    if "is_invoice" not in data and len(data) == 1 and isinstance(next(iter(data.values())), dict):
        data = next(iter(data.values()))

    out: Dict[str, Any] = {"is_invoice": _to_bool(data.get("is_invoice"))}
    if out["is_invoice"] is False:
        out.update({k: None for k in NON_INVOICE_FIELDS})
        return out

    out["vendor"] = _clean_str(data.get("vendor"))
    inv = _clean_str(data.get("invoice_number"))
    out["invoice_number"] = re.sub(r"^(?:invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*)", "", inv, flags=re.I) if inv else None
    out["invoice_date"] = normalize_date(data.get("invoice_date"))
    out["due_date"] = normalize_date(data.get("due_date"))  # helper only; dropped by the schema
    out["currency"] = normalize_currency(data.get("currency"))

    items = data.get("line_items")
    if isinstance(items, list):
        rows: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            amt = parse_number(it.get("amount"))
            desc = _clean_str(it.get("description"))
            if amt is None and desc is None:
                continue
            rows.append({
                "description": desc or "",
                "quantity": parse_number(it.get("quantity")),
                "amount": amt if amt is not None else it.get("amount"),
                "unit_price": parse_number(it.get("unit_price")),  # helper only; dropped by the schema
            })
        out["line_items"] = rows
    else:
        out["line_items"] = items

    out["tax_total"] = parse_number(data.get("tax_total"))
    out["total"] = parse_number(data.get("total"))
    return out
