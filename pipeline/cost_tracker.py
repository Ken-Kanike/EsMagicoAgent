from typing import List, Dict, Any, Optional
from pipeline.models import TokenUsage, CostRecord

PRICING_TABLE = {
    "no_ai": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "description": "Rule-based regex engine (Zero AI cost)"
    },
    "local": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "description": "Local Open Source Model (Zero cloud cost)"
    },
    "groq_free": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "description": "Groq Cloud Free Tier"
    },
    "groq_paid_llama33": {
        "input_per_1k": 0.00059,
        "output_per_1k": 0.00079,
        "description": "Groq Llama 3.3 70B Versatile (Paid rate)"
    },
    "gemini_15_flash": {
        "input_per_1k": 0.000075,
        "output_per_1k": 0.000300,
        "description": "Google Gemini 1.5 Flash (Commercial tier)"
    },
    "gpt_4o_mini": {
        "input_per_1k": 0.000150,
        "output_per_1k": 0.000600,
        "description": "OpenAI GPT-4o-mini"
    },
    "gpt_4o": {
        "input_per_1k": 0.002500,
        "output_per_1k": 0.010000,
        "description": "OpenAI GPT-4o Full Model"
    }
}

class CostTracker:
    """Tracks token consumption and calculates exact USD costs across backends."""

    def __init__(self):
        self.records: List[CostRecord] = []

    def record(self, file_name: str, usage: TokenUsage) -> CostRecord:
        pricing = PRICING_TABLE.get(usage.model_pricing_key, PRICING_TABLE["groq_free"])
        cost = (
            (usage.prompt_tokens / 1000.0) * pricing["input_per_1k"] +
            (usage.completion_tokens / 1000.0) * pricing["output_per_1k"]
        )

        rec = CostRecord(
            file=file_name,
            mode=usage.mode,
            model=usage.model,
            tokens_in=usage.prompt_tokens,
            tokens_out=usage.completion_tokens,
            cost_usd=round(cost, 6)
        )
        self.records.append(rec)
        return rec

    def get_latest(self, file_name: str) -> Optional[CostRecord]:
        for rec in reversed(self.records):
            if rec.file == file_name:
                return rec
        return None

    def get_summary(self) -> Dict[str, Any]:
        total_in = sum(r.tokens_in for r in self.records)
        total_out = sum(r.tokens_out for r in self.records)
        total_cost = sum(r.cost_usd for r in self.records)
        count = len(self.records)

        # Baseline cost comparison estimates across the entire set
        gpt4o_mini_cost = (total_in / 1000.0) * 0.00015 + (total_out / 1000.0) * 0.0006
        gemini_flash_cost = (total_in / 1000.0) * 0.000075 + (total_out / 1000.0) * 0.0003
        groq_paid_cost = (total_in / 1000.0) * 0.00059 + (total_out / 1000.0) * 0.00079

        return {
            "documents_processed": count,
            "total_tokens_in": total_in,
            "total_tokens_out": total_out,
            "total_cost_usd": round(total_cost, 6),
            "avg_cost_per_doc": round(total_cost / count, 6) if count else 0.0,
            "comparison_benchmarks": {
                "groq_free_actual": 0.0,
                "gemini_15_flash_est": round(gemini_flash_cost, 6),
                "gpt_4o_mini_est": round(gpt4o_mini_cost, 6),
                "groq_paid_est": round(groq_paid_cost, 6),
            }
        }
