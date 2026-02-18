"""Shared fixtures for endnote-mcp tests."""

import json
import sqlite3
from pathlib import Path

import pytest

from endnote_mcp.db import _create_schema, upsert_reference, insert_pdf_page


@pytest.fixture
def sample_ref():
    """A complete journal article reference dict."""
    return {
        "rec_number": 42,
        "ref_type": "Journal Article",
        "title": "Schedule Unreliability in Liner Shipping",
        "authors": ["Smith, John A.", "Jones, Mary B."],
        "year": "2020",
        "journal": "Maritime Economics & Logistics",
        "volume": "15",
        "issue": "3",
        "pages": "123-145",
        "abstract": "This paper examines schedule unreliability in liner shipping.",
        "keywords": ["shipping", "supply chain", "reliability"],
        "doi": "10.1234/example.doi",
        "url": "https://example.com/paper",
        "publisher": "Palgrave Macmillan",
        "place_published": "London",
        "edition": "",
        "isbn": "",
        "label": "",
        "notes": "",
        "pdf_path": "smith2020.pdf",
    }


@pytest.fixture
def sample_book_ref():
    """A book reference for testing ref_type branching."""
    return {
        "rec_number": 100,
        "ref_type": "Book",
        "title": "Strategic Management and Organisational Dynamics",
        "authors": ["Stacey, Ralph D."],
        "year": "2011",
        "journal": "",
        "volume": "",
        "issue": "",
        "pages": "",
        "abstract": "A textbook on complexity and strategic management.",
        "keywords": ["strategic planning", "organizational behavior"],
        "doi": "",
        "url": "",
        "publisher": "Financial Times Prentice Hall",
        "place_published": "Harlow",
        "edition": "6th",
        "isbn": "978-0273725596",
        "label": "",
        "notes": "",
        "pdf_path": "",
    }


def _ref_to_db_dict(ref: dict) -> dict:
    """Convert a fixture ref dict to the format expected by upsert_reference."""
    d = dict(ref)
    if isinstance(d["authors"], list):
        d["authors"] = json.dumps(d["authors"])
    if isinstance(d.get("keywords"), list):
        d["keywords"] = json.dumps(d["keywords"])
    return d


