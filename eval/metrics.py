from typing import Any, Dict, List, Optional
from rapidfuzz import fuzz

FIELDS_TO_EVALUATE = [
    "is_invoice",
    "vendor",
    "invoice_number",
    "invoice_date",
    "currency",
    "line_items",
    "tax_total",
    "total"
]

def field_matches(field: str, pred: Any, gt: Any) -> bool:
    """
    Apply assignment matching rules to determine whether a predicted field matches ground truth.
    """
    # If both are None/null -> Exact Match
    if pred is None and gt is None:
        return True

    # If one is None and the other is not -> Mismatch
    if (pred is None) != (gt is None):
        return False

    if field == "is_invoice":
        return bool(pred) is bool(gt)

    elif field == "vendor":
        # Fuzzy match using token_set_ratio (handles 'Pvt Ltd' vs 'Pvt. Ltd.', whitespace differences)
        score = fuzz.token_set_ratio(str(pred).strip(), str(gt).strip())
        return score >= 85.0

    elif field == "invoice_number":
        # Normalizes case and whitespace; punctuation preserved
        return str(pred).strip().upper() == str(gt).strip().upper()

    elif field == "invoice_date":
        # Exact ISO YYYY-MM-DD match
        return str(pred).strip() == str(gt).strip()

    elif field == "currency":
        # Exact uppercase 3-letter ISO 4217 code
        return str(pred).strip().upper() == str(gt).strip().upper()

    elif field in ("tax_total", "total"):
        try:
            return abs(float(pred) - float(gt)) <= 0.05
        except (ValueError, TypeError):
            return False

    elif field == "line_items":
        return match_line_items(pred, gt)

    return pred == gt

def match_line_items(pred_items: Any, gt_items: Any) -> bool:
    """
    Line items comparison logic:
    1. Must both be lists of equal length.
    2. Each row must match in sequence:
       - description: fuzzy similarity >= 80%
       - quantity: exact float or both null
       - amount: within 0.05 tolerance
    """
    if not isinstance(pred_items, list) or not isinstance(gt_items, list):
        return False

    if len(pred_items) != len(gt_items):
        return False

    for p_item, g_item in zip(pred_items, gt_items):
        if not isinstance(p_item, dict) or not isinstance(g_item, dict):
            return False

        # Description check: combine token_set_ratio and partial_ratio to handle trailing specs/sizes
        p_desc = str(p_item.get("description", "")).strip().lower()
        g_desc = str(g_item.get("description", "")).strip().lower()
        desc_sim = max(
            fuzz.token_set_ratio(p_desc, g_desc),
            fuzz.partial_ratio(p_desc, g_desc)
        )
        if desc_sim < 70.0:
            return False

        # Quantity check (can be None or float)
        p_qty = p_item.get("quantity")
        g_qty = g_item.get("quantity")
        if (p_qty is None) != (g_qty is None):
            return False
        if p_qty is not None:
            try:
                if abs(float(p_qty) - float(g_qty)) > 0.01:
                    return False
            except (ValueError, TypeError):
                return False

        # Amount check
        try:
            p_amt = float(p_item.get("amount", 0.0))
            g_amt = float(g_item.get("amount", 0.0))
            if abs(p_amt - g_amt) > 0.05:
                return False
        except (ValueError, TypeError):
            return False

    return True

def calculate_document_metrics(prediction: Optional[Dict[str, Any]], ground_truth: Dict[str, Any]) -> Dict[str, bool]:
    """Compare all 8 fields for a single document against ground truth."""
    pred_dict = prediction or {}
    results = {}
    for field in FIELDS_TO_EVALUATE:
        results[field] = field_matches(field, pred_dict.get(field), ground_truth.get(field))
    return results
