"""Tests for the matching rules documented in eval/metrics.py and the README."""
from eval.metrics import classify_error, field_matches, line_item_stats, match_line_items


def test_vendor_fuzzy_matching():
    # Punctuation, case and legal-suffix variations match
    assert field_matches("vendor", "Northwind Logistics Ltd", "Northwind Logistics Ltd.")
    assert field_matches("vendor", "Kaveri Office Mart Pvt Ltd", "Kaveri Office Mart Private Limited")
    assert field_matches("vendor", "COASTAL FRESH SEAFOODS", "Coastal Fresh Seafoods")
    assert not field_matches("vendor", "Northwind Logistics", "Completely Different Company")
    # No subset matching
    assert not field_matches("vendor", "Acme", "Acme Holdings Global")


def test_invoice_date_matching():
    assert field_matches("invoice_date", "2026-04-08", "2026-04-08")
    assert not field_matches("invoice_date", "08/04/2026", "2026-04-08")


def test_numeric_tolerance():
    assert field_matches("total", 683.4, 683.40)
    assert field_matches("total", 683.41, 683.40)      # within 0.01
    assert not field_matches("total", 683.42, 683.40)  # outside 0.01
    assert field_matches("total", "1,200.00", 1200.0)  # strings are parsed


def test_line_items_matching():
    pred = [
        {"description": "A4 copier paper 75 GSM, ream", "quantity": 40.0, "amount": 11560.0},
        {"description": "Whiteboard Markers (box of 10)", "quantity": 12.0, "amount": 2580.0},
    ]
    gt = [
        {"description": "A4 copier paper 75 GSM (ream)", "quantity": 40.0, "amount": 11560.0},
        {"description": "Whiteboard markers (box of 10)", "quantity": 12.0, "amount": 2580.0},
    ]
    assert match_line_items(pred, gt)


def test_line_items_truncated_description_fails():
    pred = [{"description": "A4 Copier Paper", "quantity": 40.0, "amount": 11560.0}]
    gt = [{"description": "A4 copier paper 75 GSM (ream) - bright white", "quantity": 40.0, "amount": 11560.0}]
    assert not match_line_items(pred, gt)


def test_null_quantity_rule():
    gt = [{"description": "Delivery charge", "quantity": None, "amount": 250.0}]
    assert match_line_items([{"description": "Delivery charge", "quantity": None, "amount": 250.0}], gt)
    st = line_item_stats([{"description": "Delivery charge", "quantity": 1.0, "amount": 250.0}], gt)
    assert not st["strict"]
    assert "quantity_null_vs_value" in st["problems"]


def test_row_precision_recall():
    gt = [{"description": "A", "quantity": 1, "amount": 10.0}, {"description": "B", "quantity": 1, "amount": 20.0}]
    st = line_item_stats([{"description": "A", "quantity": 1, "amount": 10.0}], gt)
    assert st["precision"] == 1.0 and st["recall"] == 0.5 and not st["strict"]


def test_classify_error_tags():
    assert classify_error("tax_total", 9844.8, 19689.6).startswith("tax_half_counted")
    assert classify_error("invoice_date", "2026-08-04", "2026-04-08") == "day_month_swapped"
    assert classify_error("total", None, 100.0) == "missing_value"
