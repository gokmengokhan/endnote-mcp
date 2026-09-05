"""Tests for FTS5-backed search engine."""

from endnote_mcp.search import (
    build_fts_query,
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

def test_search_references_has_doi(populated_db):
    results = search_references(populated_db, "social capital")
    matching = [r for r in results if r["rec_number"] == 1]
    assert len(matching) == 1
    assert matching[0]["doi"] == "10.1000/socrev.2018"


def test_search_fulltext_has_doi(populated_db):
    results = search_fulltext(populated_db, "habitus")
    matching = [r for r in results if r["rec_number"] == 1]
    assert len(matching) == 1
    assert matching[0]["doi"] == "10.1000/socrev.2018"


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


# --- FTS5 query sanitisation -------------------------------------------------


def test_build_fts_query_quotes_bare_terms():
    assert build_fts_query("social capital") == '"social" AND "capital"'


def test_build_fts_query_hyphenated_term():
    # Previously crashed with: no such column: Based
    assert build_fts_query("Assumption-Based Planning") == (
        '"Assumption-Based" AND "Planning"'
    )


def test_build_fts_query_colon_is_literal():
    assert build_fts_query("water:governance") == '"water:governance"'


def test_build_fts_query_keeps_phrases_and_operators():
    assert build_fts_query('"exact phrase" OR other') == '"exact phrase" OR "other"'


def test_build_fts_query_keeps_prefix_marker():
    assert build_fts_query("gov*") == '"gov"*'


def test_build_fts_query_keeps_balanced_groups():
    assert build_fts_query("(water OR zzz) AND planning") == (
        '("water" OR "zzz") AND "planning"'
    )


def test_build_fts_query_closes_open_paren():
    assert build_fts_query("(nested") == '("nested")'


def test_build_fts_query_drops_stray_close_paren():
    assert build_fts_query("a)) b") == '"a" AND "b"'


def test_build_fts_query_drops_empty_group():
    assert build_fts_query("water ()") == '"water"'


def test_build_fts_query_drops_dangling_operator():
    assert build_fts_query("foo AND") == '"foo"'


def test_build_fts_query_drops_leading_operator():
    assert build_fts_query("NOT covid") == '"covid"'


def test_build_fts_query_collapses_operator_run():
    # The last operator wins, so "AND NOT" still excludes the right operand.
    assert build_fts_query("a AND NOT b") == '"a" NOT "b"'


def test_build_fts_query_returns_empty_for_unsearchable_input():
    for query in ["", "   ", "---", "*", "()", "AND OR NOT"]:
        assert build_fts_query(query) == "", query


def test_build_fts_query_preserves_non_ascii():
    assert build_fts_query("Gökmen İstanbul") == '"Gökmen" AND "İstanbul"'


def test_search_references_hyphenated_query(populated_db):
    # Regression: hyphens used to reach FTS5 as syntax and raise OperationalError
    results = search_references(populated_db, "Assumption-Based Planning")
    assert isinstance(results, list)


def test_search_references_survives_fts_metacharacters(populated_db):
    for query in ["covid-19", "water:governance", "foo AND", "(nested", "a)) b", "*"]:
        assert isinstance(search_references(populated_db, query), list), query


def test_search_fulltext_survives_fts_metacharacters(populated_db):
    for query in ["covid-19", "grounded-theory", "habitus:", "AND", "((("]:
        assert isinstance(search_fulltext(populated_db, query), list), query


def test_list_by_topic_survives_fts_metacharacters(populated_db):
    for query in ["covid-19", "scenario:planning", "OR", ")("]:
        assert isinstance(list_by_topic(populated_db, query), list), query


def test_search_fulltext_finds_hyphenated_phrase(populated_db):
    # "grounded theory" appears in the indexed PDF text; the hyphenated form
    # becomes a phrase and still matches.
    results = search_fulltext(populated_db, "grounded-theory")
    assert len(results) >= 1


# --- notes / research notes indexing ----------------------------------------


def test_research_notes_are_searchable(populated_db):
    # Ref 1 carries "zxqmarker" only in research_notes.
    results = search_references(populated_db, "zxqmarker")
    assert [r["rec_number"] for r in results] == [1]


def test_notes_are_excluded_by_default(populated_db):
    # Ref 5's "zxqnoise" lives only in the imported notes field.
    assert search_references(populated_db, "zxqnoise") == []


def test_notes_are_searchable_when_enabled(populated_db):
    results = search_references(populated_db, "zxqnoise", search_notes=True)
    assert [r["rec_number"] for r in results] == [5]


def test_list_by_topic_excludes_notes_by_default(populated_db):
    assert list_by_topic(populated_db, "zxqnoise") == []
    assert len(list_by_topic(populated_db, "zxqnoise", search_notes=True)) == 1


def test_notes_scope_still_honours_filters(populated_db):
    # Column scoping wraps the whole expression, so the other filters still work.
    results = search_references(populated_db, "zxqmarker", year_from="2020")
    assert results == []
    results = search_references(populated_db, "zxqmarker", year_from="2015")
    assert [r["rec_number"] for r in results] == [1]


def test_notes_scope_survives_fts_metacharacters(populated_db):
    # The column filter is applied on top of the sanitised query, so malformed
    # input must still not reach FTS5 as syntax.
    for query in ["covid-19", "foo AND", "(nested", "a)) b", "water:governance"]:
        assert isinstance(search_references(populated_db, query), list), query
        assert isinstance(
            search_references(populated_db, query, search_notes=True), list
        ), query


def test_get_reference_details_returns_note_fields(populated_db):
    ref = get_reference_details(populated_db, 1)
    assert ref["research_notes"] == "zxqmarker my own reading of the field argument"
    assert "notes" in ref
