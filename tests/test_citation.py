"""Tests for citation formatting (APA7, Harvard, Vancouver, Chicago, IEEE, BibTeX)."""

import json

import pytest

from endnote_mcp.citation import (
    format_citation,
    format_bibtex,
    _invert_author,
    _direct_order,
    _direct_order_initials,
    _is_article,
    _vancouver_author_name,
    _apa_authors,
    _bibtex_entry_type,
    _bibtex_cite_key,
)


# ---- format_citation: APA 7th ----

def test_apa7_journal_article(sample_ref):
    cite = format_citation(sample_ref, "apa7")
    # EndNote's "Surname, Given names" are reduced to initials
    assert cite.startswith("Smith, J. A., & Jones, M. B. (2020).")
    assert "Schedule Unreliability" in cite
    assert "*Maritime Economics & Logistics*" in cite
    assert "https://doi.org/10.1234/example.doi" in cite


def test_apa7_book(sample_book_ref):
    cite = format_citation(sample_book_ref, "apa7")
    assert cite.startswith("Stacey, R. D. (2011).")
    assert "*Strategic Management" in cite
    assert "Financial Times Prentice Hall" in cite


def test_apa7_no_authors(sample_ref):
    sample_ref["authors"] = []
    cite = format_citation(sample_ref, "apa7")
    # Title moves to author position when no authors
    assert "Schedule Unreliability" in cite
    assert "(2020)" in cite


def test_apa7_group_author(sample_ref):
    sample_ref["authors"] = ["World Health Organization,"]
    cite = format_citation(sample_ref, "apa7")
    assert cite.startswith("World Health Organization. (2020).")


def test_apa7_page_range_en_dash(sample_ref):
    assert "123–145" in format_citation(sample_ref, "apa7")


# ---- format_citation: Harvard ----

def test_harvard_journal(sample_ref):
    cite = format_citation(sample_ref, "harvard")
    assert cite.startswith("Smith, J. A. and Jones, M. B. (2020)")
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


# ---- format_citation: chapters and conference papers ----

@pytest.fixture
def chapter_ref(sample_ref):
    """A book section: EndNote stores the book's title where a journal's would go."""
    return {
        **sample_ref, "ref_type": "Book Section", "journal": "Handbook of Forecasting",
        "volume": "", "issue": "", "pages": "303-362", "doi": "",
        "publisher": "Springer", "place_published": "Boston",
    }


@pytest.fixture
def presentation_ref(sample_ref):
    """A paper given at a conference and not published in proceedings."""
    return {
        **sample_ref, "ref_type": "Conference Paper", "journal": "EURAM 2021",
        "volume": "", "issue": "", "pages": "", "doi": "",
        "publisher": "", "place_published": "Online",
    }


@pytest.mark.parametrize("style, expected", [
    ("apa7", "Shipping. In *Handbook of Forecasting* (pp. 303–362). Springer."),
    ("harvard", "'Schedule Unreliability in Liner Shipping', in *Handbook of Forecasting*. Boston: Springer, pp. 303-362."),
    ("vancouver", "Shipping. In: Handbook of Forecasting. Boston: Springer; 2020. p. 303-362."),
    ("chicago", '"Schedule Unreliability in Liner Shipping." In *Handbook of Forecasting*, 303–362. Boston: Springer.'),
    ("ieee", '"Schedule Unreliability in Liner Shipping," in *Handbook of Forecasting*. Boston: Springer, 2020, pp. 303–362.'),
])
def test_book_section_names_its_book(chapter_ref, style, expected):
    assert expected in format_citation(chapter_ref, style)


@pytest.mark.parametrize("style, expected", [
    ("apa7", "In *Proceedings of the Forecasting Summit* (pp. 303–362). Springer."),
    ("ieee", "in *Proceedings of the Forecasting Summit*, Boston, 2020, pp. 303–362."),
])
def test_proceedings_paper_names_its_proceedings(chapter_ref, style, expected):
    ref = {**chapter_ref, "ref_type": "Conference Proceedings", "journal": "Proceedings of the Forecasting Summit"}
    assert expected in format_citation(ref, style)


