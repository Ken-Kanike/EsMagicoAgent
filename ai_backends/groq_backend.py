import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import groq

from ai_backends.base import (
    AIBackend, BackendError, BackendNotConfigured, first_content,
    messages_have_images, strip_images, usage_from_response,
)
from config.settings import settings
from pipeline.cost_tracker import register_price
from pipeline.models import TokenUsage

log = logging.getLogger("groq")


class GroqKeyRotator:
    """
    Thread-safe round-robin key pool with per-key cooldown.
    The lock is held only to pick a key; waiting happens outside the lock so
    other threads keep working with keys that are still available.
    """

    def __init__(self, keys: List[str]):
        self.keys = [k for k in keys if k and k.strip()]
        self._index = 0
        self._lock = threading.Lock()
        self._cooldown_until: Dict[str, float] = {}

    def acquire(self) -> str:
        if not self.keys:
            raise BackendNotConfigured("No Groq API keys configured (set GROQ_API_KEY_1 in .env).")
        while True:
            with self._lock:
                now = time.time()
                for _ in range(len(self.keys)):
                    key = self.keys[self._index]
                    self._index = (self._index + 1) % len(self.keys)
                    if self._cooldown_until.get(key, 0.0) <= now:
                        return key
                wait = min(self._cooldown_until.get(k, 0.0) for k in self.keys) - now
            time.sleep(max(0.25, min(wait, 30.0)))

    def cooldown(self, key: str, seconds: float):
        with self._lock:
            self._cooldown_until[key] = max(self._cooldown_until.get(key, 0.0), time.time() + seconds)


class TokenBucket:
    """
    Client-side token bucket for one model (capacity = tokens/minute, refilled continuously).
    Requests wait here instead of being sent and rejected with 429. After each call the
    reservation is corrected to the real usage, so over-estimates are returned immediately.
    All keys of one Groq org share the quota, so there is one bucket per model.
    """

    def __init__(self, tokens_per_minute: int):
        self.capacity = float(tokens_per_minute)
        self.rate = self.capacity / 60.0
        self.level = self.capacity
        self._t = time.time()
        self._lock = threading.Lock()
        self._blocked_until = 0.0
        self.avg_out = 700.0      # learned average completion size

    def _refill(self, now: float):
        if now <= self._t:  # inside a 429 block window: no refill yet (and never a negative one)
            return
        self.level = min(self.capacity, self.level + (now - self._t) * self.rate)
        self._t = now

    def reserve(self, tokens: int) -> float:
        need = min(float(tokens), self.capacity)
        while True:
            with self._lock:
                now = time.time()
                self._refill(now)
                if now >= self._blocked_until and self.level >= need:
                    self.level -= need
                    return need
                wait = max(self._blocked_until - now, (need - self.level) / self.rate)
            time.sleep(max(0.1, min(wait, 10.0)))

    def settle(self, reserved: float, actual_in: int, actual_out: int):
        with self._lock:
            self.level = min(self.capacity, self.level + reserved - (actual_in + actual_out))
            self.avg_out = 0.7 * self.avg_out + 0.3 * actual_out

    def block(self, seconds: float):
        with self._lock:
            self._blocked_until = max(self._blocked_until, time.time() + seconds)
            self.level = 0.0
            self._t = time.time() + seconds


def estimate_tokens(messages: List[Dict[str, Any]], reserve_output: float) -> int:
    chars, images = 0, 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for p in c:
                if p.get("type") == "text":
                    chars += len(p.get("text", ""))
                elif p.get("type") == "image_url":
                    images += 1
    return int(chars / 3.6 + images * 1800 + reserve_output)


_PRICES_LOADED = False
_PRICES_LOCK = threading.Lock()


def _load_live_prices(client: "groq.Groq"):
    """Groq's /models endpoint publishes per-token list prices; register them for cost reporting."""
    global _PRICES_LOADED
    with _PRICES_LOCK:
        if _PRICES_LOADED:
            return
        _PRICES_LOADED = True
        try:
            for m in client.models.list().data:
                p = (m.model_dump().get("pricing") or {})
                if p.get("prompt") is not None and p.get("completion") is not None:
                    register_price(m.id, float(p["prompt"]) * 1000, float(p["completion"]) * 1000, source="groq /models (live)")
        except Exception:
            pass  # fall back to static table in cost_tracker


def _retry_after_seconds(err: Exception, default: float) -> float:
    try:
        headers = err.response.headers  # type: ignore[attr-defined]
        for h in ("retry-after", "x-ratelimit-reset-tokens"):  # reset-requests is the DAILY window
            v = headers.get(h)
            if not v:
                continue
            v = v.strip().lower()
            if v.endswith("ms"):
                return float(v[:-2]) / 1000.0
            if v.endswith("s") and "m" in v:      # e.g. "1m2.5s"
                mins, secs = v[:-1].split("m")
                return float(mins) * 60 + float(secs or 0)
            if v.endswith("s"):
                return float(v[:-1])
            return float(v)
    except Exception:
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(err))
    if m:
        return float(m.group(1) or 0) * 60 + float(m.group(2))
    return default


