import io
import base64
from typing import List
from PIL import Image

SYSTEM_PROMPT = """You are an expert financial document intelligence system. Your sole task is to extract structured invoice data from documents according to the required JSON schema.

CRITICAL RULES AND SPECIFICATIONS:
1. Output format: Return ONLY a valid JSON object matching the schema below. No conversational text, no markdown backticks, no explanations.
2. Non-invoices:
   - If the document is NOT an invoice (e.g. purchase order, bank statement, letter, quote, packing list):
     Set "is_invoice": false, and ALL other 7 fields to null.
3. Vendor:
   - The seller/issuer entity printed at the top/header of the invoice. NOT the buyer / customer / consignee.
4. Invoice Number:
   - Exact alphanumeric string as printed (e.g. "NWL-88213", "SGS/1847", "KOM/26-27/00418").
5. Invoice Date:
   - MUST be formatted strictly as ISO 8601 string: "YYYY-MM-DD".
   - Be context-aware of Day-First (e.g. UK/India "08/04/2026" -> "2026-04-08") vs Month-First (e.g. US).
6. Currency:
   - 3-letter uppercase ISO 4217 code (e.g. "INR", "USD", "GBP", "EUR").
   - Convert symbols: "₹" / "Rs." -> "INR", "$" -> "USD", "£" -> "GBP", "€" -> "EUR".
7. Line Items:
   - Capture EVERY row in the item/charges table in the printed order.
   - Surcharges, freight, handling fees, setup fees printed in the table ARE line items.
   - Discounts appearing in the item table must be captured with NEGATIVE amount (e.g. -450.0).
   - If a row has no quantity printed (e.g. service retainer, flat charge), set "quantity": null.
   - If fractional quantities exist (e.g. 12.5 kg), capture as float (12.5).
   - "amount" is the row line total before tax.
8. Tax Total:
   - Sum of all tax components (GST, VAT, CGST, SGST, sales tax).
   - If no tax or zero tax is printed, return 0 or 0.0.
9. Total:
   - Final payable amount after tax and discounts.
   - Ensure the arithmetic balance holds: sum(line_items.amount) + tax_total == total.
10. All numeric fields ("quantity", "amount", "tax_total", "total") must be plain numbers without commas or currency symbols.

SCHEMA:
{
  "is_invoice": true,
  "vendor": "String or null",
  "invoice_number": "String or null",
  "invoice_date": "YYYY-MM-DD or null",
  "currency": "3-letter ISO code or null",
  "line_items": [
    {
      "description": "String",
      "quantity": 1.0 or null,
      "amount": 100.0
    }
  ] or null,
  "tax_total": 0.0 or null,
  "total": 100.0 or null
}
"""

USER_PROMPT_TEXT = """Extract the invoice information from the text below according to the system instructions.

--- DOCUMENT TEXT START ---
{document_text}
--- DOCUMENT TEXT END ---
"""

USER_PROMPT_RETRY = """Your previous extraction failed validation with the following issues:
{issues}

Please carefully re-read the document, fix the identified discrepancies, and output the corrected JSON object.
Ensure:
1. sum(line_items.amount) + tax_total equals total (within standard rounding).
2. Dates are strictly YYYY-MM-DD.
3. Discounts are entered with negative amounts.

--- DOCUMENT TEXT START ---
{document_text}
--- DOCUMENT TEXT END ---
"""

def image_to_base64_jpeg(image: Image.Image, max_dimension: int = 1600) -> str:
    """Resize image if needed and encode as JPEG base64 string."""
    img = image.copy()
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    
    # Scale down if exceeds max_dimension to preserve API rate limits and token budgets
    width, height = img.size
    if max(width, height) > max_dimension:
        ratio = max_dimension / float(max(width, height))
        img = img.resize((int(width * ratio), int(height * ratio)), Image.Resampling.LANCZOS)
    
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def build_vision_messages(text: str, images: List[Image.Image], is_retry: bool = False, retry_reason: str = "") -> List[dict]:
    """Construct multi-modal message list for vision-enabled LLMs (Groq, OpenAI, Gemini)."""
    user_prompt = (
        USER_PROMPT_RETRY.format(issues=retry_reason, document_text=text[:6000])
        if is_retry else
        USER_PROMPT_TEXT.format(document_text=text[:6000])
    )

    content_parts = [
        {"type": "text", "text": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}
    ]

    # Attach up to 3 page images
    for img in images[:3]:
        b64 = image_to_base64_jpeg(img)
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    return [{"role": "user", "content": content_parts}]
