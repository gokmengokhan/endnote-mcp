"""Tests for EndNote XML parser."""

import json

from endnote_mcp.endnote_parser import parse_endnote_xml


def test_parse_count(sample_xml):
    records = list(parse_endnote_xml(sample_xml))
    assert len(records) == 3


def test_parse_journal_article_fields(sample_xml):
    records = list(parse_endnote_xml(sample_xml))
    rec = records[0]
    assert rec["rec_number"] == 1
    assert rec["ref_type"] == "Journal Article"
    assert rec["title"] == "Test Article Title"
    assert rec["journal"] == "Test Journal"
    assert rec["year"] == "2020"
    assert rec["volume"] == "15"
    assert rec["issue"] == "3"
    assert rec["pages"] == "100-120"
    assert rec["abstract"] == "This is a test abstract."
    assert rec["doi"] == "10.1234/test"
    assert rec["url"] == "https://example.com"
    assert rec["publisher"] == "Test Publisher"
    assert rec["place_published"] == "London"


def test_parse_authors_json(sample_xml):
    records = list(parse_endnote_xml(sample_xml))
    authors = json.loads(records[0]["authors"])
    assert authors == ["Smith, John A.", "Jones, Mary B."]


def test_parse_keywords_json(sample_xml):
    records = list(parse_endnote_xml(sample_xml))
    keywords = json.loads(records[0]["keywords"])
    assert keywords == ["testing", "automation"]


def test_parse_pdf_filename(sample_xml):
    records = list(parse_endnote_xml(sample_xml))
    # Record 1: simple internal-pdf://smith2020.pdf
    assert records[0]["pdf_path"] == "smith2020.pdf"
    # Record 2: no PDF URL
    assert records[1]["pdf_path"] == ""
    # Record 3: internal-pdf://0123456789/davis2021.pdf (subdirectory)
    assert records[2]["pdf_path"] == "davis2021.pdf"


def test_parse_book_fields(sample_xml):
    records = list(parse_endnote_xml(sample_xml))
    rec = records[1]
    assert rec["ref_type"] == "Book"
    assert rec["title"] == "A Book About Testing"
    assert rec["publisher"] == "Academic Press"
    assert rec["place_published"] == "New York"
    assert rec["isbn"] == "978-1234567890"
