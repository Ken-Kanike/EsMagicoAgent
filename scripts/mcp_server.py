#!/usr/bin/env python3
"""
MCP server (stdio) exposing the invoice pipeline as agent tools.

Run directly:   python scripts/mcp_server.py
Claude Code:    claude mcp add invoice-pipeline -- python /abs/path/to/scripts/mcp_server.py
Claude Desktop / Cursor: see README "MCP server" (or the MCP page in the dashboard for a
ready-to-paste config with this machine's paths).

Tools (implemented once in pipeline/tools.py, also used by the dashboard's tool console):
  list_documents, extract_invoice, validate_invoice_json, list_templates,
  extract_with_template, get_latest_evaluation

Over MCP, extract_invoice / extract_with_template also accept an absolute `path`, because the
server runs locally under your own account.
"""
import json
import logging
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
# stdout is the MCP transport: send every log line to stderr.
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

from pipeline import tools  # noqa: E402

server = _Server("invoice-pipeline", instructions=(
    "Invoice extraction pipeline. Call list_documents to find doc_ids, then extract_invoice. "
    "Always surface needs_review and review_reasons to the user; never present flagged data as verified."))


def _call(name: str, **kwargs: Any) -> Dict[str, Any]:
    args = {k: v for k, v in kwargs.items() if v is not None}
    try:
        return tools.call_tool(name, args, allow_path=True)
    except Exception as e:  # report as tool output so the agent can recover
        return {"error": f"{type(e).__name__}: {e}"}


@server.tool(description=tools.TOOLS_BY_NAME["list_documents"].description)
def list_documents() -> Dict[str, Any]:
    return _call("list_documents")


@server.tool(description=tools.TOOLS_BY_NAME["extract_invoice"].description
             + " Pass doc_id, or an absolute file path.")
def extract_invoice(doc_id: Optional[str] = None, path: Optional[str] = None,
                    mode: Optional[str] = None) -> Dict[str, Any]:
    return _call("extract_invoice", doc_id=doc_id, path=path, mode=mode)


@server.tool(description=tools.TOOLS_BY_NAME["validate_invoice_json"].description)
def validate_invoice_json(data: Dict[str, Any]) -> Dict[str, Any]:
    return _call("validate_invoice_json", data=data)


@server.tool(description=tools.TOOLS_BY_NAME["list_templates"].description)
def list_templates() -> Dict[str, Any]:
    return _call("list_templates")


@server.tool(description=tools.TOOLS_BY_NAME["extract_with_template"].description
             + " Pass doc_id, or an absolute file path.")
def extract_with_template(template_id: str, doc_id: Optional[str] = None, path: Optional[str] = None,
                          mode: Optional[str] = None) -> Dict[str, Any]:
    return _call("extract_with_template", template_id=template_id, doc_id=doc_id, path=path, mode=mode)


@server.tool(description=tools.TOOLS_BY_NAME["get_latest_evaluation"].description)
def get_latest_evaluation() -> Dict[str, Any]:
    return _call("get_latest_evaluation")


def client_config() -> Dict[str, Any]:
    """Ready-to-paste config for Claude Desktop / Cursor (mcpServers block)."""
    return {"mcpServers": {"invoice-pipeline": {
        "command": sys.executable, "args": [str(ROOT / "scripts" / "mcp_server.py")]}}}


if __name__ == "__main__":
    if "--print-config" in sys.argv:
        print(json.dumps(client_config(), indent=2))
    else:
        server.run("stdio")
