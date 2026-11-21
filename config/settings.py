from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # AI Mode
    ai_mode: str = "groq"

    # Local LLM
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "qwen2.5-vl:7b"
    local_llm_api_key: str = "local-key"
    local_llm_vision_enabled: bool = True

    # Groq Multi-Key Pool
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
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_text_model: str = "llama-3.3-70b-versatile"

    # Gemini
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-1.5-flash-latest"

    # OpenAI / Antigravity
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: Optional[str] = None

    # Paths
    data_dir: str = "Es Magico - AI Intern Assignment - Sample Pack"
    labelled_dir: str = "Es Magico - AI Intern Assignment - Sample Pack/labelled"
    unlabelled_dir: str = "Es Magico - AI Intern Assignment - Sample Pack/unlabelled"
    outputs_dir: str = "outputs"

    # OCR
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    # Execution limits & behavior
    arithmetic_tolerance: float = 0.05
    max_retries: int = 2
    request_timeout: int = 60
    log_level: str = "INFO"

    @property
    def groq_api_keys(self) -> List[str]:
        """Collect all non-empty Groq keys from the rotation pool."""
        keys = []
        for i in range(1, 11):
            val = getattr(self, f"groq_api_key_{i}", None)
            if val and val.strip():
                keys.append(val.strip())
        return keys

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a path relative to the project root directory."""
        p = Path(relative_path)
        if p.is_absolute():
            return p
        return BASE_DIR / p

settings = Settings()