@pytest.mark.parametrize("style, expected", [
    ("apa7", "*Schedule Unreliability in Liner Shipping* [Paper presentation]. EURAM 2021, Online."),
    ("harvard", "'Schedule Unreliability in Liner Shipping', *EURAM 2021*. Online."),
    ("vancouver", "Shipping. Paper presented at: EURAM 2021; 2020; Online."),
    ("chicago", "Shipping.\" Paper presented at EURAM 2021, Online."),
    ("ieee", "Shipping,\" presented at EURAM 2021, Online, 2020."),
])
def test_conference_paper_names_its_conference(presentation_ref, style, expected):
    assert expected in format_citation(presentation_ref, style)


def test_year_kept_without_publisher(sample_book_ref):
    sample_book_ref["publisher"] = ""
    assert format_citation(sample_book_ref, "vancouver").endswith("Dynamics. 2011.")
    # IEEE italicises a book's title
    assert format_citation(sample_book_ref, "ieee").endswith("Dynamics*. 2011.")


def test_chicago_group_author(sample_ref):
    sample_ref["authors"] = ["World Health Organization,"]
    assert format_citation(sample_ref, "chicago").startswith("World Health Organization. 2020.")


def test_chicago_two_authors_take_a_comma(sample_ref):
    assert format_citation(sample_ref, "chicago").startswith("Smith, John A., and Mary B. Jones. 2020.")


def test_chicago_two_group_authors_take_no_comma(sample_ref):
    sample_ref["authors"] = ["World Health Organization,", "UNICEF,"]
    assert format_citation(sample_ref, "chicago").startswith("World Health Organization and UNICEF. 2020.")


ELEVEN_AUTHORS = [
    "Adams, Ann", "Baker, Ben", "Clark, Cara", "Davis, Dan", "Evans, Eve", "Fox, Finn",
    "Gray, Gus", "Hill, Hal", "Irwin, Ida", "James, Jo", "King, Kim",
]


def test_chicago_lists_up_to_ten_authors(sample_ref):
    sample_ref["authors"] = ELEVEN_AUTHORS[:10]
    assert format_citation(sample_ref, "chicago").startswith(
        "Adams, Ann, Ben Baker, Cara Clark, Dan Davis, Eve Evans, Finn Fox, "
        "Gus Gray, Hal Hill, Ida Irwin, and Jo James. 2020."
    )


def test_chicago_more_than_ten_authors_list_seven_and_et_al(sample_ref):
    sample_ref["authors"] = ELEVEN_AUTHORS
    # "et al." takes one full stop, not two
    assert format_citation(sample_ref, "chicago").startswith(
        "Adams, Ann, Ben Baker, Cara Clark, Dan Davis, Eve Evans, Finn Fox, "
        "Gus Gray, et al. 2020."
    )


def test_ieee_lists_up_to_six_authors(sample_ref):
    sample_ref["authors"] = ELEVEN_AUTHORS[:6]
    assert format_citation(sample_ref, "ieee").startswith(
        "A. Adams, B. Baker, C. Clark, D. Davis, E. Evans, and F. Fox, "
    )


def test_ieee_more_than_six_authors_take_the_first_and_et_al(sample_ref):
    sample_ref["authors"] = ELEVEN_AUTHORS[:7]
    assert format_citation(sample_ref, "ieee").startswith('A. Adams et al., "Schedule')


def test_title_question_mark_takes_no_full_stop(sample_ref, sample_book_ref):
    sample_ref["title"] = "Is Liner Shipping Reliable?"
    assert "Reliable? *Maritime" in format_citation(sample_ref, "apa7")
    assert 'Reliable?" *Maritime' in format_citation(sample_ref, "chicago")
    sample_book_ref["title"] = "Strategy as Practice?"
    assert "*Strategy as Practice?* Financial" in format_citation(sample_book_ref, "apa7")


def test_missing_year_is_nd(sample_ref):
    sample_ref["year"] = ""
    assert "(n.d.)." in format_citation(sample_ref, "apa7")
    for style in ("chicago", "ieee"):
        cite = format_citation(sample_ref, style)
        assert "n.d." in cite and "n.d.." not in cite
    # Citing Medicine writes a missing date as [date unknown]
    assert "Logistics. [date unknown];15(3):123-145." in format_citation(sample_ref, "vancouver")


# ---- format_citation: Edge cases ----

def test_unknown_style_raises(sample_ref):
    with pytest.raises(ValueError, match="Unknown style"):
        format_citation(sample_ref, "mla")


