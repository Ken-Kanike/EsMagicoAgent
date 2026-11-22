"""
Prompts for invoice extraction.

The rules below are a restatement of the labelling conventions published in the
sample pack README (not tuned per-document). PROMPT_VERSION is part of the cache
key, so changing the prompt invalidates cached results.
"""
import base64
import io
import json
from typing import Any, Dict, List, Optional

from PIL import Image

PROMPT_VERSION = "v5"

SYSTEM_PROMPT = """You are a meticulous accounts-payable data-entry specialist. You read one business document and return its data as a single JSON object. You never guess: every value must be visible in the document.

STEP 1 - CLASSIFY
is_invoice = true only if the document is an invoice / tax invoice / bill requesting payment for goods or services (any language: Rechnung, Facture, Factura, Fattura, Factuur...).
Purchase orders, quotations, proforma/estimates, delivery notes, receipts of payment, bank or account statements, credit notes, letters, CVs, forms and anything else => is_invoice = false.
If is_invoice is false, every other field MUST be null. Stop there.

STEP 2 - EXTRACT (invoices only)
- vendor: the SELLER who issued the invoice, as printed at the top (letterhead / "From"). Never the buyer, "Bill to", "Ship to" or consignee.
- invoice_number: exactly as printed (keep prefixes, slashes, dashes). Not the PO number, order number or customer id.
- invoice_date: the ISSUE date of the invoice, formatted YYYY-MM-DD. Not the due date, order date, PO date, delivery or check-in date.
  Resolve ambiguous numeric dates from context: Indian/UK/European documents are day-first (07/02/2026 = 2026-02-07); US documents (USD, US address) are month-first (09/14/2026 = 2026-09-14). Use the due date or other dates on the page as a consistency check.
- due_date: the payment due date if printed, YYYY-MM-DD, else null (helper field used only to check invoice_date; read the YEAR of both dates carefully).
- currency: ISO 4217 code (INR, USD, EUR, GBP, JPY, AED...). Rs / ₹ = INR, $ = USD unless the document says otherwise, € = EUR, £ = GBP.
- line_items: one object per row of the item table, in printed order.
  * description: the row text as printed (the main description cell; do not invent text).
  * quantity: the number in the quantity column; null if the row has no quantity (blank, "-", flat fee, retainer, discount, service charge row). Never put a rate, an amount, or a code (HSN/SAC, SKU, part number, item code) in quantity.
  * unit_price: the per-unit rate printed in the row, or null if none (helper field used for checking; quantity x unit_price should equal amount).
  * amount: the row total BEFORE tax, as a plain number.
  * Charges and discounts that appear as rows inside the item table are line items too. A discount is a NEGATIVE amount.
  * Subtotal, tax, and total rows are NOT line items.
- tax_total: the SUM of every tax line on the invoice (GST, CGST + SGST, IGST, VAT at each rate, MwSt, sales tax, cess). If the invoice shows zero tax or no tax at all, use 0.
- total: the final amount payable including tax ("Grand total", "Amount due", "Total", "Gesamtbetrag").

NUMBERS
- Plain JSON numbers: no currency symbols, no thousands separators. Read the document's locale: "1.136,25" (European) = 1136.25; "1,136.25" = 1136.25; "12,00,000.00" (Indian) = 1200000.00.
- Copy amounts exactly as printed. Do not recompute or "fix" printed numbers.

SELF-CHECK BEFORE ANSWERING
- For every row with a quantity and a unit price: quantity x unit_price should equal amount. If not, you probably took a code column as quantity.
- sum(line_items.amount) + tax_total should equal total (within rounding). If it does not, re-read the table and tax lines; if the document itself is inconsistent, still report what is printed.

OUTPUT
Return ONLY this JSON object, no markdown, no commentary:
{"is_invoice": bool, "vendor": string|null, "invoice_number": string|null, "invoice_date": "YYYY-MM-DD"|null, "due_date": "YYYY-MM-DD"|null, "currency": string|null, "line_items": [{"description": string, "quantity": number|null, "unit_price": number|null, "amount": number}]|null, "tax_total": number|null, "total": number|null}"""

