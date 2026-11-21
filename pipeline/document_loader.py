import io
from pathlib import Path
from typing import List
from PIL import Image
from pipeline.models import DocumentContent

def load_document(file_path: Path) -> DocumentContent:
    """Load a PDF or image document, extracting direct text and page renderings."""
    if not file_path.exists():
        return DocumentContent(
            file_path=file_path,
            file_type="unknown",
            text="",
            images=[],
            page_count=0,
            is_readable=False,
            error=f"File not found: {file_path}"
        )

    if file_path.stat().st_size == 0:
        return DocumentContent(
            file_path=file_path,
            file_type="unknown",
            text="",
            images=[],
            page_count=0,
            is_readable=False,
            error="File is empty (0 bytes)."
        )

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _load_pdf(file_path)
    elif suffix in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"):
        return _load_image(file_path)
    else:
        return DocumentContent(
            file_path=file_path,
            file_type=suffix,
            text="",
            images=[],
            page_count=0,
            is_readable=False,
            error=f"Unsupported file format: {suffix}"
        )

def _load_pdf(file_path: Path) -> DocumentContent:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(file_path))
        if doc.page_count == 0:
            return DocumentContent(
                file_path=file_path,
                file_type="pdf",
                text="",
                images=[],
                page_count=0,
                is_readable=False,
                error="PDF has 0 pages."
            )

        pages_text: List[str] = []
        pages_images: List[Image.Image] = []

        for page in doc:
            # 1. Direct text extraction
            text = page.get_text()
            pages_text.append(text)

            # 2. Render page pixmap at ~150 DPI for OCR/Vision
            zoom = 150.0 / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            pages_images.append(img)

        doc.close()
        combined_text = "\n\n--- PAGE BREAK ---\n\n".join(pages_text).strip()

        return DocumentContent(
            file_path=file_path,
            file_type="pdf",
            text=combined_text,
            images=pages_images,
            page_count=len(pages_images),
            is_readable=True,
            error=None
        )
    except Exception as e:
        return DocumentContent(
            file_path=file_path,
            file_type="pdf",
            text="",
            images=[],
            page_count=0,
            is_readable=False,
            error=f"Corrupt or unreadable PDF: {str(e)}"
        )

def _load_image(file_path: Path) -> DocumentContent:
    try:
        img = Image.open(file_path)
        img.load()  # Verify image integrity
        return DocumentContent(
            file_path=file_path,
            file_type="image",
            text="",  # Images have no direct digital text; OCR/Vision will extract
            images=[img],
            page_count=1,
            is_readable=True,
            error=None
        )
    except Exception as e:
        return DocumentContent(
            file_path=file_path,
            file_type="image",
            text="",
            images=[],
            page_count=0,
            is_readable=False,
            error=f"Corrupt or unreadable image: {str(e)}"
        )
