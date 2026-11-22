#!/usr/bin/env python3
"""
Extract one document to schema JSON on stdout:

    python scripts/extract.py invoice.pdf > out.json

Status / review messages go to stderr so stdout stays pure JSON.
Exit codes: 0 ok, 1 unreadable input or model failure, 2 backend not configured, 3 ok but flagged for review
(use --strict to get exit 3; by default flagged documents exit 0).
"""
import json
import logging
import sys
import warnings
from pathlib import Path

import typer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore", category=FutureWarning)

from ai_backends.base import BackendNotConfigured  # noqa: E402
from ai_backends.router import get_backend  # noqa: E402
from pipeline.extractor import InvoiceExtractor  # noqa: E402
from pipeline.output_writer import write_output  # noqa: E402

app = typer.Typer(add_completion=False)


def _err(msg: str):
    print(msg, file=sys.stderr)


@app.command()
def extract(
    file_path: Path = typer.Argument(..., help="PDF or image file"),
    mode: str = typer.Option(None, "--mode", "-m", help="groq | no_ai | openai | gemini | local"),
    save: bool = typer.Option(False, "--save/--no-save", help="Also write outputs/<name>.json"),
    meta: bool = typer.Option(False, "--meta", help="Print review flag, reasons, tokens and cost too"),
    cache: bool = typer.Option(True, "--cache/--no-cache"),
    strict: bool = typer.Option(False, "--strict", help="Exit 3 when the document needs review"),
):
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        extractor = InvoiceExtractor(get_backend(mode), use_cache=cache)
    except BackendNotConfigured as e:
        _err(f"ERROR: {e}")
        raise typer.Exit(2)

    res = extractor.extract(file_path)
    if res.error:
        _err(f"ERROR ({res.error_type}): {res.error}")
        print(json.dumps({"error": res.error, "error_type": res.error_type, "needs_review": True}, indent=2))
        raise typer.Exit(1)

    if save:
        _err(f"saved {write_output(file_path.stem, res.data)}")
    if res.needs_review:
        _err("NEEDS REVIEW: " + " | ".join(res.review_reasons))
    if res.cost:
        _err(f"{res.backend}: {res.cost.calls} call(s), {res.cost.tokens_in} in / {res.cost.tokens_out} out tokens, "
             f"${res.cost.cost_usd:.5f} list price, {res.elapsed_s:.1f}s{' (cached)' if res.cached else ''}")

    payload = res.data
    if meta:
        payload = {"data": res.data, "needs_review": res.needs_review, "review_reasons": res.review_reasons,
                   "tokens_in": res.cost.tokens_in if res.cost else 0,
                   "tokens_out": res.cost.tokens_out if res.cost else 0,
                   "cost_usd": res.cost.cost_usd if res.cost else 0.0}
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if strict and res.needs_review:
        raise typer.Exit(3)


if __name__ == "__main__":
    app()
