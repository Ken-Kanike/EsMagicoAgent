from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend selection: groq | no_ai | local | gemini | openai
    ai_mode: str = "groq"

    # Local LLM (any OpenAI-compatible server: Ollama, LM Studio, llama.cpp)
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "qwen2.5vl:7b"
    local_llm_api_key: str = "local-key"
    local_llm_vision_enabled: bool = True

    # Groq multi-key pool
    groq_api_key_1: Optional[str] = None
    groq_api_key_2: Optional[str] = None
    groq_api_key_3: Optional[str] = None
    groq_api_key_4: Optional[str] = None
    groq_api_key_5: Optional[str] = None
    groq_api_key_6: Optional[str] = None
    groq_api_key_7: Optional[str] = None
    groq_api_key_8: Optional[str] = None
    groq_api_key_9: Optional[str] = None
    groq_api_key_10: Optional[str] = None
    # Vision model reads page images (+ embedded text when the PDF has it).
    groq_vision_model: str = "qwen/qwen3.8-27b"
    # Text model used only when a backend is forced into text-only mode.
    groq_text_model: str = "openai/gpt-oss-120b"
    # Free-tier limits are per ORGANISATION and per model (all keys of one org share them).
    groq_tokens_per_minute: int = 7000
    groq_reasoning_effort: str = "medium"   # gpt-oss only: low | medium | high
    # Digital PDFs (with a text layer) go text-only to the text model: exact characters,
    # ~3x fewer tokens, and a separate rate-limit pool. Scans/photos go to the vision model.
    route_digital_to_text: bool = True

    # Gemini (OpenAI-compatible endpoint)
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"

    # OpenAI or any OpenAI-compatible gateway
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: Optional[str] = None

    # Paths
    data_dir: str = "Es Magico - AI Intern Assignment - Sample Pack"
    labelled_dir: str = "Es Magico - AI Intern Assignment - Sample Pack/labelled"
    unlabelled_dir: str = "Es Magico - AI Intern Assignment - Sample Pack/unlabelled"
    outputs_dir: str = "outputs"
    cache_dir: str = ".cache"
    upload_dir: str = "temp_upload"

    # OCR (only used by the no_ai baseline and text-only fallbacks)
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    # Execution behaviour
    arithmetic_tolerance: float = 0.05
    max_retries: int = 2
    request_timeout: int = 90
    max_pages: int = 5            # pages sent to a vision model
    render_dpi: int = 200          # scans: 150 dpi made small print unreadable (U05 year misread)
    max_image_side: int = 1800    # px, longest side sent to vision / OCR
    max_workers: int = 4          # parallel documents in batch / eval
    cache_enabled: bool = True
    log_level: str = "INFO"
    pii_shield_enabled: bool = False

    @property
    def groq_api_keys(self) -> List[str]:
        keys = []
        for i in range(1, 11):
            val = getattr(self, f"groq_api_key_{i}", None)
            if val and val.strip():
                keys.append(val.strip())
        return keys

    def resolve_path(self, relative_path: str) -> Path:
        p = Path(relative_path)
        return p if p.is_absolute() else BASE_DIR / p


settings = Settings()
