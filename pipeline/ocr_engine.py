import os
from typing import Optional, List
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
from config.settings import settings
from pipeline.models import DocumentContent

_rapidocr_instance = None

def get_rapidocr():
    """Lazy initialize RapidOCR engine."""
    global _rapidocr_instance
    if _rapidocr_instance is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapidocr_instance = RapidOCR()
        except Exception:
            _rapidocr_instance = False
    return _rapidocr_instance if _rapidocr_instance is not False else None

def ocr_image(image: Image.Image, lang: str = "eng") -> str:
    """Run OCR on image using RapidOCR (preferred) or Tesseract fallback."""
    # 1. Try RapidOCR (ONNX model, zero external binaries)
    engine = get_rapidocr()
    if engine:
        try:
            img_arr = np.array(image.convert("RGB"))
            res, _ = engine(img_arr)
            if res:
                return "\n".join([line[1] for line in res]).strip()
        except Exception:
            pass

    # 2. Try Tesseract as fallback
    try:
        import pytesseract
        candidates = [
            settings.tesseract_path,
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            "tesseract"
        ]
        for p in candidates:
            if p and (os.path.exists(p) or p == "tesseract"):
                pytesseract.pytesseract.tesseract_cmd = p
                break
        preprocessed = image.convert("L")
        preprocessed = ImageEnhance.Contrast(preprocessed).enhance(2.0)
        return pytesseract.image_to_string(preprocessed, lang=lang, config="--oem 3 --psm 6").strip()
    except Exception:
        return ""

def get_best_document_text(doc: DocumentContent) -> str:
    """
    Extract best available text from document.
    Prioritizes embedded PDF text. Falls back to RapidOCR for scanned images or empty PDFs.
    """
    # If the document has sufficient direct text (>100 chars), return it
    if doc.text and len(doc.text.strip()) > 80:
        return doc.text

    # Run OCR if document has images
    if doc.images:
        ocr_parts: List[str] = []
        for img in doc.images:
            part = ocr_image(img)
            if part:
                ocr_parts.append(part)
        if ocr_parts:
            return "\n\n--- PAGE BREAK ---\n\n".join(ocr_parts).strip()

    return doc.text or ""
