"""Agent tool layer shared by the MCP server and /api/mcp/call."""
import pytest

from pipeline import tools


def test_registry_matches_schemas():
    names = [t["name"] for t in tools.describe_tools()]
    assert names == ["list_documents", "extract_invoice", "validate_invoice_json", "list_templates",
                     "extract_with_template", "get_latest_evaluation"]
    for t in tools.describe_tools():
        assert t["inputSchema"]["type"] == "object" and t["description"]


def test_unknown_tool_and_argument_rejected():
    with pytest.raises(ValueError, match="Unknown tool"):
        tools.call_tool("rm_rf", {})
    with pytest.raises(ValueError, match="Unknown argument"):
        tools.call_tool("list_documents", {"evil": 1})


def test_paths_refused_unless_allowed(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")
    with pytest.raises(ValueError, match="not accepted"):
        tools.resolve_document(path=str(f))
    assert tools.resolve_document(path=str(f), allow_path=True) == f
    with pytest.raises(ValueError):
        tools.resolve_document(doc_id="../../etc/passwd")


def test_validate_invoice_json_tool():
    out = tools.call_tool("validate_invoice_json", {"data": {
        "is_invoice": True, "vendor": "A", "invoice_number": "1", "invoice_date": "2026-01-01",
        "currency": "inr", "line_items": [{"description": "x", "quantity": None, "amount": "1,000.00"}],
        "tax_total": 180, "total": 1180}})
    assert out["valid"] and out["normalized"]["currency"] == "INR"
    assert out["normalized"]["line_items"][0]["amount"] == 1000.0