@pytest.fixture
def db_conn():
    """In-memory SQLite database with schema created."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def populated_db(db_conn):
    """DB with 5 sample refs and 2 with PDF pages, ready for search tests."""
    refs = [
        {
            "rec_number": 1,
            "ref_type": "Journal Article",
            "title": "Social Capital and Community Development",
            "authors": json.dumps(["Bourdieu, Pierre"]),
            "year": "2018",
            "journal": "Sociology Review",
            "volume": "10",
            "issue": "2",
            "pages": "50-75",
            "abstract": "Analysis of social capital in urban communities.",
            "keywords": json.dumps(["social capital", "community", "Bourdieu"]),
            "doi": "10.1000/socrev.2018",
            "url": "",
            "publisher": "",
            "place_published": "",
            "edition": "",
            "isbn": "",
            "label": "",
            "notes": "",
            "pdf_path": "bourdieu2018.pdf",
        },
        {
            "rec_number": 2,
            "ref_type": "Journal Article",
            "title": "Grounded Theory Methods in Qualitative Research",
            "authors": json.dumps(["Charmaz, Kathy", "Smith, John"]),
            "year": "2019",
            "journal": "Qualitative Studies",
            "volume": "5",
            "issue": "1",
            "pages": "1-25",
            "abstract": "A practical guide to grounded theory methodology.",
            "keywords": json.dumps(["grounded theory", "qualitative", "methodology"]),
            "doi": "10.1000/qs.2019",
            "url": "",
            "publisher": "",
            "place_published": "",
            "edition": "",
            "isbn": "",
            "label": "",
            "notes": "",
            "pdf_path": "charmaz2019.pdf",
        },
        {
            "rec_number": 3,
            "ref_type": "Book",
            "title": "Strategic Management and Organisational Dynamics",
            "authors": json.dumps(["Stacey, Ralph D."]),
            "year": "2011",
            "journal": "",
            "volume": "",
            "issue": "",
            "pages": "",
            "abstract": "Complexity thinking applied to strategic management.",
            "keywords": json.dumps(["strategy", "complexity", "management"]),
            "doi": "",
            "url": "",
            "publisher": "Prentice Hall",
            "place_published": "Harlow",
            "edition": "",
            "isbn": "978-0273725596",
            "label": "",
            "notes": "",
            "pdf_path": "",
        },
        {
            "rec_number": 4,
            "ref_type": "Journal Article",
            "title": "Scenario Planning for Strategic Foresight",
            "authors": json.dumps(["Van der Heijden, Kees"]),
            "year": "2020",
            "journal": "Futures",
            "volume": "22",
            "issue": "4",
            "pages": "300-320",
            "abstract": "How organisations use scenario planning to deal with uncertainty.",
            "keywords": json.dumps(["scenario planning", "foresight", "uncertainty"]),
            "doi": "10.1000/futures.2020",
            "url": "",
            "publisher": "",
            "place_published": "",
            "edition": "",
            "isbn": "",
            "label": "",
            "notes": "",
            "pdf_path": "vdh2020.pdf",
        },
        {
            "rec_number": 5,
            "ref_type": "Journal Article",
            "title": "Supply Chain Resilience in Maritime Transport",
            "authors": json.dumps(["Bourdieu, Pierre", "Van der Heijden, Kees"]),
            "year": "2022",
            "journal": "Maritime Economics & Logistics",
            "volume": "30",
            "issue": "1",
            "pages": "10-35",
            "abstract": "Examining resilience in maritime supply chains under disruption.",
            "keywords": json.dumps(["supply chain", "resilience", "maritime", "shipping"]),
            "doi": "10.1000/mel.2022",
            "url": "",
            "publisher": "",
            "place_published": "",
            "edition": "",
            "isbn": "",
            "label": "",
            "notes": "",
            "pdf_path": "bvdh2022.pdf",
        },
    ]

    for ref in refs:
        upsert_reference(db_conn, ref)

    # Add PDF pages for refs 1 and 2
    insert_pdf_page(db_conn, 1, 1, "This page discusses social capital theory and Bourdieu's framework for understanding community dynamics.")
    insert_pdf_page(db_conn, 1, 2, "The second page examines field theory and habitus in urban settings.")
    insert_pdf_page(db_conn, 2, 1, "Grounded theory is a systematic methodology involving the construction of theories through data analysis.")
    insert_pdf_page(db_conn, 2, 2, "Open coding and axial coding are key techniques in grounded theory research.")

    db_conn.commit()
    return db_conn


@pytest.fixture
def sample_xml(tmp_path):
    """Small EndNote XML file with 3 records."""
    xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <records>
    <record>
      <rec-number>1</rec-number>
      <ref-type name="Journal Article">17</ref-type>
      <contributors>
        <authors>
          <author><style face="normal" font="default" size="100%">Smith, John A.</style></author>
          <author><style face="normal" font="default" size="100%">Jones, Mary B.</style></author>
        </authors>
      </contributors>
      <titles>
        <title><style face="normal" font="default" size="100%">Test Article Title</style></title>
        <secondary-title><style face="normal" font="default" size="100%">Test Journal</style></secondary-title>
      </titles>
      <dates>
        <year><style face="normal" font="default" size="100%">2020</style></year>
      </dates>
      <volume><style face="normal" font="default" size="100%">15</style></volume>
      <number><style face="normal" font="default" size="100%">3</style></number>
      <pages><style face="normal" font="default" size="100%">100-120</style></pages>
      <abstract><style face="normal" font="default" size="100%">This is a test abstract.</style></abstract>
      <keywords>
        <keyword><style face="normal" font="default" size="100%">testing</style></keyword>
        <keyword><style face="normal" font="default" size="100%">automation</style></keyword>
      </keywords>
      <electronic-resource-num><style face="normal" font="default" size="100%">10.1234/test</style></electronic-resource-num>
      <urls>
        <related-urls>
          <url><style face="normal" font="default" size="100%">https://example.com</style></url>
        </related-urls>
        <pdf-urls>
          <url><style face="normal" font="default" size="100%">internal-pdf://smith2020.pdf</style></url>
        </pdf-urls>
      </urls>
      <publisher><style face="normal" font="default" size="100%">Test Publisher</style></publisher>
      <pub-location><style face="normal" font="default" size="100%">London</style></pub-location>
    </record>
    <record>
      <rec-number>2</rec-number>
      <ref-type name="Book">6</ref-type>
      <contributors>
        <authors>
          <author><style face="normal" font="default" size="100%">Brown, Alice</style></author>
        </authors>
      </contributors>
      <titles>
        <title><style face="normal" font="default" size="100%">A Book About Testing</style></title>
      </titles>
      <dates>
        <year><style face="normal" font="default" size="100%">2019</style></year>
      </dates>
      <keywords>
        <keyword><style face="normal" font="default" size="100%">books</style></keyword>
      </keywords>
      <publisher><style face="normal" font="default" size="100%">Academic Press</style></publisher>
      <pub-location><style face="normal" font="default" size="100%">New York</style></pub-location>
      <isbn><style face="normal" font="default" size="100%">978-1234567890</style></isbn>
    </record>
    <record>
      <rec-number>3</rec-number>
      <ref-type name="Conference Proceedings">10</ref-type>
      <contributors>
        <authors>
          <author><style face="normal" font="default" size="100%">Davis, Carol</style></author>
          <author><style face="normal" font="default" size="100%">Evans, David</style></author>
        </authors>
      </contributors>
      <titles>
        <title><style face="normal" font="default" size="100%">Conference Paper on Automation</style></title>
        <secondary-title><style face="normal" font="default" size="100%">Proceedings of Testing Conference</style></secondary-title>
      </titles>
      <dates>
        <year><style face="normal" font="default" size="100%">2021</style></year>
      </dates>
      <pages><style face="normal" font="default" size="100%">50-55</style></pages>
      <urls>
        <pdf-urls>
          <url><style face="normal" font="default" size="100%">internal-pdf://0123456789/davis2021.pdf</style></url>
        </pdf-urls>
      </urls>
    </record>
  </records>
</xml>
"""
    xml_path = tmp_path / "test_library.xml"
    xml_path.write_text(xml_content, encoding="utf-8")
    return xml_path
