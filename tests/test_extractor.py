"""
Extractor behaviour with a scripted fake LLM (no network): corrective retries, JSON repair,
API failures, bad input files, and the PII shield. These are the paths the brief cares about
("do not silently pass bad data on", "handle bad inputs") that the labelled eval can't exercise.
"""
import json
from pathlib import Path
from typing import List

import pytest

from ai_backends.base import AIBackend, BackendError
from pipeline.extractor import InvoiceExtractor, parse_llm_json
from pipeline.models import TokenUsage
from pipeline.pii_shield import PIIShield

SAMPLE = Path(__file__).resolve().parent.parent / "Es Magico - AI Intern Assignment - Sample Pack" / "labelled"
L01 = SAMPLE / "L01.pdf"

GOOD = {"is_invoice": True, "vendor": "Northwind Logistics Ltd", "invoice_number": "NWL-1",
        "invoice_date": "2026-04-08", "currency": "GBP",
        "line_items": [{"description": "Freight", "quantity": 2, "unit_price": 50, "amount": 100.0}],
        "tax_total": 20.0, "total": 120.0}


class FakeBackend(AIBackend):
    """Returns scripted replies in order; an Exception instance in the script is raised."""
    mode = "fake"

    def __init__(self, replies: List):
        self.replies = list(replies)
        self.calls: List[list] = []

    @property
    def name(self) -> str:
        return "Fake"

    @property
    def supports_vision(self) -> bool:
        return False

    def model_for(self, has_images: bool) -> str:
        return "fake-model"

    def chat(self, messages, json_mode=True, max_tokens=4096):
        self.calls.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return (r if isinstance(r, str) else json.dumps(r)), TokenUsage("fake", "fake-model", "fake-model", 1000, 200)


def _extract(replies):
    be = FakeBackend(replies)
    return InvoiceExtractor(be, use_cache=False).extract(L01), be


pytestmark = pytest.mark.skipif(not L01.exists(), reason="sample pack not present")


def test_happy_path_single_call():
    res, be = _extract([GOOD])
    assert len(be.calls) == 1 and res.attempts == 1
    assert res.data["total"] == 120.0 and not res.needs_review
    assert "unit_price" not in res.data["line_items"][0]       # helper field dropped from output
    assert res.cost.tokens_in == 1000 and res.cost.tokens_out == 200


def test_arithmetic_error_triggers_corrective_retry():
    bad = dict(GOOD, total=999.0)
    res, be = _extract([bad, GOOD])
    assert len(be.calls) == 2
    # the retry message carries the validator's error back to the model
    assert "Arithmetic mismatch" in json.dumps(be.calls[1])
    assert res.data["total"] == 120.0 and not res.needs_review


def test_unfixable_error_is_flagged_not_passed():
    bad = dict(GOOD, total=999.0)
    res, be = _extract([bad, bad, bad])
    assert res.needs_review
    assert any("Arithmetic mismatch" in r for r in res.review_reasons)


def test_invalid_json_is_repaired_once():
    res, be = _extract(["not json at all", GOOD])
    assert len(be.calls) == 2 and res.data["vendor"] == "Northwind Logistics Ltd"


def test_invalid_json_twice_is_an_error_result():
    res, _ = _extract(["nope", "still nope"])
    assert res.error_type == "unparseable" and res.data is None and res.needs_review


def test_api_failure_is_graceful():
    res, _ = _extract([BackendError("timeout after retries")])
    assert res.error_type == "backend_error" and "timeout" in res.error and res.needs_review


def test_non_invoice_forces_nulls():
    res, _ = _extract([{"is_invoice": False, "vendor": "Some Bank", "total": 5}])
    assert res.data["is_invoice"] is False
    assert all(res.data[k] is None for k in res.data if k != "is_invoice")


@pytest.mark.parametrize("content,suffix,etype", [
    (b"", ".pdf", "corrupt_file"),
    (b"%PDF-1.7\n garbage", ".pdf", "corrupt_file"),
    (b"\x89PNG\r\n\x1a\n broken", ".png", "corrupt_file"),
    (b"hello", ".docx", "unsupported"),
])
def test_bad_files_never_reach_the_model(tmp_path, content, suffix, etype):
    f = tmp_path / f"bad{suffix}"
    f.write_bytes(content)
    be = FakeBackend([])
    res = InvoiceExtractor(be, use_cache=False).extract(f)
    assert res.error_type == etype and res.needs_review and not be.calls


def test_parse_llm_json_variants():
    assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_llm_json('Here you go: {"vendor": "Bob\'s Cafe"} thanks')["vendor"] == "Bob's Cafe"
    with pytest.raises(ValueError):
        parse_llm_json("no braces here")


def test_pii_shield_masks_by_position_and_restores():
    text = "Invoice No 1234567890\nAccount No: 1234567890\nEmail: ap@vendor.example"
    r = PIIShield.sanitize_text(text, mask_enabled=True)
    assert r.masked_text.startswith("Invoice No 1234567890")      # invoice number untouched
    assert "ap@vendor.example" not in r.masked_text
    assert PIIShield.restore_in_obj({"x": r.masked_text}, r.entity_map)["x"] == text
