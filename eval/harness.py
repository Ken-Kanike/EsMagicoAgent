"""Evaluation harness: run the extractor on L01..L10 and compare field by field with ground truth."""
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_backends.router import get_backend
from config.settings import settings
from eval.metrics import (FIELDS_TO_EVALUATE, calculate_document_metrics, classify_error,
                          line_item_stats)
from pipeline.batch_runner import run_many
from pipeline.extractor import InvoiceExtractor
from pipeline.output_writer import write_output, write_run_metadata


@dataclass
class DocumentEvalRecord:
    doc_id: str
    file_name: str
    is_success: bool
    field_matches: Dict[str, bool]
    predicted: Optional[Dict[str, Any]]
    ground_truth: Dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    elapsed_s: float = 0.0
    needs_review: bool = False
    issues: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)       # field -> cause tag
    line_items: Dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    error: Optional[str] = None


@dataclass
class EvalSummary:
    mode: str
    total_docs: int
    field_accuracy: Dict[str, float]
    field_correct_counts: Dict[str, int]
    overall_accuracy: float
    document_records: List[DocumentEvalRecord]
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    avg_cost_per_doc: float
    wall_time_s: float = 0.0
    line_item_row_precision: float = 0.0
    line_item_row_recall: float = 0.0
    docs_fully_correct: int = 0
    error_groups: Dict[str, List[str]] = field(default_factory=dict)
    review: Dict[str, Any] = field(default_factory=dict)
    pricing: Dict[str, Any] = field(default_factory=dict)


def _find_doc(target_dir: Path, doc_id: str) -> Optional[Path]:
    return next((c for c in sorted(target_dir.glob(f"{doc_id}.*")) if c.suffix.lower() != ".json"), None)


def _review_analysis(records: List[DocumentEvalRecord]) -> Dict[str, Any]:
    flagged = [r for r in records if r.needs_review]
    with_err = [r for r in records if r.errors]
    tp = sum(1 for r in records if r.needs_review and r.errors)
    fp = sum(1 for r in records if r.needs_review and not r.errors)
    fn = sum(1 for r in records if not r.needs_review and r.errors)
    tn = sum(1 for r in records if not r.needs_review and not r.errors)
    total_err_fields = sum(len(r.errors) for r in records)
    err_in_flagged = sum(len(r.errors) for r in flagged)
    return {
        "flagged_docs": len(flagged),
        "docs_with_errors": len(with_err),
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
        "recall": round(tp / (tp + fn), 3) if (tp + fn) else None,
        "error_fields_total": total_err_fields,
        "error_fields_in_flagged_docs": err_in_flagged,
        "share_of_errors_caught": round(err_in_flagged / total_err_fields, 3) if total_err_fields else None,
    }


def run_evaluation(mode: Optional[str] = None, labelled_dir: Optional[Path] = None,
                   save_outputs: bool = True, use_cache: bool = False,
                   workers: Optional[int] = None) -> EvalSummary:
    target_dir = labelled_dir or settings.resolve_path(settings.labelled_dir)
    backend = get_backend(mode)
    extractor = InvoiceExtractor(backend, use_cache=use_cache)

    pairs = []
    for gt_path in sorted(target_dir.glob("*.json")):
        doc = _find_doc(target_dir, gt_path.stem)
        if doc:
            pairs.append((gt_path.stem, doc, json.loads(gt_path.read_text(encoding="utf-8"))))

    t0 = time.time()
    results = run_many([p[1] for p in pairs], extractor, workers=workers)
    wall = time.time() - t0

    records: List[DocumentEvalRecord] = []
    field_correct = {f: 0 for f in FIELDS_TO_EVALUATE}
    groups: Dict[str, List[str]] = defaultdict(list)
    row_matched = row_pred = row_gt = 0

    for (doc_id, doc_file, gt), res in zip(pairs, results):
        pred = res.data
        if save_outputs and pred:
            write_output(doc_id, pred)
        matches = calculate_document_metrics(pred, gt)
        errors = {}
        for f, ok in matches.items():
            if ok:
                field_correct[f] += 1
            else:
                tag = classify_error(f, (pred or {}).get(f), gt.get(f))
                errors[f] = tag
                groups[f"{f}: {tag}"].append(doc_id)
        li = line_item_stats((pred or {}).get("line_items"), gt.get("line_items")) if gt.get("line_items") else {}
        if li:
            row_matched += li["matched_rows"]
            row_pred += li["pred_rows"]
            row_gt += li["gt_rows"]
        records.append(DocumentEvalRecord(
            doc_id=doc_id, file_name=doc_file.name, is_success=res.error is None,
            field_matches=matches, predicted=pred, ground_truth=gt,
            tokens_in=res.cost.tokens_in if res.cost else 0,
            tokens_out=res.cost.tokens_out if res.cost else 0,
            cost_usd=res.cost.cost_usd if res.cost else 0.0,
            calls=res.cost.calls if res.cost else 0,
            elapsed_s=res.elapsed_s, needs_review=res.needs_review,
            issues=res.review_reasons, errors=errors, line_items=li, cached=res.cached, error=res.error,
        ))
    if save_outputs:  # --no-save must leave reports/ untouched too
        write_run_metadata(results, "eval_run_metadata")

    n = len(records)
    total_fields = n * len(FIELDS_TO_EVALUATE)
    correct = sum(field_correct.values())
    tin = sum(r.tokens_in for r in records)
    tout = sum(r.tokens_out for r in records)
    cost = sum(r.cost_usd for r in records)

    from pipeline.cost_tracker import PRICING_TABLE
    used_models = {m for r in results if r.cost for m in r.cost.model.split("+")}
    pricing = {m: PRICING_TABLE.get(m) for m in used_models}

    return EvalSummary(
        mode=backend.name, total_docs=n,
        field_accuracy={f: round(field_correct[f] / n * 100.0, 1) if n else 0.0 for f in FIELDS_TO_EVALUATE},
        field_correct_counts=field_correct,
        overall_accuracy=round(correct / total_fields * 100.0, 1) if total_fields else 0.0,
        document_records=records,
        total_tokens_in=tin, total_tokens_out=tout,
        total_cost_usd=round(cost, 6), avg_cost_per_doc=round(cost / n, 6) if n else 0.0,
        wall_time_s=round(wall, 1),
        line_item_row_precision=round(row_matched / row_pred, 3) if row_pred else 0.0,
        line_item_row_recall=round(row_matched / row_gt, 3) if row_gt else 0.0,
        docs_fully_correct=sum(1 for r in records if not r.errors),
        error_groups=dict(sorted(groups.items(), key=lambda kv: -len(kv[1]))),
        review=_review_analysis(records),
        pricing=pricing,
    )


def summary_to_dict(s: EvalSummary) -> Dict[str, Any]:
    from dataclasses import asdict
    return asdict(s)


def error_counter(s: EvalSummary) -> Counter:
    return Counter({k: len(v) for k, v in s.error_groups.items()})
