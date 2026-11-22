"""
Token -> USD cost accounting.

Prices are USD per 1K tokens. For Groq models the table is overwritten at start-up
with the live list prices published by Groq's /models endpoint. Groq's free tier
bills $0, but we always report the *list-price* cost so the number is meaningful
for a paid deployment.
"""
import threading
from typing import Any, Dict, List, Optional

from pipeline.models import CostRecord, TokenUsage

_lock = threading.Lock()

# Static fallbacks (USD per 1K tokens). Verify against provider pricing pages before quoting.
PRICING_TABLE: Dict[str, Dict[str, Any]] = {
    "no_ai": {"input_per_1k": 0.0, "output_per_1k": 0.0, "source": "rule engine"},
    "local": {"input_per_1k": 0.0, "output_per_1k": 0.0, "source": "local model"},
    "qwen/qwen3.8-27b": {"input_per_1k": 0.0008, "output_per_1k": 0.004, "source": "groq /models (2026-11-21)"},
    "openai/gpt-oss-120b": {"input_per_1k": 0.00015, "output_per_1k": 0.0006, "source": "groq /models (2026-11-21)"},
    "openai/gpt-oss-20b": {"input_per_1k": 0.000075, "output_per_1k": 0.0003, "source": "groq /models (2026-11-21)"},
    "gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006, "source": "static"},
    "gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.01, "source": "static"},
}


def register_price(model: str, input_per_1k: float, output_per_1k: float, source: str = "live"):
    with _lock:
        PRICING_TABLE[model] = {"input_per_1k": input_per_1k, "output_per_1k": output_per_1k, "source": source}


def price_for(model_key: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return PRICING_TABLE.get(model_key)


def cost_of(usage: TokenUsage) -> float:
    p = price_for(usage.model_pricing_key) or price_for(usage.mode)
    if not p:
        return 0.0
    return (usage.prompt_tokens / 1000.0) * p["input_per_1k"] + (usage.completion_tokens / 1000.0) * p["output_per_1k"]


class CostTracker:
    """Per-document accumulator. Create one per extraction (not shared across threads)."""

    def __init__(self):
        self.records: List[CostRecord] = []

    def record(self, file_name: str, usage: TokenUsage) -> CostRecord:
        rec = CostRecord(
            file=file_name, mode=usage.mode, model=usage.model_pricing_key or usage.model,
            tokens_in=usage.prompt_tokens, tokens_out=usage.completion_tokens,
            cost_usd=round(cost_of(usage), 8),
        )
        self.records.append(rec)
        return rec

    def total(self, file_name: str) -> Optional[CostRecord]:
        recs = [r for r in self.records if r.file == file_name]
        if not recs:
            return None
        models = sorted({r.model for r in recs})
        return CostRecord(
            file=file_name, mode=recs[0].mode, model="+".join(models),
            tokens_in=sum(r.tokens_in for r in recs), tokens_out=sum(r.tokens_out for r in recs),
            cost_usd=round(sum(r.cost_usd for r in recs), 8), calls=len(recs),
        )
