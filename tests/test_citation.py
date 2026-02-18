"""Tests for citation formatting (APA7, Harvard, Vancouver, Chicago, IEEE, BibTeX)."""

import json

import pytest

from endnote_mcp.citation import (
    format_citation,
    format_bibtex,
    _invert_author,
    _direct_order,
    _is_article,
    _vancouver_author_name,
    _apa_authors,
    _bibtex_entry_type,
    _bibtex_cite_key,
)


# ---- format_citation: APA 7th ----

def test_apa7_journal_article(sample_ref):
    cite = format_citation(sample_ref, "apa7")
    # Already-inverted names (with comma) are preserved as-is
    assert "Smith, John A." in cite
    assert "Jones, Mary B." in cite
    assert "(2020)" in cite
    assert "Schedule Unreliability" in cite
    assert "*Maritime Economics & Logistics*" in cite
    assert "https://doi.org/10.1234/example.doi" in cite


def test_apa7_book(sample_book_ref):
    cite = format_citation(sample_book_ref, "apa7")
    assert "Stacey, Ralph D." in cite
    assert "(2011)" in cite
    assert "*Strategic Management" in cite
    assert "Financial Times Prentice Hall" in cite


def test_apa7_no_authors(sample_ref):
    sample_ref["authors"] = []
    cite = format_citation(sample_ref, "apa7")
    # Title moves to author position when no authors
    assert "Schedule Unreliability" in cite
    assert "(2020)" in cite


# ---- format_citation: Harvard ----

def test_harvard_journal(sample_ref):
    cite = format_citation(sample_ref, "harvard")
    assert "Smith, John A." in cite
    assert "(2020)" in cite
    assert "'" in cite  # single quotes around title
    assert "vol. 15" in cite
    assert "no. 3" in cite
    assert "pp. 123-145" in cite


# ---- format_citation: Vancouver ----

def test_vancouver_journal(sample_ref):
    cite = format_citation(sample_ref, "vancouver")
    assert "Smith JA" in cite
    assert "Jones MB" in cite
    assert ";15(3):123-145" in cite


# ---- format_citation: Chicago ----

def test_chicago_journal(sample_ref):
    cite = format_citation(sample_ref, "chicago")
    assert "Smith, John A." in cite
    assert "2020." in cite
    # Title in double quotes
    assert '"Schedule Unreliability' in cite


# ---- format_citation: IEEE ----

def test_ieee_journal(sample_ref):
    cite = format_citation(sample_ref, "ieee")
    assert "J. A. Smith" in cite
    assert "M. B. Jones" in cite
    assert "vol. 15" in cite
    assert "no. 3" in cite
    assert "doi: 10.1234/example.doi" in cite


# ---- format_citation: Edge cases ----

def test_unknown_style_raises(sample_ref):
    with pytest.raises(ValueError, match="Unknown style"):
        format_citation(sample_ref, "mla")


def test_authors_as_json_string(sample_ref):
    sample_ref["authors"] = json.dumps(["Smith, John A.", "Jones, Mary B."])
    cite = format_citation(sample_ref, "apa7")
    assert "Smith, John A." in cite


def test_doi_already_url(sample_ref):
    sample_ref["doi"] = "https://doi.org/10.1234/example.doi"
    cite = format_citation(sample_ref, "apa7")
    # Should not double-prefix
    assert "https://doi.org/https://doi.org/" not in cite
    assert "https://doi.org/10.1234/example.doi" in cite


# ---- format_bibtex ----

def test_bibtex_article(sample_ref):
    bib = format_bibtex(sample_ref)
    assert bib.startswith("@article{")
    assert "journal = {Maritime Economics & Logistics}" in bib
    assert "pages = {123--145}" in bib
    assert "year = {2020}" in bib


def test_bibtex_book(sample_book_ref):
    bib = format_bibtex(sample_book_ref)
    assert bib.startswith("@book{")
    assert "publisher = {Financial Times Prentice Hall}" in bib
    assert "address = {Harlow}" in bib
    assert "isbn = {978-0273725596}" in bib


def test_bibtex_cite_key_format():
    key = _bibtex_cite_key(["Smith, John A."], "2020", 42)
    assert key == "smith2020r42"


def test_bibtex_cite_key_no_authors():
    key = _bibtex_cite_key([], "2020", 42)
    assert key == "unknown2020r42"


def test_bibtex_doi_cleaned(sample_ref):
    sample_ref["doi"] = "https://doi.org/10.1234/example.doi"
    bib = format_bibtex(sample_ref)
    assert "doi = {10.1234/example.doi}" in bib


def test_bibtex_keywords(sample_ref):
    bib = format_bibtex(sample_ref)
    assert "keywords = {shipping, supply chain, reliability}" in bib


def test_bibtex_title_braces(sample_ref):
    bib = format_bibtex(sample_ref)
    # Title should be wrapped in double braces for case preservation
    assert "title = {{Schedule Unreliability in Liner Shipping}}" in bib


# ---- _bibtex_entry_type ----

def test_bibtex_entry_type_article():
    assert _bibtex_entry_type("Journal Article") == "article"


def test_bibtex_entry_type_book():
    assert _bibtex_entry_type("Book") == "book"


def test_bibtex_entry_type_book_section():
    assert _bibtex_entry_type("Book Section") == "incollection"


def test_bibtex_entry_type_conference():
    assert _bibtex_entry_type("Conference Proceedings") == "inproceedings"


def test_bibtex_entry_type_thesis():
    assert _bibtex_entry_type("Thesis") == "phdthesis"


def test_bibtex_entry_type_report():
    assert _bibtex_entry_type("Report") == "techreport"


def test_bibtex_entry_type_patent():
    assert _bibtex_entry_type("Patent") == "misc"


def test_bibtex_entry_type_web():
    assert _bibtex_entry_type("Web Page") == "misc"


# ---- Helpers ----

def test_invert_author():
    assert _invert_author("John Smith") == "Smith, J."


def test_invert_author_middle():
    assert _invert_author("John A. Smith") == "Smith, J. A."


def test_invert_author_already_inverted():
    assert _invert_author("Smith, J. A.") == "Smith, J. A."


def test_direct_order():
    assert _direct_order("Smith, John") == "John Smith"


def test_direct_order_no_comma():
    assert _direct_order("John Smith") == "John Smith"


def test_is_article_true():
    assert _is_article("Journal Article") is True
    assert _is_article("Magazine Article") is True


def test_is_article_false():
    assert _is_article("Book") is False
    assert _is_article("Thesis") is False


def test_vancouver_author_name():
    assert _vancouver_author_name("Smith, John A.") == "Smith JA"


def test_vancouver_author_name_no_comma():
    assert _vancouver_author_name("Smith") == "Smith"


def test_apa_authors_single():
    result = _apa_authors(["Smith, J."])
    assert result == "Smith, J."


def test_apa_authors_two():
    result = _apa_authors(["Smith, J.", "Jones, M."])
    assert result == "Smith, J. & Jones, M."


def test_apa_authors_three():
    result = _apa_authors(["Smith, J.", "Jones, M.", "Brown, A."])
    assert result == "Smith, J., Jones, M., & Brown, A."


def test_apa_authors_21():
    authors = [f"Author{i}, X." for i in range(21)]
    result = _apa_authors(authors)
    assert "..." in result
    assert "Author0, X." in result
    assert "Author20, X." in result
