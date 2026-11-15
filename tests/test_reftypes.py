"""The generated label maps: internally consistent, and EndNote's quirks pinned."""

import pytest

from endnote_mcp.reftypes import GENERIC_XML, LIST_FIELDS, NAME_FIELDS, REF_TYPES


@pytest.mark.parametrize("ref_type", REF_TYPES)
def test_every_label_has_a_place_in_the_xml(ref_type):
    _number, labels = REF_TYPES[ref_type]
    assert set(labels.values()) <= set(GENERIC_XML)
    # one label per generic field, so a stored field maps back to one label
    assert len(set(labels.values())) == len(labels)
    for generic in ("Author", "Title", "Year", "URL", "Label"):
        assert generic in labels.values()


def test_name_and_list_fields_exist():
    assert NAME_FIELDS <= set(GENERIC_XML) and LIST_FIELDS <= set(GENERIC_XML)


def test_numbers_match_endnote_xml():
    assert {t: n for t, (n, _) in REF_TYPES.items()} == {
        "Journal Article": 17, "Book": 6, "Book Section": 5,
        "Report": 27, "Web Page": 12, "Conference Proceedings": 10,
    }


@pytest.mark.parametrize("ref_type, label, generic", [
    ("Web Page", "Access Date", "Number"),
    ("Report", "Institution", "Publisher"),
    ("Report", "Publisher", "Tertiary Author"),
    ("Report", "Report Number", "ISBN/ISSN"),
    ("Report", "Issue", "Custom 6"),
    ("Book", "Pages", "Section"),
    ("Book", "Number of Pages", "Pages"),
    ("Journal Article", "Journal", "Secondary Title"),
    ("Journal Article", "Issue", "Number"),
    ("Conference Proceedings", "Year of Conference", "Year"),
])
def test_endnote_quirks(ref_type, label, generic):
    assert REF_TYPES[ref_type][1][label] == generic
