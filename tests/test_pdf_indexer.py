"""Tests for PDF file lookup."""

from pathlib import Path
from urllib.parse import quote

import pytest

from endnote_mcp.pdf_indexer import find_pdf, read_pages, _pdf_cache, _pdf_cache_dir


@pytest.fixture(autouse=True)
def _reset_pdf_cache():
    """Reset the global PDF cache between tests."""
    import endnote_mcp.pdf_indexer as mod
    mod._pdf_cache = {}
    mod._pdf_cache_dir = None
    yield
    mod._pdf_cache = {}
    mod._pdf_cache_dir = None


def test_find_pdf_direct(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    result = find_pdf(tmp_path, "test.pdf")
    assert result == pdf


def test_find_pdf_cache(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    pdf = subdir / "nested.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    # Not at direct path, should be found via cache
    result = find_pdf(tmp_path, "nested.pdf")
    assert result == pdf


def test_find_pdf_not_found(tmp_path):
    result = find_pdf(tmp_path, "nonexistent.pdf")
    assert result is None


def test_find_pdf_empty_filename(tmp_path):
    result = find_pdf(tmp_path, "")
    assert result is None


def test_find_pdf_url_decoded(tmp_path):
    # Create a file with spaces in the name
    pdf = tmp_path / "my paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    # Look up with URL-encoded name
    encoded_name = quote("my paper.pdf")
    result = find_pdf(tmp_path, encoded_name)
    assert result == pdf


def test_read_pages_not_found():
    with pytest.raises(FileNotFoundError):
        read_pages("/nonexistent/path/to.pdf", 1, 5)
