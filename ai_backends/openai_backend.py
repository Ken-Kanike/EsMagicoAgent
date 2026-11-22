import time
from typing import Any, Dict, List, Optional, Tuple

from ai_backends.base import (
    AIBackend, BackendError, BackendNotConfigured, first_content,
    messages_have_images, strip_images, usage_from_response,
)
from config.settings import settings
from pipeline.models import TokenUsage


class OpenAICompatibleBackend(AIBackend):
    """
    Any OpenAI-compatible chat endpoint: OpenAI, Google Gemini's OpenAI endpoint,
    Ollama / LM Studio / llama.cpp, or a custom gateway.
    """

    def __init__(self, mode: str, model: str, api_key: Optional[str], base_url: Optional[str],
                 vision: bool = True, label: str = "OpenAI", json_mode: bool = True):
        from openai import OpenAI
        if not api_key:
            raise BackendNotConfigured(f"{label} selected but no API key is configured in .env.")
        self.mode = mode
        self.model = model
        self.label = label
        self._vision = vision
        self._json_mode = json_mode
        self.base_url = base_url
        kwargs: Dict[str, Any] = {"api_key": api_key, "timeout": settings.request_timeout, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    @property
    def name(self) -> str:
        return f"{self.label} ({self.model})"

    @property
    def supports_vision(self) -> bool:
        return self._vision

    def model_for(self, has_images: bool) -> str:
        return self.model

    def chat(self, messages: List[Dict[str, Any]], json_mode: bool = True,
             max_tokens: int = 4096) -> Tuple[str, TokenUsage]:
        from openai import (APIConnectionError, APITimeoutError, BadRequestError,
                            InternalServerError, RateLimitError)
        if not self._vision or not messages_have_images(messages):
            messages = strip_images(messages)
        kwargs: Dict[str, Any] = dict(model=self.model, messages=messages, temperature=0, max_tokens=max_tokens)
        if json_mode and self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_err: Optional[Exception] = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                content = first_content(resp)
                if not content:
                    raise BackendError("Empty response from model.")
                return content, usage_from_response(resp, self.mode, self.model)
            except BadRequestError as e:
                if "response_format" in kwargs:      # some servers reject json mode: retry without it
                    kwargs.pop("response_format")
                    last_err = e
                    continue
                raise BackendError(f"{self.label} rejected the request: {str(e)[:300]}") from e
            except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError, BackendError) as e:
                last_err = e
                time.sleep(2.0 * (attempt + 1))
        raise BackendError(f"{self.label} call failed: {type(last_err).__name__}: {str(last_err)[:200]}")


def OpenAIBackend() -> OpenAICompatibleBackend:
    return OpenAICompatibleBackend("openai", settings.openai_model, settings.openai_api_key,
                                   settings.openai_base_url or None, label="OpenAI")


def GeminiBackend() -> OpenAICompatibleBackend:
    return OpenAICompatibleBackend("gemini", settings.gemini_model, settings.gemini_api_key,
                                   "https://generativelanguage.googleapis.com/v1beta/openai/", label="Google Gemini")


def LocalLLMBackend() -> OpenAICompatibleBackend:
    return OpenAICompatibleBackend("local", settings.local_llm_model, settings.local_llm_api_key or "local-key",
                                   settings.local_llm_base_url, vision=settings.local_llm_vision_enabled,
                                   label="Local LLM")
