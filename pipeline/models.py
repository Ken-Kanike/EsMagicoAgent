from __future__ import annotations

import io
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Any, Dict

from PIL import Image
from pydantic import BaseModel, Field, model_validator

NON_INVOICE_FIELDS = [
    "vendor", "invoice_number", "invoice_date", "currency",
    "line_items", "tax_total", "total",
]


class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    amount: float

    model_config = {"extra": "ignore"}


class InvoiceSchema(BaseModel):
    """Mirrors schema.json from the sample pack."""
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
        if not self.is_invoice:
            for name in NON_INVOICE_FIELDS:
                if getattr(self, name) is not None:
                    raise ValueError(f"For non-invoices, '{name}' must be null.")
        return self


class DocumentContent:
    """
    A loaded document. Embedded text is read eagerly (cheap); page images are
    rendered lazily and cached, because rendering is only needed for vision
    models or OCR.
    """

    def __init__(
        self,
        file_path: Path,
        file_type: str,
        text: str = "",
        page_count: int = 0,
        is_readable: bool = True,
        error: Optional[str] = None,
        pdf_bytes: Optional[bytes] = None,
        image: Optional[Image.Image] = None,
        dpi: int = 150,
        max_pages: int = 5,
    ):
        self.file_path = file_path
        self.file_type = file_type
        self.text = text
        self.page_count = page_count
        self.is_readable = is_readable
        self.error = error
        self._pdf_bytes = pdf_bytes
        self._image = image
        self._dpi = dpi
        self._max_pages = max_pages
        self._images: Optional[List[Image.Image]] = None

    @property
    def images(self) -> List[Image.Image]:
        if self._images is None:
            imgs = self._render()
            # Scans/photos only (no text layer): straighten sideways pages before OCR / vision.
            if len((self.text or "").strip()) <= 80:
                from pipeline.ocr_engine import auto_upright
                imgs = [auto_upright(im) for im in imgs]
            self._images = imgs
        return self._images

    @property
    def layout_text(self) -> str:
        """Embedded text rebuilt into visual rows ("cell | cell | cell"), so table rows stay on one line."""
        if not hasattr(self, "_layout_text"):
            self._layout_text = self._build_layout_text()
        return self._layout_text

    def _build_layout_text(self) -> str:
        if not self._pdf_bytes:
            return self.text
        import fitz

        pages: List[str] = []
        with fitz.open(stream=self._pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                words = page.get_text("words")  # x0, y0, x1, y1, word, block, line, wno
                if not words:
                    continue
                words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
                rows: List[List[tuple]] = []
                for w in words:
                    yc = (w[1] + w[3]) / 2
                    h = max(1.0, w[3] - w[1])
                    if rows and abs(rows[-1][0][0] - yc) <= h * 0.45:
                        rows[-1][1].append(w)
                    else:
                        rows.append([(yc,), [w]])
                lines = []
                for _, ws in rows:
                    ws.sort(key=lambda w: w[0])
                    out, prev = "", None
                    for w in ws:
                        if prev is not None:
                            gap = w[0] - prev[2]
                            out += "  |  " if gap > max(8.0, (prev[3] - prev[1]) * 0.9) else " "
                        out += w[4]
                        prev = w
                    lines.append(out)
                pages.append("\n".join(lines))
        return "\n\n--- PAGE BREAK ---\n\n".join(pages).strip()

    @property
    def pages_truncated(self) -> bool:
        return self.file_type == "pdf" and self.page_count > self._max_pages

    def _render(self) -> List[Image.Image]:
        if self._image is not None:
            return [self._image]
        if not self._pdf_bytes:
            return []
        import fitz  # PyMuPDF

        out: List[Image.Image] = []
        with fitz.open(stream=self._pdf_bytes, filetype="pdf") as doc:
            zoom = self._dpi / 72.0
            for i, page in enumerate(doc):
                if i >= self._max_pages:
                    break
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                out.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        return out


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
    calls: int = 1


@dataclass
class ExtractionResult:
    file: str
    data: Optional[Dict[str, Any]]
    needs_review: bool
    review_reasons: List[str] = field(default_factory=list)
    cost: Optional[CostRecord] = None
    error: Optional[str] = None
    error_type: Optional[str] = None      # corrupt_file | unsupported | backend_error | unparseable
    backend: str = ""
    attempts: int = 0
    elapsed_s: float = 0.0
    cached: bool = False
    timings: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def error_result(cls, file: str, error_msg: str, error_type: str = "error", backend: str = "") -> "ExtractionResult":
        return cls(
            file=file, data=None, needs_review=True, review_reasons=[error_msg],
            cost=None, error=error_msg, error_type=error_type, backend=backend,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExtractionResult":
        d = dict(d)
        cost = d.pop("cost", None)
        res = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        res.cost = CostRecord(**cost) if cost else None
        return res
