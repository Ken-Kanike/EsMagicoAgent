"""
Field matching rules (stated in the README and printed in the report).

is_invoice      exact boolean
vendor          case/punctuation-insensitive; legal suffixes canonicalised
                (Pvt Ltd = Private Limited, Ltd = Limited, Co = Company, ...);
                match if the canonical names are equal, or fuzz.ratio >= 90 on them.
                (No subset matching: "Acme" does NOT match "Acme Holdings Global".)
invoice_number  exact after trimming whitespace and upper-casing
invoice_date    exact ISO YYYY-MM-DD string
currency        exact ISO-4217 code (case-insensitive)
tax_total/total numeric, |pred - gt| <= 0.01 (strings like "1,200.00" are parsed first)
line_items      strict: same number of rows, in order, and every row matches
                (description fuzz >= 80 after normalisation, quantity equal or both null,
                amount within 0.01). Also reported: row-level precision / recall.
Both null       counts as a match for every field (non-invoices).
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from pipeline.normalizer import parse_number

FIELDS_TO_EVALUATE = [
    "is_invoice", "vendor", "invoice_number", "invoice_date",
    "currency", "line_items", "tax_total", "total",
]

AMOUNT_TOL = 0.01
QTY_TOL = 0.001
DESC_THRESHOLD = 80.0
VENDOR_THRESHOLD = 90.0

_SUFFIXES = [
    (r"\bprivate limited\b", "pvt ltd"), (r"\bpvt\.? ltd\.?\b", "pvt ltd"), (r"\bprivate ltd\b", "pvt ltd"),
    (r"\blimited\b", "ltd"), (r"\bincorporated\b", "inc"), (r"\bcompany\b", "co"),
    (r"\bcorporation\b", "corp"), (r"\bb\.\s?v\.?", "bv"), (r"\bl\.?l\.?p\.?\b", "llp"),
    (r"\bl\.?l\.?c\.?\b", "llc"), (r"\bg\.?m\.?b\.?h\.?\b", "gmbh"),
]


def _norm_text(s: Any) -> str:
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"[‘’“”'\"`]", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_vendor(s: Any) -> str:
    s = str(s or "").lower()
    for pat, rep in _SUFFIXES:
        s = re.sub(pat, rep, s)
    return _norm_text(s)


def vendor_matches(pred: Any, gt: Any) -> bool:
    a, b = canonical_vendor(pred), canonical_vendor(gt)
    return bool(a) and (a == b or fuzz.ratio(a, b) >= VENDOR_THRESHOLD)


def _num(v: Any) -> Optional[float]:
    return parse_number(v)


def row_matches(p: Dict[str, Any], g: Dict[str, Any]) -> Tuple[bool, List[str]]:
    problems = []
    pd, gd = _norm_text(p.get("description")), _norm_text(g.get("description"))
    if max(fuzz.ratio(pd, gd), fuzz.token_sort_ratio(pd, gd)) < DESC_THRESHOLD:
        problems.append("description")
    pq, gq = _num(p.get("quantity")), _num(g.get("quantity"))
    if (pq is None) != (gq is None) or (pq is not None and abs(pq - gq) > QTY_TOL):
        problems.append("quantity_null_vs_value" if (pq is None) != (gq is None) else "quantity_value")
    pa, ga = _num(p.get("amount")), _num(g.get("amount"))
    if pa is None or ga is None or abs(pa - ga) > AMOUNT_TOL:
        problems.append("amount_sign" if pa is not None and ga is not None and abs(pa + ga) <= AMOUNT_TOL else "amount")
    return (not problems), problems


def line_item_stats(pred: Any, gt: Any) -> Dict[str, Any]:
    """Order-preserving greedy alignment; returns strict match + row precision/recall + problems."""
    pred = pred if isinstance(pred, list) else []
    gt = gt if isinstance(gt, list) else []
    matched, problems = 0, []
    used = set()
    for gi, g in enumerate(gt):
        best = None
        for pi, p in enumerate(pred):
            if pi in used or not isinstance(p, dict):
                continue
            ok, probs = row_matches(p, g)
            if ok:
                best = (pi, [])
                break
            if best is None and pi == gi:
                best = (pi, probs)
        if best is not None and not best[1]:
            used.add(best[0])
            matched += 1
        elif best is not None:
            problems.extend(best[1])
        else:
            problems.append("row_missing")
    if len(pred) > len(gt):
        problems.append("extra_rows")
    strict = len(pred) == len(gt) and matched == len(gt) and all(
        row_matches(p, g)[0] for p, g in zip(pred, gt) if isinstance(p, dict))
    return {
        "strict": strict,
        "matched_rows": matched,
        "pred_rows": len(pred),
        "gt_rows": len(gt),
        "precision": matched / len(pred) if pred else (1.0 if not gt else 0.0),
        "recall": matched / len(gt) if gt else (1.0 if not pred else 0.0),
        "problems": sorted(set(problems)),
    }


def match_line_items(pred_items: Any, gt_items: Any) -> bool:
    if not isinstance(pred_items, list) or not isinstance(gt_items, list):
        return False
    return line_item_stats(pred_items, gt_items)["strict"]


def field_matches(field: str, pred: Any, gt: Any) -> bool:
    if pred is None and gt is None:
        return True
    if (pred is None) != (gt is None):
        return False
    if field == "is_invoice":
        return bool(pred) is bool(gt)
    if field == "vendor":
        return vendor_matches(pred, gt)
    if field == "invoice_number":
        return re.sub(r"\s+", "", str(pred)).upper() == re.sub(r"\s+", "", str(gt)).upper()
    if field == "invoice_date":
        return str(pred).strip() == str(gt).strip()
    if field == "currency":
        return str(pred).strip().upper() == str(gt).strip().upper()
    if field in ("tax_total", "total"):
        a, b = _num(pred), _num(gt)
        return a is not None and b is not None and abs(a - b) <= AMOUNT_TOL
    if field == "line_items":
        return match_line_items(pred, gt)
    return pred == gt


def calculate_document_metrics(prediction: Optional[Dict[str, Any]], ground_truth: Dict[str, Any]) -> Dict[str, bool]:
    pred = prediction or {}
    return {f: field_matches(f, pred.get(f), ground_truth.get(f)) for f in FIELDS_TO_EVALUATE}


def classify_error(field: str, pred: Any, gt: Any) -> str:
    """Data-derived cause tag for one mismatching field (used to group failures)."""
    if pred is None and gt is not None:
        return "missing_value"
    if field == "is_invoice":
        return "non_invoice_accepted" if pred else "invoice_rejected"
    if gt is None:
        return "value_on_non_invoice"
    if field == "invoice_date":
        p, g = str(pred), str(gt)
        if len(p) == 10 and len(g) == 10 and p[:4] == g[:4] and p[5:7] == g[8:10] and p[8:10] == g[5:7]:
            return "day_month_swapped"
        return "wrong_date_picked"
    if field == "tax_total":
        a, b = _num(pred), _num(gt)
        if a is not None and b is not None:
            if b and abs(a * 2 - b) <= AMOUNT_TOL:
                return "tax_half_counted (one of CGST/SGST)"
            return "tax_under_counted" if a < b else "tax_over_counted"
    if field == "total":
        return "total_misread"
    if field == "line_items":
        st = line_item_stats(pred, gt)
        if st["pred_rows"] != st["gt_rows"]:
            return f"row_count_mismatch ({st['pred_rows']} vs {st['gt_rows']})"
        return "row_" + "+".join(st["problems"]) if st["problems"] else "row_order"
    if field == "vendor":
        return "vendor_different_entity" if fuzz.partial_ratio(canonical_vendor(pred), canonical_vendor(gt)) < 70 else "vendor_spelling"
    if field == "invoice_number":
        a, b = re.sub(r"\W", "", str(pred)).upper(), re.sub(r"\W", "", str(gt)).upper()
        return "invoice_number_punctuation" if a == b else "invoice_number_misread"
    return f"{field}_mismatch"