def test_authors_as_json_string(sample_ref):
    sample_ref["authors"] = json.dumps(["Smith, John A.", "Jones, Mary B."])
    cite = format_citation(sample_ref, "apa7")
    assert "Smith, J. A." in cite


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


def test_invert_author_full_given_names():
    # EndNote exports "Surname, Given names"; APA and Harvard want initials
    assert _invert_author("Meissner, Philip") == "Meissner, P."
    assert _invert_author("Schoemaker, Paul J. H.") == "Schoemaker, P. J. H."


def test_invert_author_initials_without_spaces():
    assert _invert_author("Smith, J.A.") == "Smith, J. A."
    assert _invert_author("Turpin, SM") == "Turpin, S. M."


def test_invert_author_hyphenated_given_name():
    assert _invert_author("Rodrigue, Jean-Paul") == "Rodrigue, J.-P."


def test_invert_author_suffix():
    assert _invert_author("Ketchen, David J., Jr.") == "Ketchen, D. J., Jr."


def test_invert_author_corporate():
    # EndNote marks a corporate author with a trailing comma and writes a
    # comma inside its name as ",,"
    assert _invert_author("World Health Organization,") == "World Health Organization"
    assert _invert_author("Becton,, Dickinson and Company") == "Becton, Dickinson and Company"


def test_invert_author_skips_import_debris():
    assert _invert_author("Robbins, Stephen P. author") == "Robbins, S. P."


def test_invert_author_several_people_left_as_entered():
    assert _invert_author("Chermack, T. J., Glick, M., Cumming, J. M.,") == (
        "Chermack, T. J., Glick, M., Cumming, J. M."
    )


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


def test_vancouver_author_name_initials_and_corporate():
    assert _vancouver_author_name("Smith, J.A.") == "Smith JA"
    assert _vancouver_author_name("Turpin, SM") == "Turpin SM"
    assert _vancouver_author_name("Rodrigue, Jean-Paul") == "Rodrigue JP"
    assert _vancouver_author_name("World Health Organization,") == "World Health Organization"


def test_direct_order_initials():
    assert _direct_order_initials("Smith, J.A.") == "J. A. Smith"
    assert _direct_order_initials("Rodrigue, Jean-Paul") == "J.-P. Rodrigue"
    assert _direct_order_initials("Ketchen, David J., Jr.") == "D. J. Ketchen, Jr."
    assert _direct_order_initials("World Health Organization,") == "World Health Organization"


def test_apa_authors_single():
    result = _apa_authors(["Smith, J."])
    assert result == "Smith, J."


def test_apa_authors_two():
    result = _apa_authors(["Smith, J.", "Jones, M."])
    assert result == "Smith, J., & Jones, M."


def test_apa_authors_three():
    result = _apa_authors(["Smith, J.", "Jones, M.", "Brown, A."])
    assert result == "Smith, J., Jones, M., & Brown, A."


def test_apa_authors_21():
    authors = [f"Author{i}, X." for i in range(21)]
    result = _apa_authors(authors)
    assert "..." in result
    assert "Author0, X." in result
    assert "Author20, X." in result


# ---- Reports and web pages: cited as online sources ----

import datetime as _date_mod

from endnote_mcp.citation import _bibtex_author, _is_author, _parse_date


@pytest.fixture
def report_ref():
    return {
        "rec_number": 12, "ref_type": "Report", "title": "Delivering Scotland's Blue Economy approach",
        "authors": ["Scottish Government,"], "year": "2022", "journal": "", "volume": "", "issue": "",
        "pages": "", "doi": "", "publisher": "Scottish Government", "place_published": "",
        "url": "https://www.gov.scot/publications/x/", "access_date": "11 November 2026",
    }


@pytest.fixture
def web_ref():
    return {
        "rec_number": 50, "ref_type": "Web Page", "title": "Port statistics", "authors": [], "year": "",
        "journal": "", "volume": "", "issue": "", "pages": "", "doi": "",
        "publisher": "Department for Transport", "place_published": "",
        "url": "https://www.gov.uk/port", "access_date": "29.03.2016",
    }


