from pathlib import Path

from PIL import Image, ImageOps

from config.settings import settings
from pipeline.models import DocumentContent

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
SUPPORTED_SUFFIXES = (".pdf",) + IMAGE_SUFFIXES
MAX_FILE_BYTES = 25 * 1024 * 1024


def _unreadable(file_path: Path, file_type: str, error: str) -> DocumentContent:
    return DocumentContent(file_path=file_path, file_type=file_type, is_readable=False, error=error)


def load_document(file_path: Path) -> DocumentContent:
    """Load a PDF or image. Never raises: unreadable inputs come back with is_readable=False."""
    file_path = Path(file_path)
    if not file_path.exists():
        return _unreadable(file_path, "unknown", f"File not found: {file_path.name}")
    size = file_path.stat().st_size
    if size == 0:
        return _unreadable(file_path, "unknown", "File is empty (0 bytes).")
    if size > MAX_FILE_BYTES:
        return _unreadable(file_path, "unknown", f"File too large ({size / 1e6:.1f} MB > 25 MB).")

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(file_path)
    if suffix in IMAGE_SUFFIXES:
        return _load_image(file_path)
    return _unreadable(file_path, suffix, f"Unsupported file format: {suffix or '(none)'}")


def _load_pdf(file_path: Path) -> DocumentContent:
    try:
        import fitz  # PyMuPDF

        data = file_path.read_bytes()
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                return _unreadable(file_path, "pdf", "PDF is password protected.")
            if doc.page_count == 0:
                return _unreadable(file_path, "pdf", "PDF has 0 pages (corrupt or truncated).")
            pages_text = [page.get_text() for page in doc]
            page_count = doc.page_count
        return DocumentContent(
            file_path=file_path,
            file_type="pdf",
            text="\n\n--- PAGE BREAK ---\n\n".join(pages_text).strip(),
            page_count=page_count,
            pdf_bytes=data,
            dpi=settings.render_dpi,
            max_pages=settings.max_pages,
        )
    except Exception as e:
        return _unreadable(file_path, "pdf", f"Corrupt or unreadable PDF: {type(e).__name__}")


def _load_image(file_path: Path) -> DocumentContent:
    try:
        img = Image.open(file_path)
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")  # respect phone rotation
        if min(img.size) < 50:
            return _unreadable(file_path, "image", f"Image too small to read ({img.size[0]}x{img.size[1]}).")
        return DocumentContent(file_path=file_path, file_type="image", text="", page_count=1, image=img)
    except Exception as e:
        return _unreadable(file_path, "image", f"Corrupt or unreadable image: {type(e).__name__}")
