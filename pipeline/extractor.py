import re
import json
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from config.settings import settings
from pipeline.models import ExtractionResult, DocumentContent
from pipeline.document_loader import load_document
from pipeline.ocr_engine import get_best_document_text
from pipeline.validator import InvoiceValidator
from pipeline.cost_tracker import CostTracker
from pipeline.pii_shield import PIIShield, PIIDetectionResult
from ai_backends.base import AIBackend
from ai_backends.router import get_backend

def parse_llm_json(raw: str) -> Dict[str, Any]:
    """
    Robustly extract and parse JSON object from LLM response strings.
    Handles markdown formatting, extraneous commentary, and common syntax glitches.
    """
    if isinstance(raw, dict):
        return raw

    text = raw.strip()

    # 1. Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # 2. Extract content between the first '{' and the last '}'
    first_brace = text.find("{")
    last_brace = text.rfind("}")

    if first_brace == -1 or last_brace == -1 or last_brace < first_brace:
        raise ValueError(f"No JSON object detected in response. Raw prefix: {text[:200]}")

    candidate_str = text[first_brace:last_brace + 1]

    # 3. Clean up common LLM JSON syntax issues (e.g. trailing commas before braces)
    candidate_str = re.sub(r",\s*([}\]])", r"\1", candidate_str)

    try:
        return json.loads(candidate_str)
    except json.JSONDecodeError as e:
        # Secondary fallback: replace single quotes with double quotes if needed
        try:
            fixed_str = re.sub(r"(?<=\w)'(?=\w)", "’", candidate_str) # preserve contractions
            fixed_str = fixed_str.replace("'", '"')
            return json.loads(fixed_str)
        except Exception:
            raise ValueError(f"JSON decoding failed: {e}. Payload snippet: {candidate_str[:300]}")

class InvoiceExtractor:
    """
    Orchestrates end-to-end document extraction:
    intake -> OCR/text loading -> AI extraction -> JSON parsing -> validation -> retry loop.
    """

    def __init__(self, backend: Optional[AIBackend] = None):
        self.backend = backend or get_backend()
        self.validator = InvoiceValidator()
        self.cost_tracker = CostTracker()

    def extract(self, file_path: Path) -> ExtractionResult:
        file_name = file_path.name

        # 1. Document loading
        doc = load_document(file_path)
        if not doc.is_readable:
            return ExtractionResult.error_result(file_name, doc.error or "Corrupt or unreadable file.")

        # 2. Text resolution (PyMuPDF embedded text + Tesseract fallback)
        text = get_best_document_text(doc)

        # 2b. Enterprise PII Redaction Shield (Sanitize sensitive banking/national IDs before external cloud LLMs)
        pii_result = PIIShield.sanitize_text(text, mask_enabled=getattr(settings, "pii_shield_enabled", True))
        prompt_text = pii_result.masked_text if self.backend.name != "No-AI (Rule-Based & Regex Engine)" else text

        # 3. First extraction attempt
        try:
            raw_response, usage = self.backend.extract(prompt_text, doc.images)
        except Exception as e:
            return ExtractionResult.error_result(file_name, f"Extraction failed at backend: {str(e)}")

        cost_rec = self.cost_tracker.record(file_name, usage)

        # 4. JSON Parsing
        parsed_data = None
        try:
            parsed_data = parse_llm_json(raw_response)
        except ValueError as parse_err:
            # Immediate retry requesting strict JSON
            try:
                raw_response, usage_retry = self.backend.extract(
                    text, doc.images, retry=True,
                    retry_reason=f"Previous output was not valid JSON: {str(parse_err)}"
                )
                self.cost_tracker.record(file_name, usage_retry)
                parsed_data = parse_llm_json(raw_response)
            except Exception:
                return ExtractionResult.error_result(file_name, f"Unparseable JSON output: {str(parse_err)}")

        # 5. Schema & Arithmetic Validation
        validated_obj, issues = self.validator.validate(parsed_data)

        # 6. Self-correction Retry Loop (if validation failed and max_retries > 0)
        retries_left = settings.max_retries
        while issues and retries_left > 0 and self.backend.name != "No-AI (Rule-Based & Regex Engine)":
            retries_left -= 1
            retry_reason = "; ".join(issues)
            try:
                retry_raw, usage_retry = self.backend.extract(
                    text, doc.images, retry=True, retry_reason=retry_reason
                )
                self.cost_tracker.record(file_name, usage_retry)
                candidate_data = parse_llm_json(retry_raw)
                cand_obj, cand_issues = self.validator.validate(candidate_data)
                if not cand_issues:
                    validated_obj, issues = cand_obj, cand_issues
                    parsed_data = candidate_data
                    break
                elif len(cand_issues) < len(issues):
                    # Progress made
                    validated_obj, issues = cand_obj, cand_issues
                    parsed_data = candidate_data
            except Exception:
                break

        # Final structured payload
        final_dict = validated_obj.model_dump() if validated_obj else parsed_data

        # Restore any PII tokens in the local record so internal ledger is 100% complete
        if pii_result.entity_map and final_dict:
            try:
                final_str = json.dumps(final_dict)
                final_str = PIIShield.restore_entities(final_str, pii_result.entity_map)
                final_dict = json.loads(final_str)
            except Exception:
                pass

        return ExtractionResult(
            file=file_name,
            data=final_dict,
            needs_review=bool(issues),
            review_reasons=issues,
            cost=self.cost_tracker.get_latest(file_name),
            error=None
        )
