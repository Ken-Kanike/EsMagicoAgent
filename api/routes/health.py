from fastapi import APIRouter
from config.settings import settings
from api.models import HealthResponse

router = APIRouter(tags=["Health"])

@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        status="healthy",
        active_mode=settings.ai_mode,
        groq_keys_available=len(settings.groq_api_keys)
    )
