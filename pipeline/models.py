from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Any, Dict
from PIL import Image
from pydantic import BaseModel, Field, model_validator

class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    amount: float

    model_config = {"extra": "ignore"}

class InvoiceSchema(BaseModel):
    is_invoice: bool
    vendor: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    line_items: Optional[List[LineItem]] = None
    tax_total: Optional[float] = None
    total: Optional[float] = None

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def validate_non_invoice_fields(self):
        """Enforce schema rule: If is_invoice is false, all other 7 fields must be null."""
        if not self.is_invoice:
            for field_name in [
                "vendor", "invoice_number", "invoice_date",
                "currency", "line_items", "tax_total", "total"
            ]:
                if getattr(self, field_name) is not None:
                    raise ValueError(f"For non-invoices, '{field_name}' must be null.")
        return self

@dataclass
class DocumentContent:
    file_path: Path
    file_type: str                  # "pdf" | "image"
    text: str                       # Clean extracted text or OCR text
    images: List[Image.Image]       # Page images for multimodal models or OCR
    page_count: int
    is_readable: bool = True
    error: Optional[str] = None

@dataclass
class TokenUsage:
    mode: str
    model: str
    model_pricing_key: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

@dataclass
class CostRecord:
    file: str
    mode: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float

@dataclass
class ExtractionResult:
    file: str
    data: Optional[Dict[str, Any]]
    needs_review: bool
    review_reasons: List[str] = field(default_factory=list)
    cost: Optional[CostRecord] = None
    error: Optional[str] = None

    @classmethod
    def error_result(cls, file: str, error_msg: str) -> "ExtractionResult":
        return cls(
            file=file,
            data=None,
            needs_review=True,
            review_reasons=[error_msg],
            cost=None,
            error=error_msg
        )
