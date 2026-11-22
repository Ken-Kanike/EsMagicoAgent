"""
OCR fallback. Only used by the no_ai baseline and by text-only LLM backends;
vision backends read page images directly and skip OCR entirely.
"""
import os
import threading
from typing import List, Optional

import numpy as np
from PIL import Image, ImageEnhance

from config.settings import settings
from pipeline.models import DocumentContent

_rapidocr_instance = None
_init_lock = threading.Lock()
_run_lock = threading.Lock()

MIN_EMBEDDED_TEXT_CHARS = 80


def get_rapidocr():
    global _rapidocr_instance
    with _init_lock:
        if _rapidocr_instance is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                _rapidocr_instance = RapidOCR()
            except Exception:
                _rapidocr_instance = False
    return _rapidocr_instance or None


def _downscale(image: Image.Image, max_side: int) -> Image.Image:
    w, h = image.size
    if max(w, h) <= max_side:
        return image
    r = max_side / float(max(w, h))
    return image.resize((int(w * r), int(h * r)), Image.Resampling.LANCZOS)


def _rec_score(engine, image: Image.Image) -> float:
    """Mean recognition confidence x number of boxes (higher = text reads upright)."""
    with _run_lock:
        res, _ = engine(np.array(image.convert("RGB")))
    if not res:
        return 0.0
    return sum(float(r[2]) for r in res)


def auto_upright(image: Image.Image) -> Image.Image:
    """
    Fix pages scanned/photographed sideways (90 / 270 degrees). Vision models misread
    rotated pages (U05: invoice number and year wrong), so we straighten them first.

    1. Text detection only, on a <=960px copy (~0.5 s): if most text boxes are taller
       than wide, the page is sideways.
    2. Recognise both candidate rotations and keep the one that reads with higher confidence.
    Upright pages cost only step 1. 180-degree pages are not handled.
    """
    engine = get_rapidocr()
    if not engine:
        return image
    small = _downscale(image, 960)
    try:
        with _run_lock:
            boxes, _ = engine(np.array(small.convert("RGB")), use_det=True, use_cls=False, use_rec=False)
        boxes = boxes or []
        if len(boxes) < 5:
            return image
        vertical = 0
        for b in boxes:
            b = np.asarray(b, dtype=float)
            w, h = np.linalg.norm(b[1] - b[0]), np.linalg.norm(b[3] - b[0])
            vertical += h > 1.5 * w
        if vertical < 0.6 * len(boxes):
            return image
        ccw = _rec_score(engine, small.rotate(90, expand=True))
        cw = _rec_score(engine, small.rotate(-90, expand=True))
        return image.rotate(90 if ccw >= cw else -90, expand=True)
    except Exception:
        return image


def _group_into_lines(res) -> str:
    """Rebuild reading order: cluster boxes by vertical centre, sort each row left-to-right."""
    boxes = []
    for box, text, _score in res:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), text))
    if not boxes:
        return ""
    heights = sorted(b[2] for b in boxes)
    tol = max(4.0, heights[len(heights) // 2] * 0.5)
    boxes.sort(key=lambda b: b[0])
    rows: List[List[tuple]] = []
    for b in boxes:
        if rows and abs(rows[-1][-1][0] - b[0]) <= tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    return "\n".join("   ".join(t[3] for t in sorted(r, key=lambda t: t[1])) for r in rows)


def ocr_image(image: Image.Image, layout: str = "raw") -> str:
    """
    layout="raw"   -> one OCR box per line in detector order (what the no_ai parser expects)
    layout="lines" -> boxes regrouped into visual rows (better for LLMs reading OCR text)
    """
    image = _downscale(image, settings.max_image_side)
    engine = get_rapidocr()
    if engine:
        try:
            with _run_lock:
                res, _ = engine(np.array(image.convert("RGB")))
            if res:
                if layout == "lines":
                    return _group_into_lines(res).strip()
                return "\n".join(line[1] for line in res).strip()
        except Exception:
            pass

    try:
        import pytesseract
        for p in (settings.tesseract_path, r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
            if p and os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break
        pre = ImageEnhance.Contrast(image.convert("L")).enhance(2.0)
        return pytesseract.image_to_string(pre, config="--oem 3 --psm 6").strip()
    except Exception:
        return ""


def has_embedded_text(doc: DocumentContent) -> bool:
    return bool(doc.text and len(doc.text.strip()) > MIN_EMBEDDED_TEXT_CHARS)


def get_best_document_text(doc: DocumentContent, layout: str = "raw") -> str:
    """Embedded PDF text if present, else OCR of the page images."""
    if has_embedded_text(doc):
        return doc.text
    parts = [p for p in (ocr_image(img, layout=layout) for img in doc.images) if p]
    if parts:
        return "\n\n--- PAGE BREAK ---\n\n".join(parts).strip()
    return doc.text or ""


def ocr_available() -> Optional[str]:
    if get_rapidocr():
        return "rapidocr"
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return "tesseract"
    except Exception:
        return None
