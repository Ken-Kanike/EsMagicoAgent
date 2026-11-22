import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from config.settings import settings
from pipeline.models import ExtractionResult


def _atomic_write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def write_output(file_stem: str, data: Dict[str, Any], output_dir: Optional[Path] = None) -> Path:
    """Write the schema-only JSON for one document (outputs/<stem>.json)."""
    target_dir = output_dir or settings.resolve_path(settings.outputs_dir)
    return _atomic_write_json(target_dir / f"{file_stem}.json", data)


def read_output(file_stem: str, output_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    target_dir = output_dir or settings.resolve_path(settings.outputs_dir)
    out_file = target_dir / f"{file_stem}.json"
    if not out_file.exists():
        return None
    with open(out_file, "r", encoding="utf-8") as f:
        return json.load(f)


def result_metadata(r: ExtractionResult) -> Dict[str, Any]:
    return {
        "file": r.file,
        "needs_review": r.needs_review,
        "review_reasons": r.review_reasons,
        "error": r.error,
        "error_type": r.error_type,
        "backend": r.backend,
        "attempts": r.attempts,
        "elapsed_s": r.elapsed_s,
        "cached": r.cached,
        "tokens_in": r.cost.tokens_in if r.cost else 0,
        "tokens_out": r.cost.tokens_out if r.cost else 0,
        "cost_usd": r.cost.cost_usd if r.cost else 0.0,
        "model": r.cost.model if r.cost else None,
    }


def write_run_metadata(results: Iterable[ExtractionResult], name: str = "run_metadata") -> Path:
    """Side-car with review flags, reasons, tokens and cost (kept out of the schema-only outputs)."""
    rows = [result_metadata(r) for r in results]
    return _atomic_write_json(settings.resolve_path("reports") / f"{name}.json", rows)
