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


def _inv(**kw):
    d = {"is_invoice": True, "vendor": "Lakeside Printing Co", "invoice_number": "LP-10932",
         "invoice_date": "2026-10-21", "due_date": "2026-11-20", "currency": "GBP",
         "line_items": [{"description": "Delivery", "quantity": None, "amount": 100.0}],
         "tax_total": 0.0, "total": 100.0}
    d.update(kw)
    return d


def test_due_date_consistency():
    v = InvoiceValidator()
    assert v.check(_inv()).ok
    # misread year on a scan: 2026 -> 2025
    assert any("days before due_date" in e for e in v.check(_inv(invoice_date="2025-10-21")).errors)
    # issue date after due date
    assert any("AFTER due_date" in e for e in v.check(_inv(invoice_date="2026-12-01")).errors)
    # helper field never reaches the output
    assert "due_date" not in v.check(_inv()).obj.model_dump()


def test_required_fields_flagged():
    errs = InvoiceValidator().check(_inv(total=None)).errors
    assert any("'total' is missing" in e for e in errs)
