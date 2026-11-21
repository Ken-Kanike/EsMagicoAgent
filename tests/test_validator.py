import pytest
from pipeline.validator import InvoiceValidator
from pipeline.models import InvoiceSchema, LineItem

def test_valid_invoice_validation():
    validator = InvoiceValidator(tolerance=0.05)
    payload = {
        "is_invoice": True,
        "vendor": "Acme Supplies Pvt Ltd",
        "invoice_number": "INV-2041",
        "invoice_date": "2026-03-14",
        "currency": "INR",
        "line_items": [
            {"description": "A4 Paper Reams", "quantity": 10.0, "amount": 3200.0}
        ],
        "tax_total": 576.0,
        "total": 3776.0
    }
    obj, issues = validator.validate(payload)
    assert obj is not None
    assert len(issues) == 0
    assert obj.total == 3776.0

def test_non_invoice_all_null_valid():
    validator = InvoiceValidator()
    payload = {
        "is_invoice": False,
        "vendor": None,
        "invoice_number": None,
        "invoice_date": None,
        "currency": None,
        "line_items": None,
        "tax_total": None,
        "total": None
    }
    obj, issues = validator.validate(payload)
    assert obj is not None
    assert len(issues) == 0
    assert obj.is_invoice is False

def test_non_invoice_with_vendor_fails():
    validator = InvoiceValidator()
    payload = {
        "is_invoice": False,
        "vendor": "Some Random Vendor",
        "invoice_number": None,
        "invoice_date": None,
        "currency": None,
        "line_items": None,
        "tax_total": None,
        "total": None
    }
    obj, issues = validator.validate(payload)
    assert obj is None or len(issues) > 0

def test_arithmetic_mismatch_detected():
    validator = InvoiceValidator(tolerance=0.05)
    payload = {
        "is_invoice": True,
        "vendor": "Test Corp",
        "invoice_number": "T-100",
        "invoice_date": "2026-01-01",
        "currency": "USD",
        "line_items": [
            {"description": "Consulting", "quantity": 1.0, "amount": 100.0}
        ],
        "tax_total": 10.0,
        "total": 200.0  # Mismatch: 100 + 10 = 110 != 200
    }
    obj, issues = validator.validate(payload)
    assert any("Arithmetic mismatch" in issue for issue in issues)

def test_fractional_quantity_and_negative_discount():
    validator = InvoiceValidator(tolerance=0.05)
    payload = {
        "is_invoice": True,
        "vendor": "Fresh Foods Co",
        "invoice_number": "FF-991",
        "invoice_date": "2026-05-12",
        "currency": "INR",
        "line_items": [
            {"description": "King Fish (kg)", "quantity": 12.5, "amount": 11500.0},
            {"description": "Early Bird Discount", "quantity": None, "amount": -500.0}
        ],
        "tax_total": 550.0,
        "total": 11550.0 # 11500 - 500 + 550 = 11550
    }
    obj, issues = validator.validate(payload)
    assert len(issues) == 0
    assert obj.total == 11550.0
