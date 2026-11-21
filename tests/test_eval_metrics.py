import pytest
from eval.metrics import field_matches, match_line_items

def test_vendor_fuzzy_matching():
    # Minor variations in punctuation & entity suffix should pass
    assert field_matches("vendor", "Northwind Logistics Ltd", "Northwind Logistics Ltd.")
    assert field_matches("vendor", "Kaveri Office Mart Pvt Ltd", "Kaveri Office Mart Private Limited")
    assert not field_matches("vendor", "Northwind Logistics", "Completely Different Company")

def test_invoice_date_matching():
    assert field_matches("invoice_date", "2026-04-08", "2026-04-08")
    assert not field_matches("invoice_date", "08/04/2026", "2026-04-08")

def test_numeric_tolerance():
    assert field_matches("total", 683.4, 683.40)
    assert field_matches("total", 683.42, 683.40) # within 0.05
    assert not field_matches("total", 683.50, 683.40) # outside 0.05

def test_line_items_matching():
    pred = [
        {"description": "A4 Copier Paper", "quantity": 40.0, "amount": 11560.0},
        {"description": "Whiteboard Markers", "quantity": 12.0, "amount": 2580.0}
    ]
    gt = [
        {"description": "A4 copier paper 75 GSM (ream)", "quantity": 40.0, "amount": 11560.0},
        {"description": "Whiteboard markers (box of 10)", "quantity": 12.0, "amount": 2580.0}
    ]
    assert match_line_items(pred, gt)
