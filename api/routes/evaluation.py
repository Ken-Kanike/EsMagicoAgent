from typing import Optional
from fastapi import APIRouter, Query
from eval.harness import run_evaluation
from api.models import EvalResponse

router = APIRouter(tags=["Evaluation"])

@router.get("/eval", response_model=EvalResponse)
def evaluate(
    mode: Optional[str] = Query(None, description="Backend mode to evaluate")
):
    summary = run_evaluation(mode=mode)
    return EvalResponse(
        mode=summary.mode,
        total_docs=summary.total_docs,
        overall_accuracy=summary.overall_accuracy,
        field_accuracy=summary.field_accuracy,
        total_cost_usd=summary.total_cost_usd
    )