@pytest.mark.parametrize("style, expected", [
    ("apa7", "Scottish Government. (2022). *Delivering Scotland's Blue Economy approach*. "
             "https://www.gov.scot/publications/x/"),
    ("harvard", "Scottish Government (2022) *Delivering Scotland's Blue Economy approach*. Scottish Government. "
                "Available at: https://www.gov.scot/publications/x/ (Accessed: 11 November 2026)."),
    ("vancouver", "Scottish Government. Delivering Scotland's Blue Economy approach [Internet]. Scottish Government; "
                  "2022 [cited 2026 Nov 11]. Available from: https://www.gov.scot/publications/x/"),
    ("chicago", "Scottish Government. 2022. *Delivering Scotland's Blue Economy approach*. Scottish Government. "
                "https://www.gov.scot/publications/x/."),
    ("ieee", 'Scottish Government, "Delivering Scotland\'s Blue Economy approach," Scottish Government, 2022. '
             "Accessed: Nov. 11, 2026. [Online]. Available: https://www.gov.scot/publications/x/"),
])
def test_online_report(report_ref, style, expected):
    assert format_citation(report_ref, style) == expected


def test_apa_keeps_a_publisher_that_is_not_the_author(report_ref):
    report_ref["publisher"] = "Marine Directorate"
    assert "approach*. Marine Directorate. https://" in format_citation(report_ref, "apa7")


def test_a_doi_takes_the_urls_place(report_ref):
    report_ref["doi"] = "10.1000/xyz"
    for style in ("apa7", "harvard", "vancouver", "chicago", "ieee"):
        cite = format_citation(report_ref, style)
        assert "gov.scot" not in cite and "10.1000/xyz" in cite


def test_report_without_url_is_cited_like_print(report_ref):
    report_ref["url"] = ""
    assert format_citation(report_ref, "harvard").endswith("approach*. Scottish Government.")
    assert "[Internet]" not in format_citation(report_ref, "vancouver")


@pytest.mark.parametrize("style, expected", [
    ("apa7", "*Port statistics*. (n.d.). Department for Transport. "
             "Retrieved March 29, 2016, from https://www.gov.uk/port"),
    ("harvard", "*Port statistics* (n.d.) Available at: https://www.gov.uk/port (Accessed: 29 March 2016)."),
    ("vancouver", "Port statistics [Internet]. Department for Transport; [date unknown] [cited 2016 Mar 29]. "
                  "Available from: https://www.gov.uk/port"),
    ("chicago", '"Port statistics." n.d. Department for Transport. Accessed March 29, 2016. https://www.gov.uk/port.'),
    ("ieee", '"Port statistics." Department for Transport. https://www.gov.uk/port (accessed Mar. 29, 2016).'),
])
def test_undated_web_page_without_author(web_ref, style, expected):
    assert format_citation(web_ref, style) == expected


def test_dated_web_page_needs_no_retrieval_date(web_ref):
    web_ref.update(year="2024", authors=["Department for Transport,"])
    assert format_citation(web_ref, "apa7") == (
        "Department for Transport. (2024). *Port statistics*. https://www.gov.uk/port")
    assert "Accessed" not in format_citation(web_ref, "chicago")


def test_unreadable_access_date_is_printed_as_typed(report_ref):
    report_ref["access_date"] = "2/10/2025"  # 2 October or February 10?
    assert "(Accessed: 2/10/2025)" in format_citation(report_ref, "harvard")


@pytest.mark.parametrize("text, expected", [
    ("11 November 2026", (2026, 11, 11)), ("11 Nov 2026", (2026, 11, 11)),
    ("November 11, 2026", (2026, 11, 11)), ("Sept. 3, 2024", (2024, 9, 3)),
    ("29.03.2016", (2016, 3, 29)), ("2025-02-01T11:43:59", (2025, 2, 1)),
    ("2025/02/01/", (2025, 2, 1)), ("2/24/2025", (2025, 2, 24)), ("24/2/2025", (2025, 2, 24)),
    ("2/10/2025", None), ("01.12.", None), ("31.02.2020", None), ("last week", None), ("", None),
])
def test_parse_date(text, expected):
    assert _parse_date(text) == (_date_mod.date(*expected) if expected else None)


def test_is_author():
    assert _is_author("The Scottish Government", ["Scottish Government,"])
    assert _is_author("Becton, Dickinson and Company", ["Becton,, Dickinson and Company"])
    assert not _is_author("Smith", ["Smith, John"])          # a person, not a publisher
    assert not _is_author("Scottish Government", ["Welsh Government,"])


