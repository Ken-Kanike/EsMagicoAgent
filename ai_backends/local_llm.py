from typing import List, Tuple
from PIL import Image
from openai import OpenAI
from config.settings import settings
from config.prompts import SYSTEM_PROMPT, USER_PROMPT_TEXT, USER_PROMPT_RETRY, build_vision_messages
from ai_backends.base import AIBackend
from pipeline.models import TokenUsage

class LocalLLMBackend(AIBackend):
    """
    OpenAI-compatible local inference backend.
    Compatible with Ollama, LM Studio, llama.cpp, NousResearch Hermes, and OpenCode.
    """

    def __init__(self):
        self.client = OpenAI(
            base_url=settings.local_llm_base_url,
            api_key=settings.local_llm_api_key or "local-key"
        )
        self.model = settings.local_llm_model
        self.vision_enabled = settings.local_llm_vision_enabled

    @property
    def name(self) -> str:
        return f"Local LLM ({self.model} @ {settings.local_llm_base_url})"

    @property
    def supports_vision(self) -> bool:
        return self.vision_enabled

    def extract(
        self,
        text: str,
        images: List[Image.Image],
        retry: bool = False,
        retry_reason: str = ""
    ) -> Tuple[str, TokenUsage]:
        has_images = images and len(images) > 0 and self.vision_enabled

        if has_images:
            try:
                messages = build_vision_messages(
                    text=text,
                    images=images,
                    is_retry=retry,
                    retry_reason=retry_reason
                )
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2500,
                    timeout=settings.request_timeout,
                )
                usage = TokenUsage(
                    mode="local",
                    model=self.model,
                    model_pricing_key="local",
                    prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                )
                return response.choices[0].message.content, usage
            except Exception as e:
                # If vision fails on local model, downgrade to text extraction
                self.vision_enabled = False

        # Text-only call
        user_msg = (
            USER_PROMPT_RETRY.format(issues=retry_reason, document_text=text[:8000])
            if retry else
            USER_PROMPT_TEXT.format(document_text=text[:8000])
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=2500,
            timeout=settings.request_timeout,
        )
        usage = TokenUsage(
            mode="local",
            model=self.model,
            model_pricing_key="local",
            prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
        )
        return response.choices[0].message.content, usage
