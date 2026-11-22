"""
Optional PII redaction for the TEXT sent to cloud models.

Scope and honest limits:
- Masks only values never needed for the 8 output fields: labelled bank account
  numbers, IBANs, Luhn-valid card numbers, emails, labelled/international phone
  numbers, US SSNs and Indian PAN numbers.
- Matching is replaced by position (not by first occurrence of the string), so
  invoice numbers and amounts are not corrupted.
- Page IMAGES sent to a vision model are NOT redacted. With a vision backend the
  shield therefore reduces, but does not eliminate, PII exposure. Use the local
  backend if documents must never leave the machine.
"""
import re
from typing import Dict, List, Tuple

from pydantic import BaseModel


class PIIDetectionResult(BaseModel):
    has_pii: bool
    detected_types: List[str]
    masked_text: str
    redaction_count: int
    entity_map: Dict[str, str]


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


class PIIShield:
    PATTERNS: List[Tuple[str, "re.Pattern[str]", int]] = [
        ("IBAN", re.compile(r"\b([A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?)\b"), 1),
        ("BANK_ACCOUNT", re.compile(
            r"(?:A/?C|Account|Acct|Acc)\.?\s*(?:No\.?|Number|#)?\s*[:#\-]?\s*(\d[\d \-]{7,20}\d)", re.I), 1),
        ("CARD", re.compile(r"\b((?:\d[ \-]?){12,18}\d)\b"), 1),
        ("EMAIL", re.compile(r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"), 1),
        ("PHONE", re.compile(
            r"(?:(?:Tel|Phone|Ph|Mob(?:ile)?|Cell|Contact)\.?\s*(?:No\.?)?\s*[:\-]?\s*)(\+?\d[\d \-()]{7,16}\d)", re.I), 1),
        ("PHONE", re.compile(r"(?<![\w/])(\+\d{1,3}[ \-]?\d[\d \-]{6,14}\d)"), 1),
        ("SSN", re.compile(r"\b(\d{3}-\d{2}-\d{4})\b"), 1),
        ("PAN", re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b"), 1),
    ]

    @classmethod
    def sanitize_text(cls, text: str, mask_enabled: bool = True) -> PIIDetectionResult:
        if not text or not mask_enabled:
            return PIIDetectionResult(has_pii=False, detected_types=[], masked_text=text or "",
                                      redaction_count=0, entity_map={})
        spans: List[Tuple[int, int, str, str]] = []
        for kind, pat, grp in cls.PATTERNS:
            for m in pat.finditer(text):
                val = m.group(grp)
                if kind == "CARD":
                    digits = re.sub(r"\D", "", val)
                    if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                        continue
                s, e = m.span(grp)
                if any(not (e <= a or s >= b) for a, b, _, _ in spans):
                    continue  # overlaps an earlier, more specific match
                spans.append((s, e, kind, val))

        spans.sort()
        out, last, entity_map, types = [], 0, {}, []
        for i, (s, e, kind, val) in enumerate(spans):
            token = f"[REDACTED_{kind}_{i}]"
            out.append(text[last:s])
            out.append(token)
            entity_map[token] = val
            types.append(kind)
            last = e
        out.append(text[last:])
        return PIIDetectionResult(
            has_pii=bool(spans), detected_types=sorted(set(types)), masked_text="".join(out),
            redaction_count=len(spans), entity_map=entity_map,
        )

    @classmethod
    def restore_entities(cls, text: str, entity_map: Dict[str, str]) -> str:
        for token, original in entity_map.items():
            text = text.replace(token, original)
        return text

    @classmethod
    def restore_in_obj(cls, obj, entity_map: Dict[str, str]):
        if not entity_map:
            return obj
        if isinstance(obj, str):
            return cls.restore_entities(obj, entity_map)
        if isinstance(obj, list):
            return [cls.restore_in_obj(x, entity_map) for x in obj]
        if isinstance(obj, dict):
            return {k: cls.restore_in_obj(v, entity_map) for k, v in obj.items()}
        return obj
