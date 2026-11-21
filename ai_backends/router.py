from typing import Optional
from config.settings import settings
from ai_backends.base import AIBackend
from ai_backends.no_ai import NoAIBackend
from ai_backends.groq_backend import GroqBackend
from ai_backends.local_llm import LocalLLMBackend
from ai_backends.gemini_backend import GeminiBackend
from ai_backends.openai_backend import OpenAIBackend

def get_backend(mode: Optional[str] = None) -> AIBackend:
    """Resolve and instantiate the requested extraction backend."""
    selected_mode = (mode or settings.ai_mode).lower().strip()

    if selected_mode in ("no_ai", "noai", "rules", "regex"):
        return NoAIBackend()

    elif selected_mode in ("groq", "groq_cloud"):
        if not settings.groq_api_keys:
            # Safe fallback if user has not yet entered keys in .env
            return NoAIBackend()
        return GroqBackend()

    elif selected_mode in ("local", "ollama", "lmstudio", "opencode", "hermes"):
        return LocalLLMBackend()

    elif selected_mode in ("gemini", "google"):
        if not settings.gemini_api_key:
            return NoAIBackend()
        return GeminiBackend()

    elif selected_mode in ("openai", "gpt"):
        if not settings.openai_api_key:
            return NoAIBackend()
        return OpenAIBackend()

    elif selected_mode in ("antigravity", "agy"):
        return OpenAIBackend(base_url=settings.openai_base_url or "https://api.antigravity.ai/v1")

    else:
        valid = ["no_ai", "groq", "local", "gemini", "openai", "antigravity"]
        raise ValueError(f"Unknown AI mode '{selected_mode}'. Supported modes: {', '.join(valid)}")
