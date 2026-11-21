import time
import threading
from typing import List, Tuple, Optional
from PIL import Image
import groq
from config.settings import settings
from config.prompts import SYSTEM_PROMPT, USER_PROMPT_TEXT, USER_PROMPT_RETRY, build_vision_messages
from ai_backends.base import AIBackend
from pipeline.models import TokenUsage

class GroqKeyRotator:
    """Thread-safe round-robin API key rotator with automatic rate-limit cooldown."""

    def __init__(self, keys: List[str]):
        self.keys = [k for k in keys if k and k.strip()]
        self._index = 0
        self._lock = threading.Lock()
        self._cooldowns: dict[str, float] = {}

    def get_key(self) -> str:
        if not self.keys:
            raise ValueError(
                "No Groq API keys configured. Please add GROQ_API_KEY_1 (up to GROQ_API_KEY_10) to your .env file."
            )

        with self._lock:
            now = time.time()
            # Try to find a key that is not in cooldown
            for _ in range(len(self.keys)):
                key = self.keys[self._index]
                self._index = (self._index + 1) % len(self.keys)
                if self._cooldowns.get(key, 0) < now:
                    return key

            # All keys are currently in cooldown; wait for the one that expires soonest
            soonest_key = min(self.keys, key=lambda k: self._cooldowns.get(k, 0))
            wait_seconds = max(0.5, self._cooldowns.get(soonest_key, 0) - now)
            time.sleep(wait_seconds)
            return soonest_key

    def trigger_cooldown(self, key: str, seconds: float = 65.0):
        with self._lock:
            self._cooldowns[key] = time.time() + seconds

class GroqBackend(AIBackend):
    """Groq Cloud API backend supporting high-speed inference and multi-key rotation."""

    def __init__(self):
        self.rotator = GroqKeyRotator(settings.groq_api_keys)
        self.vision_model = settings.groq_vision_model
        self.text_model = settings.groq_text_model

    @property
    def name(self) -> str:
        return f"Groq (Vision: {self.vision_model} | Text: {self.text_model})"

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
        max_attempts = max(3, len(self.rotator.keys) * 2)

        for attempt in range(max_attempts):
            key = self.rotator.get_key()
            client = groq.Groq(api_key=key, timeout=settings.request_timeout)

            try:
                # 1. Use Vision if images are provided
                if images and len(images) > 0:
                    try:
                        messages = build_vision_messages(
                            text=text,
                            images=images,
                            is_retry=retry,
                            retry_reason=retry_reason
                        )
                        response = client.chat.completions.create(
                            model=self.vision_model,
                            messages=messages,
                            temperature=0.1,
                            max_tokens=2500,
                        )
                        usage = TokenUsage(
                            mode="groq",
                            model=response.model or self.vision_model,
                            model_pricing_key="groq_free",
                            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                            completion_tokens=response.usage.completion_tokens if response.usage else 0,
                        )
                        return response.choices[0].message.content, usage
                    except groq.BadRequestError as b_err:
                        # If vision model errors out due to image size/unsupported payload, fall back to text
                        if "image" in str(b_err).lower() or "too large" in str(b_err).lower():
                            pass
                        else:
                            raise b_err

                # 2. Text-based extraction fallback
                user_msg = (
                    USER_PROMPT_RETRY.format(issues=retry_reason, document_text=text[:7500])
                    if retry else
                    USER_PROMPT_TEXT.format(document_text=text[:7500])
                )
                response = client.chat.completions.create(
                    model=self.text_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.1,
                    max_tokens=2500,
                )
                usage = TokenUsage(
                    mode="groq",
                    model=response.model or self.text_model,
                    model_pricing_key="groq_free",
                    prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                    completion_tokens=response.usage.completion_tokens if response.usage else 0,
                )
                return response.choices[0].message.content, usage

            except groq.RateLimitError:
                # Put key on cooldown and try next key
                self.rotator.trigger_cooldown(key, seconds=65.0)
                if attempt == max_attempts - 1:
                    raise
                continue
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise e
                time.sleep(1.0)
                continue

        raise RuntimeError("Failed to extract data via Groq after exhausting key pool retries.")
