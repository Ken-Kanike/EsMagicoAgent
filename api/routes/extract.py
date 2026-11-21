import shutil
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Query, HTTPException
from config.settings import settings
from pipeline.extractor import InvoiceExtractor
from pipeline.models import InvoiceSchema
from ai_backends.router import get_backend
from api.models import ExtractResponse

router = APIRouter(tags=["Extraction"])

@router.post("/extract", response_model=ExtractResponse)
async def extract_invoice(
    file: UploadFile = File(...),
    mode: Optional[str] = Query(None, description="Backend mode (no_ai, groq, local, gemini, openai)")
):
    temp_dir = settings.resolve_path("temp_upload")
    temp_dir.mkdir(exist_ok=True)
    file_path = temp_dir / file.filename

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        backend = get_backend(mode)
        extractor = InvoiceExtractor(backend)
        result = extractor.extract(file_path)

        if result.error and not result.data:
            raise HTTPException(status_code=400, detail=result.error)

        parsed_obj = None
        if result.data:
            parsed_obj = InvoiceSchema(**result.data)

        tokens = 0
        cost = 0.0
        if result.cost:
            tokens = result.cost.tokens_in + result.cost.tokens_out
            cost = result.cost.cost_usd

        return ExtractResponse(
            file_name=file.filename,
            status="flagged" if result.needs_review else "verified",
            needs_review=result.needs_review,
            review_reasons=result.review_reasons,
            data=parsed_obj,
            cost_usd=cost,
            tokens_consumed=tokens
        )
    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass
