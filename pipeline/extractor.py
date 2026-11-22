"""
End-to-end extraction:

  load -> choose inputs (page images and/or embedded text, OCR only if the model is text-only)
       -> LLM (JSON mode) -> parse -> normalise -> validate
       -> corrective retries with the validation errors (multi-turn, same document context)
       -> keep the best attempt -> needs_review flag + reasons

The rule-based baseline (no_ai) goes through the same normalise/validate path,
so its review flags are comparable.
"""
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_backends.base import AIBackend, BackendError
from ai_backends.router import get_backend
from config.prompts import (PROMPT_VERSION, append_parse_retry, append_retry,
                            build_messages, encode_images)
from config.settings import settings

# Bump when page-image preprocessing changes (v2: auto-upright for sideways scans, v3: 200 dpi).
IMAGE_PIPELINE_VERSION = "img-v3"
from pipeline import cache
from pipeline.cost_tracker import CostTracker
from pipeline.document_loader import load_document
from pipeline.models import ExtractionResult
from pipeline.normalizer import normalize_payload
from pipeline.ocr_engine import get_best_document_text, has_embedded_text
from pipeline.pii_shield import PIIShield
from pipeline.validator import InvoiceValidator, ValidationReport


def parse_llm_json(raw: Any) -> Dict[str, Any]:
    """Extract one JSON object from a model reply (handles fences, prose, trailing commas)."""
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()   # reasoning models
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"No JSON object in response: {text[:120]!r}")
    candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    repaired = re.sub(r"\bTrue\b", "true", re.sub(r"\bFalse\b", "false", repaired))
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e.msg} at char {e.pos}") from e


def _score(rep: ValidationReport) -> Tuple[int, int, int]:
    """Lower is better: (schema invalid, #errors, #warnings)."""
    return (0 if rep.obj is not None else 1, len(rep.errors), len(rep.warnings))


class InvoiceExtractor:
    def __init__(self, backend: Optional[AIBackend] = None, use_cache: Optional[bool] = None):
        self.backend = backend or get_backend()
        self.validator = InvoiceValidator()
        self.use_cache = settings.cache_enabled if use_cache is None else use_cache

    # ------------------------------------------------------------------ public
    def extract(self, file_path: Path) -> ExtractionResult:
        t0 = time.time()
        file_path = Path(file_path)
        name = file_path.name
        doc = load_document(file_path)
        if not doc.is_readable:
            etype = "unsupported" if (doc.error or "").startswith("Unsupported") else "corrupt_file"
            res = ExtractionResult.error_result(name, doc.error or "Unreadable file.", etype, self.backend.name)
            res.elapsed_s = round(time.time() - t0, 3)
            return res

        key = None
        if self.use_cache:
            key = cache.make_key(cache.file_sha256(file_path), self.backend.cache_id(), PROMPT_VERSION,
                                 str(settings.pii_shield_enabled), str(settings.max_retries),
                                 str(settings.route_digital_to_text), settings.groq_reasoning_effort,
                                 IMAGE_PIPELINE_VERSION)
            hit = cache.get("extractions", key)
            if hit:
                res = ExtractionResult.from_dict(hit)
                res.file, res.cached = name, True
                res.elapsed_s = round(time.time() - t0, 3)
                return res

        try:
            res = self._extract_llm(doc, name) if self.backend.is_llm else self._extract_rules(doc, name)
        except BackendError as e:
            res = ExtractionResult.error_result(name, f"Model call failed: {e}", "backend_error", self.backend.name)
        except ValueError as e:
            res = ExtractionResult.error_result(name, f"Model output was not valid JSON after a repair attempt: {e}",
                                                "unparseable", self.backend.name)
        except Exception as e:  # never crash a batch on one document
            res = ExtractionResult.error_result(name, f"Unexpected error: {type(e).__name__}: {e}",
                                                "internal_error", self.backend.name)
        res.elapsed_s = round(time.time() - t0, 3)
        if key and res.error_type not in ("backend_error", "internal_error"):
            cache.put("extractions", key, res.to_dict())
        return res

    # --------------------------------------------------------------- baseline
    def _extract_rules(self, doc, name: str) -> ExtractionResult:
        t = time.time()
        text = get_best_document_text(doc, layout="raw")
        t_text = time.time() - t
        data = normalize_payload(self.backend.extract_rules(text))  # type: ignore[attr-defined]
        rep = self.validator.check(data)
        final = rep.obj.model_dump() if rep.obj else data
        reasons = rep.all_issues + ([] if text.strip() else ["No text could be read from the document (OCR empty)."])
        return ExtractionResult(
            file=name, data=final, needs_review=bool(reasons), review_reasons=reasons,
            backend=self.backend.name, attempts=1,
            timings={"text_or_ocr": round(t_text, 3), "extract": round(time.time() - t - t_text, 3)},
        )

    # -------------------------------------------------------------------- LLM
    def _prepare_inputs(self, doc) -> Tuple[str, List[str], str, List[str]]:
        notes: List[str] = []
        embedded = has_embedded_text(doc)
        images_b64: List[str] = []
        text_only_route = (embedded and settings.route_digital_to_text
                           and self.backend.model_for(False) != self.backend.model_for(True))
        if text_only_route:  # the text layer covers every page, so no page limit applies
            return doc.layout_text, [], "embedded", notes
        if self.backend.supports_vision:
            images_b64 = encode_images(doc.images, settings.max_image_side)
            if doc.pages_truncated:
                notes.append(f"Only the first {settings.max_pages} of {doc.page_count} pages were read.")
        if embedded:
            return doc.layout_text, images_b64, "embedded", notes
        if images_b64:
            return "", images_b64, "none", notes
        ocr = get_best_document_text(doc, layout="lines")
        if not ocr.strip():
            notes.append("Text-only model and OCR returned no text.")
        return ocr, [], "ocr", notes

    def _extract_llm(self, doc, name: str) -> ExtractionResult:
        tracker = CostTracker()
        timings: Dict[str, float] = {}

        t = time.time()
        text, images_b64, source, notes = self._prepare_inputs(doc)
        timings["prepare"] = round(time.time() - t, 3)

        pii = PIIShield.sanitize_text(text, mask_enabled=settings.pii_shield_enabled)
        messages = build_messages(pii.masked_text, images_b64, source)

        attempts = 0
        t = time.time()
        raw, usage = self.backend.chat(messages)
        attempts += 1
        tracker.record(name, usage)

        # JSON parse (one repair round-trip if needed)
        try:
            parsed = parse_llm_json(raw)
        except ValueError as e:
            messages = append_parse_retry(messages, raw, str(e))
            raw, usage = self.backend.chat(messages)
            attempts += 1
            tracker.record(name, usage)
            parsed = parse_llm_json(raw)  # raises -> handled below

        data = normalize_payload(PIIShield.restore_in_obj(parsed, pii.entity_map))
        rep = self.validator.check(data)
        best_data, best_rep, best_raw = data, rep, raw

        retries = settings.max_retries
        while best_rep.errors and retries > 0:
            retries -= 1
            messages = append_retry(messages, best_raw, best_rep.errors + best_rep.warnings)
            try:
                raw, usage = self.backend.chat(messages)
                attempts += 1
                tracker.record(name, usage)
                cand = normalize_payload(PIIShield.restore_in_obj(parse_llm_json(raw), pii.entity_map))
            except (ValueError, BackendError):
                break
            cand_rep = self.validator.check(cand)
            if _score(cand_rep) <= _score(best_rep):
                best_data, best_rep, best_raw = cand, cand_rep, raw
        timings["llm"] = round(time.time() - t, 3)

        final = best_rep.obj.model_dump() if best_rep.obj else best_data
        reasons = best_rep.errors + best_rep.warnings + notes
        return ExtractionResult(
            file=name, data=final, needs_review=bool(reasons), review_reasons=reasons,
            cost=tracker.total(name), backend=self.backend.name, attempts=attempts, timings=timings,
        )
