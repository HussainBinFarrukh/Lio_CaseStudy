"""PDF acceptance and text extraction on the customer's five reference quotes."""
from pathlib import Path

import pytest

from app.services.pdf import extract_text, is_pdf_upload

QUOTES_DIR = Path(__file__).resolve().parents[3] / "quotes"
REFERENCE_QUOTES = [
    "QT-4120-Cust-14918.pdf",
    "QT-OF2312380-Cust-57692.pdf",
    "QuoteA0492_23.Pdf",
    "Quote_1__Lio_Technologies_Inc__1x_MBA___2214703918.pdf",
    "Quote_Hartwell_Cleveland_ACME_Grinding_Machine.pdf",
]

needs_quotes = pytest.mark.skipif(
    not QUOTES_DIR.is_dir(), reason="reference quotes not available (e.g. inside the image)"
)


@pytest.mark.parametrize(
    "filename, content_type",
    [
        ("offer.pdf", "application/pdf"),
        ("QuoteA0492_23.Pdf", ""),
        ("QuoteA0492_23.Pdf", "application/octet-stream"),
        ("offer", "application/x-pdf"),
        ("offer.PDF", None),
    ],
)
def test_pdf_accepted_by_type_or_name(filename, content_type):
    assert is_pdf_upload(filename, content_type, b"%PDF-1.7\n...")


@pytest.mark.parametrize(
    "filename, content_type, content",
    [
        ("notes.pdf", "application/pdf", b"hello"),  # claims PDF, isn't one
        ("notes.txt", "text/plain", b"%PDF-1.7"),  # neither type nor name says PDF
        ("offer", "application/octet-stream", b"%PDF-1.7"),
    ],
)
def test_non_pdfs_rejected(filename, content_type, content):
    assert not is_pdf_upload(filename, content_type, content)


@needs_quotes
@pytest.mark.parametrize("filename", REFERENCE_QUOTES)
def test_reference_quotes_parse(filename):
    content = (QUOTES_DIR / filename).read_bytes()
    assert is_pdf_upload(filename, "", content)
    text = extract_text(content)  # includes Hollis with its broken xref table
    assert len(text) > 500


@needs_quotes
@pytest.mark.parametrize(
    "filename, expected",
    [
        # Labels stay next to their values (they are separated in plain mode).
        ("QuoteA0492_23.Pdf", "EIN: | 94 1985704"),
        ("QuoteA0492_23.Pdf", "Grand total | $2,042.15"),
        ("Quote_1__Lio_Technologies_Inc__1x_MBA___2214703918.pdf", "Total (USD) | $1,534.59"),
        # Table rows stay on one line, including the "U.P." marker of an alternative.
        ("QuoteA0492_23.Pdf", "$2,090.00 | U.P."),
        ("QT-4120-Cust-14918.pdf", "894.08 | -20.00% | 715.26"),
    ],
)
def test_layout_text_keeps_labels_with_values(filename, expected):
    assert expected in extract_text((QUOTES_DIR / filename).read_bytes())
