from typing import List, Tuple
from PIL import Image
from openai import OpenAI
from config.settings import settings
from config.prompts import SYSTEM_PROMPT, USER_PROMPT_TEXT, USER_PROMPT_RETRY, build_vision_messages
from ai_backends.base import AIBackend
from pipeline.models import TokenUsage

class GeminiBackend(AIBackend):
    """
    Google Gemini API backend utilizing Google's OpenAI-compatible endpoint.
    Supports Gemini 1.5 Flash, Gemini 1.5 Pro, and Gemini 2.0.
    """

    def __init__(self):
        api_key = settings.gemini_api_key or "dummy-key"
        self.client = OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=api_key
        )
        self.model = settings.gemini_model

    @property
    def name(self) -> str:
        return f"Google Gemini ({self.model})"

    @property
    def supports_vision(self) -> bool:
        return True

    def extract(
        self,
        text: str,
        images: List[Image.Image],
        retry: bool = False,
        retry_reason: str = ""
    ) -> Tuple[str, TokenUsage]:
        if images and len(images) > 0:
            messages = build_vision_messages(
                text=text,
                images=images,
                is_retry=retry,
                retry_reason=retry_reason
            )
        else:
            user_msg = (
                USER_PROMPT_RETRY.format(issues=retry_reason, document_text=text[:8000])
                if retry else
                USER_PROMPT_TEXT.format(document_text=text[:8000])
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=2500,
            timeout=settings.request_timeout,
        )

        usage = TokenUsage(
            mode="gemini",
            model=response.model or self.model,
            model_pricing_key="gemini_15_flash",
            prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
        )

        return response.choices[0].message.content, usage