USER_PROMPT_WITH_TEXT = """Extract the invoice data from this document.
{image_note}The machine-readable text layer of the document is below. It is exact for spelling and numbers, but table layout may be scrambled; use the page image(s) for layout when available.

--- DOCUMENT TEXT START ---
{document_text}
--- DOCUMENT TEXT END ---"""

USER_PROMPT_IMAGE_ONLY = """Extract the invoice data from the attached page image(s). The document is a scan or photo; read it carefully, especially digits in amounts and the invoice number."""

USER_PROMPT_OCR_TEXT = """Extract the invoice data from this document. It is a scan; the text below was produced by OCR and may contain recognition errors (0/O, 1/l, merged words). Correct obvious OCR errors only when the meaning is unambiguous.

--- OCR TEXT START ---
{document_text}
--- OCR TEXT END ---"""

RETRY_PROMPT = """Your previous answer failed automatic validation:
{issues}

Re-read the document carefully (item table, tax lines, totals, dates) and return the corrected JSON object. Only change values that are actually wrong; report what is printed on the document. Return ONLY the JSON object."""

PARSE_RETRY_PROMPT = """Your previous answer was not a valid JSON object ({error}). Return ONLY the JSON object described in the instructions, with no other text."""

MAX_TEXT_CHARS = 12000


def image_to_base64_jpeg(image: Image.Image, max_dimension: int = 1800, quality: int = 88) -> str:
    img = image if image.mode == "RGB" else image.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dimension:
        r = max_dimension / float(max(w, h))
        img = img.resize((int(w * r), int(h * r)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def encode_images(images: List[Image.Image], max_dimension: int = 1800) -> List[str]:
    return [image_to_base64_jpeg(img, max_dimension) for img in images]


def build_user_content(text: str, images_b64: List[str], text_source: str) -> Any:
    """
    text_source: "embedded" (digital PDF text layer), "ocr", or "none" (image only).
    Returns a string for text-only models, or a list of content parts when images are attached.
    """
    text = (text or "")[:MAX_TEXT_CHARS]
    if text_source == "embedded" and text:
        note = "Page image(s) are attached. " if images_b64 else ""
        prompt = USER_PROMPT_WITH_TEXT.format(image_note=note, document_text=text)
    elif text_source == "ocr" and text:
        prompt = USER_PROMPT_OCR_TEXT.format(document_text=text)
    else:
        prompt = USER_PROMPT_IMAGE_ONLY

    if not images_b64:
        return prompt
    parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for b64 in images_b64:
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return parts


def build_messages(text: str, images_b64: List[str], text_source: str,
                   system_prompt: str = SYSTEM_PROMPT) -> List[Dict[str, Any]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_user_content(text, images_b64, text_source)},
    ]


def append_retry(messages: List[Dict[str, Any]], previous_answer: str, issues: List[str]) -> List[Dict[str, Any]]:
    """Multi-turn correction: keep the document in context, show the model its answer and the errors."""
    issue_text = "\n".join(f"- {i}" for i in issues)
    return messages + [
        {"role": "assistant", "content": previous_answer},
        {"role": "user", "content": RETRY_PROMPT.format(issues=issue_text)},
    ]


def append_parse_retry(messages: List[Dict[str, Any]], previous_answer: str, error: str) -> List[Dict[str, Any]]:
    return messages + [
        {"role": "assistant", "content": (previous_answer or "")[:2000]},
        {"role": "user", "content": PARSE_RETRY_PROMPT.format(error=error[:200])},
    ]


def compact_json(obj: Optional[Dict[str, Any]]) -> str:
    return json.dumps(obj, ensure_ascii=False)
