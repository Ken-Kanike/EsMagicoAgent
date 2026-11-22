from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from pipeline.models import TokenUsage


class BackendError(RuntimeError):
    """Raised when a provider call fails after all retries (timeout, auth, rate limit, 5xx)."""


class BackendNotConfigured(RuntimeError):
    """Raised when the selected backend has no credentials / endpoint."""


def messages_have_images(messages: List[Dict[str, Any]]) -> bool:
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(p.get("type") == "image_url" for p in c):
            return True
    return False


def strip_images(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert multimodal messages to plain-text messages (for text-only models)."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = "\n".join(p.get("text", "") for p in c if p.get("type") == "text")
        out.append({**m, "content": c})
    return out


class AIBackend(ABC):
    """Common interface for every extraction backend."""

    #: True for LLM backends that accept chat messages; False for the rule engine.
    is_llm: bool = True
    #: short id used in cache keys / reports
    mode: str = "base"

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def supports_vision(self) -> bool: ...

    def model_for(self, has_images: bool) -> str:
        return ""

    def chat(
        self,
        messages: List[Dict[str, Any]],
        json_mode: bool = True,
        max_tokens: int = 4096,
    ) -> Tuple[str, TokenUsage]:
        raise NotImplementedError

    def cache_id(self) -> str:
        return f"{self.mode}:{self.model_for(True)}:{self.model_for(False)}"


def usage_from_response(response: Any, mode: str, model: str) -> TokenUsage:
    u = getattr(response, "usage", None)
    return TokenUsage(
        mode=mode,
        model=getattr(response, "model", None) or model,
        model_pricing_key=model,
        prompt_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(u, "completion_tokens", 0) or 0),
    )


def first_content(response: Any) -> Optional[str]:
    try:
        return response.choices[0].message.content
    except Exception:
        return None