class GroqBackend(AIBackend):
    mode = "groq"

    def __init__(self):
        self.rotator = GroqKeyRotator(settings.groq_api_keys)
        if not self.rotator.keys:
            raise BackendNotConfigured("Groq selected but no GROQ_API_KEY_n is set in .env.")
        self.vision_model = settings.groq_vision_model
        self.text_model = settings.groq_text_model
        self._clients: Dict[str, groq.Groq] = {}
        self._clients_lock = threading.Lock()
        # All keys of one Groq org share the per-model quota, so the budget is per model, not per key.
        self._buckets: Dict[str, TokenBucket] = {}
        _load_live_prices(self._client(self.rotator.keys[0]))

    def _client(self, key: str) -> "groq.Groq":
        with self._clients_lock:
            c = self._clients.get(key)
            if c is None:
                c = groq.Groq(api_key=key, timeout=settings.request_timeout, max_retries=0)
                self._clients[key] = c
            return c

    @property
    def name(self) -> str:
        return f"Groq (vision: {self.vision_model} | text: {self.text_model})"

    @property
    def supports_vision(self) -> bool:
        return True

    def model_for(self, has_images: bool) -> str:
        return self.vision_model if has_images else self.text_model

    def _bucket(self, model: str) -> TokenBucket:
        with self._clients_lock:
            b = self._buckets.get(model)
            if b is None:
                b = TokenBucket(settings.groq_tokens_per_minute)
                self._buckets[model] = b
            return b

    def chat(self, messages: List[Dict[str, Any]], json_mode: bool = True,
             max_tokens: int = 4096, model: Optional[str] = None) -> Tuple[str, TokenUsage]:
        has_images = messages_have_images(messages)
        model = model or self.model_for(has_images)
        if not has_images:
            messages = strip_images(messages)  # text-only models require string content

        kwargs: Dict[str, Any] = dict(model=model, messages=messages, temperature=0, max_tokens=max_tokens, seed=7)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if model.startswith("openai/gpt-oss"):
            kwargs["reasoning_effort"] = settings.groq_reasoning_effort
            kwargs["include_reasoning"] = False
        bucket = self._bucket(model)
        est = estimate_tokens(messages, reserve_output=bucket.avg_out)

        last_err: Optional[Exception] = None
        max_attempts = max(6, len(self.rotator.keys) * 2)
        for attempt in range(max_attempts):
            entry = bucket.reserve(est)
            key = self.rotator.acquire()
            try:
                response = self._client(key).chat.completions.create(**kwargs)
                content = first_content(response)
                usage = usage_from_response(response, "groq", model)
                bucket.settle(entry, usage.prompt_tokens, usage.completion_tokens)
                if not content:
                    raise BackendError("Empty response from model.")
                return content, usage
            except groq.RateLimitError as e:
                last_err = e
                wait = _retry_after_seconds(e, 20.0) + 0.5
                msg = str(e).lower()
                if "per day" in msg or "(rpd)" in msg or "(tpd)" in msg:
                    raise BackendError(f"Groq daily quota exhausted for {model}: {str(e)[:200]}") from e
                wait = min(wait, 65.0)
                log.warning("429 on %s (attempt %d): waiting %.1fs", model, attempt + 1, wait)
                bucket.block(wait)  # org-wide limit: every key is affected
            except groq.BadRequestError as e:
                msg = str(e)
                # JSON mode validation failure: the model produced invalid JSON. Retry once without
                # response_format and let the caller's parser repair it.
                if "json_validate_failed" in msg or "failed_generation" in msg:
                    last_err = e
                    kwargs.pop("response_format", None)
                    continue
                raise BackendError(f"Groq rejected the request: {msg[:300]}") from e
            except groq.NotFoundError as e:
                raise BackendError(f"Groq model '{model}' not found - check GROQ_VISION_MODEL / GROQ_TEXT_MODEL "
                                   f"in .env against `client.models.list()`.") from e
            except (groq.AuthenticationError, groq.PermissionDeniedError) as e:
                self.rotator.cooldown(key, 3600)
                last_err = e
            except (groq.APITimeoutError, groq.APIConnectionError, groq.InternalServerError) as e:
                last_err = e
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
            except BackendError as e:
                last_err = e
                time.sleep(1.0)
        raise BackendError(f"Groq call failed after {max_attempts} attempts: {type(last_err).__name__}: {str(last_err)[:200]}")
