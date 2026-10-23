import io
import logging
import re

from pypdf import PdfReader

logger = logging.getLogger(__name__)

_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
# Runs of 3+ spaces in layout text separate columns; keep that boundary visible
# (" | ") while dropping the padding, which roughly halves the token count.
_COLUMN_GAP = re.compile(r" {3,}")


def is_pdf_upload(filename: str | None, content_type: str | None, content: bytes) -> bool:
    """Whether an upload is a PDF.

    Browsers report an empty or generic type for some PDFs and file names may be
    upper-case (``QuoteA0492_23.Pdf``), so a PDF type *or* a ``.pdf`` name is
    enough — but the bytes must actually be a PDF.
    """
    media_type = (content_type or "").split(";")[0].strip().lower()
    declared = media_type in _PDF_CONTENT_TYPES or (filename or "").lower().endswith(".pdf")
    return declared and b"%PDF-" in content[:1024]


def _page_text(page) -> str:
    # Layout mode keeps printed labels next to their values ("EIN: | 94 1985704")
    # and table rows on one line; plain mode separates them on many quotes.
    try:
        text = page.extract_text(extraction_mode="layout") or ""
    except Exception:  # noqa: BLE001 — fall back rather than lose the page
        logger.warning("Layout text extraction failed; falling back to plain mode")
        text = page.extract_text() or ""
    lines = (_COLUMN_GAP.sub(" | ", line.strip()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def extract_text(pdf_bytes: bytes) -> str:
    """Extract the text from a vendor-offer PDF, page by page in reading layout.

    Covers text-based PDFs (scans need OCR, which is out of scope). Slightly
    damaged files (e.g. a broken cross-reference table) are still read.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n\n".join(_page_text(page) for page in reader.pages)
