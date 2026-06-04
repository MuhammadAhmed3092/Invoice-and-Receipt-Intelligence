"""
agents/document_processor.py — Converts any uploaded invoice/receipt into
page images (base64) + extracted text, ready for the vision model.

Reuses the same battle-tested approach from the doc intelligence project:
  1. PyMuPDF  → direct text extraction (fast, lossless for digital PDFs)
  2. pdf2image → render each page as a PIL Image at 150 DPI
  3. Resize   → cap at max_image_size to stay within Groq API limits
  4. pytesseract → OCR if page has no direct text (scanned/photo invoices)
  5. base64   → encode image for the vision model API call
"""

from __future__ import annotations
import base64
import io
from pathlib import Path
from dataclasses import dataclass, field
from loguru import logger
from PIL import Image
from config import settings


@dataclass
class PageResult:
    """Everything extracted from one page of the document."""
    page_number: int
    image_b64:   str   = ""     # JPEG base64 for vision model
    direct_text: str   = ""     # from PyMuPDF (digital PDF)
    ocr_text:    str   = ""     # from pytesseract (scanned)
    text:        str   = ""     # best available text
    is_scanned:  bool  = False


@dataclass
class DocumentResult:
    """All pages extracted from one invoice file."""
    filename:  str
    file_path: str
    pages:     list[PageResult] = field(default_factory=list)
    full_text: str = ""
    used_ocr:  bool = False
    error:     str = ""

    @property
    def first_page_b64(self) -> str:
        """Most invoices are 1 page — quick access to the first page image."""
        return self.pages[0].image_b64 if self.pages else ""

    @property
    def all_text(self) -> str:
        """Full text across all pages, deduplicated."""
        return self.full_text


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resize_and_encode(img: Image.Image) -> str:
    """Resize to max_image_size and return base64 JPEG string."""
    img = img.convert("RGB")
    w, h = img.size
    max_s = settings.max_image_size
    if max(w, h) > max_s:
        scale = max_s / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _run_ocr(img: Image.Image) -> str:
    if not settings.ocr_enabled:
        return ""
    try:
        import pytesseract
        return pytesseract.image_to_string(img).strip()
    except Exception as e:
        logger.debug(f"[OCR] Unavailable: {e}")
        return ""


# ── PDF processor ─────────────────────────────────────────────────────────────

def _process_pdf(path: Path) -> DocumentResult:
    import fitz
    result = DocumentResult(filename=path.name, file_path=str(path))

    pdf     = fitz.open(str(path))
    n_pages = len(pdf)
    logger.info(f"[Processor] PDF: {path.name} — {n_pages} page(s)")

    # Render all pages to images
    try:
        from pdf2image import convert_from_path
        pil_pages = convert_from_path(str(path), dpi=settings.page_image_dpi)
    except Exception as e:
        logger.warning(f"[Processor] pdf2image failed ({e}), falling back to PyMuPDF renderer")
        pil_pages = []
        for i in range(n_pages):
            pix = pdf[i].get_pixmap(dpi=settings.page_image_dpi)
            pil_pages.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))

    all_text  = []
    used_ocr  = False

    for i in range(n_pages):
        page        = pdf[i]
        direct_text = page.get_text("text").strip()
        is_scanned  = len(direct_text) < 30
        pil_img     = pil_pages[i] if i < len(pil_pages) else None

        ocr_text = ""
        if is_scanned and pil_img:
            ocr_text = _run_ocr(pil_img)
            if ocr_text:
                used_ocr = True

        best_text = direct_text if len(direct_text) >= 30 else ocr_text
        img_b64   = _resize_and_encode(pil_img) if pil_img else ""
        all_text.append(best_text)

        result.pages.append(PageResult(
            page_number = i + 1,
            image_b64   = img_b64,
            direct_text = direct_text,
            ocr_text    = ocr_text,
            text        = best_text,
            is_scanned  = is_scanned,
        ))
        logger.debug(f"[Processor] Page {i+1}: {len(best_text)} chars, scanned={is_scanned}")

    pdf.close()
    result.full_text = "\n\n".join(all_text)
    result.used_ocr  = used_ocr
    return result


# ── Image processor (JPG / PNG / TIFF) ───────────────────────────────────────

def _process_image(path: Path) -> DocumentResult:
    result  = DocumentResult(filename=path.name, file_path=str(path))
    img     = Image.open(path)
    ocr_txt = _run_ocr(img)
    b64     = _resize_and_encode(img)

    result.pages.append(PageResult(
        page_number = 1,
        image_b64   = b64,
        ocr_text    = ocr_txt,
        text        = ocr_txt,
        is_scanned  = True,
    ))
    result.full_text = ocr_txt
    result.used_ocr  = bool(ocr_txt)
    logger.info(f"[Processor] Image: {path.name}, OCR chars={len(ocr_txt)}")
    return result


# ── Main entry point ──────────────────────────────────────────────────────────

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

def process_document(file_path: str | Path) -> DocumentResult:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported type: {ext}. Supported: {SUPPORTED}")
    return _process_pdf(path) if ext == ".pdf" else _process_image(path)
