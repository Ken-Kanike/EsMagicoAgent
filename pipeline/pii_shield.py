import re
from typing import Dict, Any, Tuple, List, Optional
from pydantic import BaseModel

class PIIDetectionResult(BaseModel):
    has_pii: bool
    detected_types: List[str]
    masked_text: str
    redaction_count: int
    entity_map: Dict[str, str]  # Maps token e.g. [REDACTED_ACC_1] -> original value

class PIIShield:
    """
    Enterprise PII (Personally Identifiable Information) Redaction & Privacy Shield.
    
    Protects banking information, credit card numbers, national identification numbers,
    phone numbers, and personal emails before transmitting prompt text to public/external AI models.
    """

    # 1. Bank Account / IBAN Patterns (8-18 digit numeric sequences near account keywords)
    BANK_REGEX = re.compile(
        r'\b(?:A/C|Account(?:\s+No\.?|\s+Number)?|IBAN|Acc\.?\s*#?)\s*[:#-]?\s*([A-Z]{2}\d{2}[A-Z0-9]{4,30}|\d{9,18})\b',
        re.IGNORECASE
    )

    # 2. Credit / Debit Card Numbers (13-19 digits, space or dash separated)
    CREDIT_CARD_REGEX = re.compile(
        r'\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{15,16}\b'
    )

    # 3. Phone Numbers (International and domestic formats)
    PHONE_REGEX = re.compile(
        r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    )

    # 4. Personal Email Addresses
    EMAIL_REGEX = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'
    )

    # 5. National IDs: US SSN (XXX-XX-XXXX) or Indian PAN (5 letters, 4 digits, 1 letter)
    SSN_REGEX = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
    PAN_REGEX = re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b')

    @classmethod
    def sanitize_text(cls, text: str, mask_enabled: bool = True) -> PIIDetectionResult:
        """
        Scans and optionally masks PII in text before it is dispatched to external AI models.
        Returns PIIDetectionResult containing masked text and reversible entity mapping.
        """
        if not text or not mask_enabled:
            return PIIDetectionResult(
                has_pii=False,
                detected_types=[],
                masked_text=text or "",
                redaction_count=0,
                entity_map={}
            )

        sanitized = text
        entity_map: Dict[str, str] = {}
        detected_types: List[str] = []
        counter = 0

        # Mask Bank Accounts
        for match in cls.BANK_REGEX.finditer(sanitized):
            acc_val = match.group(1)
            token = f"[REDACTED_BANK_ACC_{counter}]"
            entity_map[token] = acc_val
            sanitized = sanitized.replace(acc_val, token, 1)
            detected_types.append("Bank Account")
            counter += 1

        # Mask Credit Cards
        for match in cls.CREDIT_CARD_REGEX.finditer(sanitized):
            card_val = match.group(0)
            token = f"[REDACTED_CARD_{counter}]"
            entity_map[token] = card_val
            sanitized = sanitized.replace(card_val, token, 1)
            detected_types.append("Credit Card")
            counter += 1

        # Mask SSN
        for match in cls.SSN_REGEX.finditer(sanitized):
            ssn_val = match.group(0)
            token = f"[REDACTED_SSN_{counter}]"
            entity_map[token] = ssn_val
            sanitized = sanitized.replace(ssn_val, token, 1)
            detected_types.append("SSN / Tax ID")
            counter += 1

        # Mask PAN
        for match in cls.PAN_REGEX.finditer(sanitized):
            pan_val = match.group(0)
            token = f"[REDACTED_PAN_{counter}]"
            entity_map[token] = pan_val
            sanitized = sanitized.replace(pan_val, token, 1)
            detected_types.append("National Tax ID")
            counter += 1

        # Mask Personal Phone Numbers
        for match in cls.PHONE_REGEX.finditer(sanitized):
            phone_val = match.group(0)
            token = f"[REDACTED_PHONE_{counter}]"
            entity_map[token] = phone_val
            sanitized = sanitized.replace(phone_val, token, 1)
            detected_types.append("Phone Number")
            counter += 1

        # Mask Personal Emails
        for match in cls.EMAIL_REGEX.finditer(sanitized):
            email_val = match.group(0)
            token = f"[REDACTED_EMAIL_{counter}]"
            entity_map[token] = email_val
            sanitized = sanitized.replace(email_val, token, 1)
            detected_types.append("Email Address")
            counter += 1

        unique_types = sorted(list(set(detected_types)))
        return PIIDetectionResult(
            has_pii=len(unique_types) > 0,
            detected_types=unique_types,
            masked_text=sanitized,
            redaction_count=len(entity_map),
            entity_map=entity_map
        )

    @classmethod
    def restore_entities(cls, text: str, entity_map: Dict[str, str]) -> str:
        """
        Reverses masking on received structured output so final database records
        retain legitimate values while keeping external cloud inference 100% blind to PII.
        """
        restored = text
        for token, original in entity_map.items():
            restored = restored.replace(token, original)
        return restored
