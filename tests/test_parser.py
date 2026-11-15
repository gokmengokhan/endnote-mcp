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


def test_parse_research_notes(sample_xml):
    refs = {r["rec_number"]: r for r in parse_endnote_xml(sample_xml)}
    assert refs[2]["research_notes"] == "My own take on this book."
    assert refs[2]["notes"] == "Email Address: x@example.com"


def test_research_notes_absent_is_empty_string(sample_xml):
    refs = {r["rec_number"]: r for r in parse_endnote_xml(sample_xml)}
    assert refs[1]["research_notes"] == ""


def test_parse_xml_string():
    """Records read back from EndNote arrive as a string, not a file."""
    from endnote_mcp.endnote_parser import parse_endnote_xml_string

    text = (
        '<?xml version="1.0" encoding="UTF-8" ?><xml><records>'
        '<record><database name="L.enl" path="/L.enl">L.enl</database><rec-number>7</rec-number>'
        '<ref-type name="Report">27</ref-type><contributors><authors><author>'
        '<style face="normal">Scottish Government,</style></author></authors></contributors>'
        '<titles><title>Scotland’s Blue Economy</title></titles>'
        '<urls><pdf-urls><url>internal-pdf://1234567890/r.pdf</url></pdf-urls></urls></record>'
        "<record><titles><title>no record number</title></titles></record>"
        "</records></xml>"
    )
    refs = parse_endnote_xml_string(text)
    assert len(refs) == 1
    ref = refs[0]
    assert ref["rec_number"] == 7 and ref["ref_type"] == "Report"
    assert ref["title"] == "Scotland’s Blue Economy"
    assert json.loads(ref["authors"]) == ["Scottish Government,"]
    assert ref["pdf_path"] == "r.pdf"


def test_access_dates():
    """A Web Page keeps its Access Date in EndNote's Number field and its Access Year in Volume."""
    from endnote_mcp.endnote_parser import parse_endnote_xml_string

    refs = {r["rec_number"]: r for r in parse_endnote_xml_string(
        "<xml><records>"
        '<record><rec-number>1</rec-number><ref-type name="Web Page">12</ref-type>'
        "<volume>2016</volume><number>29.03.2016</number></record>"
        '<record><rec-number>2</rec-number><ref-type name="Report">27</ref-type>'
        "<number>WP-7</number><access-date>11 November 2026</access-date></record>"
        '<record><rec-number>3</rec-number><ref-type name="Journal Article">17</ref-type>'
        "<volume>12</volume><number>3</number></record>"
        "</records></xml>"
    )}
    assert (refs[1]["access_date"], refs[1]["volume"], refs[1]["issue"]) == ("29.03.2016", "", "")
    assert (refs[2]["access_date"], refs[2]["issue"]) == ("11 November 2026", "WP-7")
    assert (refs[3]["access_date"], refs[3]["volume"], refs[3]["issue"]) == ("", "12", "3")
