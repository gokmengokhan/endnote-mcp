"""Tests for FTS5-backed search engine."""

from endnote_mcp.search import (
    search_references,
    search_fulltext,
    list_by_topic,
    get_reference_details,
    get_references_batch,
    _find_related_fts,
    _parse_authors_short,
)


def test_search_references_basic(populated_db):
    results = search_references(populated_db, "social capital")
    assert len(results) >= 1
    titles = [r["title"] for r in results]
    assert any("Social Capital" in t for t in titles)


def test_search_references_empty_query(populated_db):
    results = search_references(populated_db, "")
    assert results == []


def test_search_references_empty_whitespace(populated_db):
    results = search_references(populated_db, "   ")
    assert results == []


def test_search_references_year_filter(populated_db):
    results = search_references(populated_db, "supply chain", year_from="2021")
    # Should find the 2022 paper but not the 2020 one (if it matched)
    for r in results:
        assert int(r["year"]) >= 2021


def test_search_references_year_to_filter(populated_db):
    results = search_references(populated_db, "planning", year_to="2019")
    for r in results:
        assert int(r["year"]) <= 2019


def test_search_references_author_filter(populated_db):
    results = search_references(populated_db, "capital", author="Bourdieu")
    assert len(results) >= 1
    for r in results:
        assert "Bourdieu" in r["authors"]


def test_search_references_ref_type_filter(populated_db):
    results = search_references(populated_db, "management", ref_type="Book")
    assert len(results) >= 1
    # The Book result should be included
    assert any("Strategic Management" in r["title"] for r in results)


def test_search_fulltext(populated_db):
    results = search_fulltext(populated_db, "habitus")
    assert len(results) >= 1
    # Should find rec_number 1 (Bourdieu paper has "habitus" on page 2)
    assert any(r["rec_number"] == 1 for r in results)
    # Should have snippets
    for r in results:
        assert len(r["snippets"]) > 0


def test_search_fulltext_grouped(populated_db):
    results = search_fulltext(populated_db, "grounded theory")
    # rec_number 2 has "grounded theory" on both pages
    matching = [r for r in results if r["rec_number"] == 2]
    assert len(matching) == 1  # grouped into one entry
    assert len(matching[0]["snippets"]) >= 1


def test_list_by_topic(populated_db):
    results = list_by_topic(populated_db, "uncertainty")
    assert len(results) >= 1
    titles = [r["title"] for r in results]
    assert any("Scenario Planning" in t or "uncertainty" in t.lower() for t in titles)


def test_get_reference_details(populated_db):
    ref = get_reference_details(populated_db, 1)
    assert ref is not None
    assert ref["title"] == "Social Capital and Community Development"
    assert isinstance(ref["authors"], list)
    assert ref["authors"] == ["Bourdieu, Pierre"]
    assert isinstance(ref["keywords"], list)
    assert "social capital" in ref["keywords"]
    assert ref["indexed_pdf_pages"] == 2


def test_get_reference_details_not_found(populated_db):
    ref = get_reference_details(populated_db, 9999)
    assert ref is None


def test_get_references_batch(populated_db):
    refs = get_references_batch(populated_db, [1, 3, 5])
    assert len(refs) == 3
    # Should be in the order requested
    assert refs[0]["rec_number"] == 1
    assert refs[1]["rec_number"] == 3
    assert refs[2]["rec_number"] == 5


def test_get_references_batch_empty(populated_db):
    refs = get_references_batch(populated_db, [])
    assert refs == []


def test_get_references_batch_missing(populated_db):
    refs = get_references_batch(populated_db, [1, 9999])
    assert len(refs) == 1
    assert refs[0]["rec_number"] == 1


def test_find_related_fts(populated_db):
    results = _find_related_fts(populated_db, 1, limit=5)
    # Should return related refs but NOT the target itself
    rec_numbers = [r["rec_number"] for r in results]
    assert 1 not in rec_numbers
    # Should find at least one related ref (e.g. ref 5 shares "supply chain")
    assert len(results) > 0


# ---- Helpers ----

def test_parse_authors_short_single():
    assert _parse_authors_short('["Smith, J."]') == "Smith, J."


def test_parse_authors_short_two():
    result = _parse_authors_short('["Smith, J.", "Jones, M."]')
    assert "Smith, J." in result
    assert "Jones, M." in result


def test_parse_authors_short_many():
    result = _parse_authors_short('["A", "B", "C", "D"]')
    assert "et al." in result


def test_parse_authors_short_empty():
    assert _parse_authors_short("[]") == "Unknown"


def test_parse_authors_short_none():
    assert _parse_authors_short("") == "Unknown"
