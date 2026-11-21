from typing import List, Tuple, Optional
from PIL import Image
from openai import OpenAI
from config.settings import settings
from config.prompts import SYSTEM_PROMPT, USER_PROMPT_TEXT, USER_PROMPT_RETRY, build_vision_messages
from ai_backends.base import AIBackend
from pipeline.models import TokenUsage

class OpenAIBackend(AIBackend):
    """
    OpenAI and OpenAI-compatible API gateway backend (e.g. Antigravity passthrough).
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        target_base_url = base_url or settings.openai_base_url
        target_api_key = api_key or settings.openai_api_key or "sk-dummy"

        if target_base_url:
            self.client = OpenAI(base_url=target_base_url, api_key=target_api_key)
            self._mode_label = "antigravity" if "antigravity" in target_base_url.lower() else "openai_custom"
        else:
            self.client = OpenAI(api_key=target_api_key)
            self._mode_label = "openai"

        self.model = settings.openai_model

    @property
    def name(self) -> str:
        return f"OpenAI Gateway ({self.model} via {self._mode_label})"

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

        pricing_key = "gpt_4o_mini" if "mini" in self.model.lower() else "gpt_4o"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=2500,
            timeout=settings.request_timeout,
        )

        usage = TokenUsage(
            mode=self._mode_label,
            model=response.model or self.model,
            model_pricing_key=pricing_key,
            prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
        )

        return response.choices[0].message.content, usage
