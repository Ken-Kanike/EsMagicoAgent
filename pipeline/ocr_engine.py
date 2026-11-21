import os
from typing import Optional, List
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
from config.settings import settings
from pipeline.models import DocumentContent

_tesseract_checked = False
_tesseract_available = False

def check_tesseract_available() -> bool:
    """Check if the Tesseract binary is available and functional."""
    global _tesseract_checked, _tesseract_available
    if _tesseract_checked:
        return _tesseract_available

    candidates = [
        settings.tesseract_path,
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Users\junai\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
        "tesseract"
    ]

    for path in candidates:
        if path and (os.path.exists(path) or path == "tesseract"):
            pytesseract.pytesseract.tesseract_cmd = path
            try:
                pytesseract.get_tesseract_version()
                _tesseract_available = True
                _tesseract_checked = True
                return True
            except Exception:
                continue

    _tesseract_available = False
    _tesseract_checked = True
    return False

def preprocess_image(image: Image.Image) -> Image.Image:
    """Enhance image for optical character recognition."""
    img = image.convert("L")  # Convert to grayscale
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)

    # Scale up small images for better OCR resolution
    if img.width < 1200:
        scale = 1200 / float(img.width)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)

    return img

def ocr_image(image: Image.Image, lang: str = "eng") -> str:
    """Run OCR on a single PIL Image."""
    if not check_tesseract_available():
        return ""

    preprocessed = preprocess_image(image)
    config = "--oem 3 --psm 6"
    try:
        return pytesseract.image_to_string(preprocessed, lang=lang, config=config).strip()
    except Exception:
        return ""

def get_best_document_text(doc: DocumentContent) -> str:
    """
    Extract best available text from document.
    Prioritizes embedded PDF text. Falls back to OCR if text is sparse or document is an image.
    """
    # If the document has sufficient direct text (>100 chars), return it
    if doc.text and len(doc.text.strip()) > 100:
        return doc.text

    # If document has images and Tesseract is available, perform OCR
    if doc.images and check_tesseract_available():
        ocr_parts: List[str] = []
        for img in doc.images:
            part = ocr_image(img)
            if part:
                ocr_parts.append(part)
        if ocr_parts:
            return "\n\n--- PAGE BREAK ---\n\n".join(ocr_parts).strip()

    # Otherwise return whatever text was loaded (even if empty)
    return doc.text or ""
