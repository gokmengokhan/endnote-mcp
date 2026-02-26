"""Extract text from PDFs using PyMuPDF (fitz)."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Generator
from urllib.parse import unquote

import fitz  # PyMuPDF


@contextlib.contextmanager
def _suppress_stderr():
    """Suppress stderr to silence harmless MuPDF warnings."""
    stderr_fd = sys.stderr.fileno()
    old_fd = os.dup(stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, stderr_fd)
        yield
    finally:
        os.dup2(old_fd, stderr_fd)
        os.close(old_fd)
        os.close(devnull)


class _PdfTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _PdfTimeout("PDF extraction timed out")

logger = logging.getLogger(__name__)

# Cached filename → path mapping (built once per pdf_dir)
_pdf_cache: dict[str, Path] = {}
_pdf_cache_dir: Path | None = None


def _build_pdf_cache(pdf_dir: Path) -> None:
    """Scan pdf_dir once and cache all PDF paths by filename."""
    global _pdf_cache, _pdf_cache_dir
    if _pdf_cache_dir == pdf_dir and _pdf_cache:
        return
    logger.info("Building PDF file cache for %s...", pdf_dir)
    _pdf_cache = {}
    for path in pdf_dir.rglob("*.[pP][dD][fF]"):
        _pdf_cache[path.name] = path
        # Also index URL-decoded name
        decoded = unquote(path.name)
        if decoded != path.name:
            _pdf_cache[decoded] = path
    _pdf_cache_dir = pdf_dir
    logger.info("Cached %d PDF files.", len(_pdf_cache))


def extract_pages(pdf_path: str | Path, timeout: int = 30) -> list[tuple[int, str]]:
    """Extract (page_number, text) for each page in a PDF.

    Page numbers are 1-based to match human-readable page references.
    Returns a list instead of generator so the timeout covers the full extraction.
    Skips PDFs that take longer than `timeout` seconds.
    """
    pdf_path = Path(pdf_path)

    # Set alarm-based timeout (Unix only, ignored on Windows)
    old_handler = None
    try:
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)
    except (OSError, AttributeError):
        pass  # Windows or signal not available

    try:
        with _suppress_stderr():
            doc = fitz.open(str(pdf_path))
    except _PdfTimeout:
        logger.warning("Timeout opening PDF %s", pdf_path.name)
        return []
    except Exception as e:
        logger.warning("Failed to open PDF %s: %s", pdf_path.name, e)
        return []

    results = []
    try:
        with _suppress_stderr():
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                text = page.get_text("text")
                if text and text.strip():
                    results.append((page_idx + 1, text.strip()))
    except _PdfTimeout:
        logger.warning("Timeout extracting PDF %s (got %d pages before timeout)", pdf_path.name, len(results))
    finally:
        doc.close()
        # Cancel alarm and restore handler
        try:
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
        except (OSError, AttributeError):
            pass

    return results


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

    with _suppress_stderr():
        doc = fitz.open(str(pdf_path))
    results = []
    try:
        total = len(doc)
        start = max(1, start)
        end = min(total, end)
        with _suppress_stderr():
            for page_num in range(start, end + 1):
                page = doc[page_num - 1]
                text = page.get_text("text").strip()
                results.append({"page": page_num, "text": text, "total_pages": total})
    finally:
        doc.close()

    return results


def find_pdf(pdf_dir: Path, pdf_filename: str) -> Path | None:
    """Locate a PDF file in the pdf_dir using a cached lookup.

    On first call, scans the entire pdf_dir once and caches all PDF paths.
    Subsequent lookups are O(1) dict lookups instead of recursive searches.
    """
    if not pdf_filename:
        return None

    # Direct path (fastest)
    direct = pdf_dir / pdf_filename
    if direct.exists():
        return direct

    # Build cache on first use
    _build_pdf_cache(pdf_dir)

    # Lookup by filename
    result = _pdf_cache.get(pdf_filename)
    if result:
        return result

    # Try URL-decoded name
    decoded = unquote(pdf_filename)
    if decoded != pdf_filename:
        result = _pdf_cache.get(decoded)
        if result:
            return result

    return None
