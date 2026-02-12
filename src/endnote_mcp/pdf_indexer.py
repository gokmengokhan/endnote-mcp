"""Extract text from PDFs using PyMuPDF (fitz)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


def extract_pages(pdf_path: str | Path) -> Generator[tuple[int, str], None, None]:
    """Yield (page_number, text) for each page in a PDF.

    Page numbers are 1-based to match human-readable page references.
    """
    pdf_path = Path(pdf_path)
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        logger.warning("Failed to open PDF %s: %s", pdf_path.name, e)
        return

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text("text")
            if text and text.strip():
                yield page_idx + 1, text.strip()
    finally:
        doc.close()


def read_pages(pdf_path: str | Path, start: int, end: int) -> list[dict]:
    """Read specific pages from a PDF.

    Args:
        pdf_path: Path to the PDF file.
        start: First page to read (1-based, inclusive).
        end: Last page to read (1-based, inclusive).

    Returns:
        List of dicts with 'page' and 'text' keys.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    results = []
    try:
        total = len(doc)
        start = max(1, start)
        end = min(total, end)
        for page_num in range(start, end + 1):
            page = doc[page_num - 1]
            text = page.get_text("text").strip()
            results.append({"page": page_num, "text": text, "total_pages": total})
    finally:
        doc.close()

    return results


def find_pdf(pdf_dir: Path, pdf_filename: str) -> Path | None:
    """Locate a PDF file in the pdf_dir, handling common path variations.

    EndNote stores PDFs in various subdirectory structures. This function
    searches recursively.
    """
    if not pdf_filename:
        return None

    # Direct path
    direct = pdf_dir / pdf_filename
    if direct.exists():
        return direct

    # Search recursively
    for path in pdf_dir.rglob(pdf_filename):
        return path

    # Try URL-decoded name
    from urllib.parse import unquote
    decoded = unquote(pdf_filename)
    if decoded != pdf_filename:
        for path in pdf_dir.rglob(decoded):
            return path

    return None
