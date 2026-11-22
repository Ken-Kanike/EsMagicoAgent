from typing import Optional

from ai_backends.base import AIBackend, BackendNotConfigured
from config.settings import settings

VALID_MODES = ["groq", "no_ai", "openai", "gemini", "local"]

_ALIASES = {
    "no_ai": "no_ai", "noai": "no_ai", "rules": "no_ai", "regex": "no_ai",
    "groq": "groq", "groq_cloud": "groq",
    "local": "local", "ollama": "local", "lmstudio": "local",
    "gemini": "gemini", "google": "gemini",
    "openai": "openai", "gpt": "openai",
}


def normalize_mode(mode: Optional[str]) -> str:
    m = (mode or settings.ai_mode or "groq").lower().strip()
    if m not in _ALIASES:
        raise ValueError(f"Unknown AI mode '{m}'. Supported: {', '.join(VALID_MODES)}")
    return _ALIASES[m]


def get_backend(mode: Optional[str] = None) -> AIBackend:
    """
    Resolve a backend. Never silently substitutes another backend: if the requested
    provider is not configured, BackendNotConfigured is raised so a run can't be
    mistaken for an LLM run when it was really the rule engine.
    """
    m = normalize_mode(mode)
    if m == "no_ai":
        from ai_backends.no_ai import NoAIBackend
        return NoAIBackend()
    if m == "groq":
        from ai_backends.groq_backend import GroqBackend
        return GroqBackend()
    from ai_backends.openai_backend import GeminiBackend, LocalLLMBackend, OpenAIBackend
    if m == "gemini":
        return GeminiBackend()
    if m == "openai":
        return OpenAIBackend()
    if m == "local":
        return LocalLLMBackend()
    raise BackendNotConfigured(m)
