from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from pipeline.models import InvoiceSchema

class ExtractResponse(BaseModel):
    file_name: str
    status: str
    needs_review: bool
    review_reasons: List[str]
    data: Optional[InvoiceSchema] = None
    cost_usd: float = 0.0
    tokens_consumed: int = 0

class EvalResponse(BaseModel):
    mode: str
    total_docs: int
    overall_accuracy: float
    field_accuracy: Dict[str, float]
    total_cost_usd: float

class HealthResponse(BaseModel):
    status: str
    active_mode: str
    groq_keys_available: int
    version: str = "1.0.0"