def test_bibtex_authors_and_link(report_ref):
    assert _bibtex_author("Smith, John A.") == "Smith, John A."
    assert _bibtex_author("King, Martin Luther, Jr.") == "King, Jr., Martin Luther"
    assert _bibtex_author("Becton,, Dickinson and Company") == "{Becton, Dickinson and Company}"
    bib = format_bibtex(report_ref)
    assert "author = {{Scottish Government}}" in bib
    assert "url = {https://www.gov.scot/publications/x/}" in bib
    assert "urldate = {2026-11-11}" in bib


@pytest.mark.parametrize("ref_type, journal", [("Journal Article", "Artificial Intelligence Review"),
                                                ("Web Page", ""), ("Book Section", "A Book"),
                                                ("Conference Paper", "EURAM 2021")])
def test_record_without_title_leaves_no_stray_punctuation(sample_ref, ref_type, journal):
    sample_ref.update(title="", ref_type=ref_type, journal=journal)
    for style in ("apa7", "harvard", "vancouver", "chicago", "ieee"):
        cite = format_citation(sample_ref, style)
        for debris in ("''", '"."', '","', ". .", "**", "[Internet]."):
            assert debris not in cite, (style, cite)


@pytest.mark.parametrize("text, expected", [("05/05/2024", (2024, 5, 5)), ("15. 05. 2022", (2022, 5, 15)),
                                            ("6/12/2022", None)])
def test_parse_date_more_shapes(text, expected):
    assert _parse_date(text) == (_date_mod.date(*expected) if expected else None)


def test_quotes_around_a_whole_title_are_dropped(web_ref):
    web_ref.update(title='"BASIC"', year="2021", authors=["Britannica, Encyclopedia"])
    assert format_citation(web_ref, "chicago").startswith('Britannica, Encyclopedia. 2021. "BASIC." ')
    assert format_citation(web_ref, "ieee").startswith('E. Britannica. "BASIC." ')
    assert "*BASIC*." in format_citation(web_ref, "apa7")


def test_quotes_inside_a_quoted_title_nest(sample_ref):
    sample_ref["title"] = 'Why "blue growth" stalled'
    assert "\"Why 'blue growth' stalled.\"" in format_citation(sample_ref, "chicago")
    assert "\"Why 'blue growth' stalled,\"" in format_citation(sample_ref, "ieee")
    assert "'Why \"blue growth\" stalled'," in format_citation(sample_ref, "harvard")  # single outside, double in


def test_ieee_book_title_is_italic(sample_book_ref):
    cite = format_citation(sample_book_ref, "ieee")
    assert cite == "R. D. Stacey, *Strategic Management and Organisational Dynamics*. Harlow: Financial Times Prentice Hall, 2011."


@pytest.mark.parametrize("style, title, expected", [
    # Harvard quotes titles in single marks, so a quotation inside takes double
    ("harvard", "Thematic analysis as 'saliency analysis'", "'Thematic analysis as \"saliency analysis\"',"),
    ("harvard", "'Cyber' Cargo Crime Called Growing Threat", "'\"Cyber\" Cargo Crime Called Growing Threat',"),
    ("harvard", "Now Cheaper, But not \"Cheap Oil\"", "'Now Cheaper, But not \"Cheap Oil\"',"),
    # Chicago and IEEE use double marks: single inside, and back to double a level deeper
    ("chicago", "'Zombie' malware targets shipping", "\"'Zombie' malware targets shipping.\""),
    ("chicago", "\"Is there such a thing as 'evidence-based management'?\": A commentary",
     "\"'Is there such a thing as \"evidence-based management\"?': A commentary.\""),
    ("ieee", "Scotland's “blue” economy", "\"Scotland's ‘blue’ economy,\""),
    # already alternating the right way round for Harvard: left alone
    ("harvard", "\"Is there such a thing as 'evidence-based management'?\": A commentary",
     "'\"Is there such a thing as 'evidence-based management'?\": A commentary',"),
])
def test_quotations_inside_titles_alternate(sample_ref, style, title, expected):
    sample_ref["title"] = title
    assert expected in format_citation(sample_ref, style)
