import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from config.settings import settings
from pipeline.extractor import InvoiceExtractor
from pipeline.output_writer import write_output
from eval.metrics import FIELDS_TO_EVALUATE, calculate_document_metrics
from ai_backends.router import get_backend

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
    issues: List[str] = field(default_factory=list)

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

def run_evaluation(
    mode: Optional[str] = None,
    labelled_dir: Optional[Path] = None,
    save_outputs: bool = True
) -> EvalSummary:
    """
    Run evaluation harness over the 10 labelled sample documents (L01 .. L10).
    """
    target_dir = labelled_dir or settings.resolve_path(settings.labelled_dir)
    backend = get_backend(mode)
    extractor = InvoiceExtractor(backend)

    records: List[DocumentEvalRecord] = []
    field_correct = {f: 0 for f in FIELDS_TO_EVALUATE}

    # Process L01 through L10
    for i in range(1, 11):
        doc_id = f"L{i:02d}"
        gt_path = target_dir / f"{doc_id}.json"
        if not gt_path.exists():
            continue

        with open(gt_path, "r", encoding="utf-8") as f:
            gt_data = json.load(f)

        # Locate corresponding document file (.pdf or .jpg/.png)
        doc_candidates = list(target_dir.glob(f"{doc_id}.*"))
        doc_file = next((c for c in doc_candidates if c.suffix.lower() != ".json"), None)

        if not doc_file:
            continue

        # Run extraction
        result = extractor.extract(doc_file)
        pred_data = result.data

        # Save to outputs folder as required by assignment
        if save_outputs and pred_data:
            write_output(doc_id, pred_data)

        # Evaluate fields
        matches = calculate_document_metrics(pred_data, gt_data)
        for f, is_match in matches.items():
            if is_match:
                field_correct[f] += 1

        tokens_in = result.cost.tokens_in if result.cost else 0
        tokens_out = result.cost.tokens_out if result.cost else 0
        cost_usd = result.cost.cost_usd if result.cost else 0.0

        records.append(DocumentEvalRecord(
            doc_id=doc_id,
            file_name=doc_file.name,
            is_success=(result.error is None),
            field_matches=matches,
            predicted=pred_data,
            ground_truth=gt_data,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            issues=result.review_reasons
        ))

    num_docs = len(records)
    field_acc = {
        f: round((field_correct[f] / num_docs) * 100.0, 1) if num_docs else 0.0
        for f in FIELDS_TO_EVALUATE
    }

    total_fields = num_docs * len(FIELDS_TO_EVALUATE)
    correct_fields = sum(field_correct.values())
    overall_acc = round((correct_fields / total_fields) * 100.0, 1) if total_fields else 0.0

    total_in = sum(r.tokens_in for r in records)
    total_out = sum(r.tokens_out for r in records)
    total_cost = sum(r.cost_usd for r in records)

    return EvalSummary(
        mode=backend.name,
        total_docs=num_docs,
        field_accuracy=field_acc,
        field_correct_counts=field_correct,
        overall_accuracy=overall_acc,
        document_records=records,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        total_cost_usd=round(total_cost, 6),
        avg_cost_per_doc=round(total_cost / num_docs, 6) if num_docs else 0.0
    )
