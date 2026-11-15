"""add_reference: request checking, EndNote XML, duplicates, PDFs, the whole flow.

EndNote itself is replaced by FakeApp, which imports, finds and exports the
way EndNote 2025 was seen to (scripts/verify_reftypes_live.py checks the
real thing).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from endnote_mcp import writer
from endnote_mcp.config import Config
from endnote_mcp.endnote_app import EndNoteError, parse_record_id
from endnote_mcp.reftypes import GENERIC_XML
from endnote_mcp.writer import (
    AddReferenceError,
    LABEL,
    add_reference,
    differences,
    display_name,
    draft_record,
    endnote_name,
    library_path,
    library_pdf_dir,
    record_fields,
    record_xml,
)

TODAY = dt.date(2026, 11, 11)
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def values(draft, generic):
    return draft.values.get(GENERIC_XML[generic], [])


# ---------------------------------------------------------------- names

@pytest.mark.parametrize("given, stored", [
    ("Öztürk, İsmail Çağrı", "Öztürk, İsmail Çağrı"),
    ("  Smith ,  John A. ", "Smith, John A."),
    ("King, Martin Luther, Jr.", "King, Martin Luther, Jr."),
    ("{Scottish Government}", "Scottish Government,"),
    ("{Becton, Dickinson and Company}", "Becton,, Dickinson and Company"),
    ("{Becton,, Dickinson and Company}", "Becton,, Dickinson and Company"),
    ("{Çevre, Şehircilik ve İklim Değişikliği Bakanlığı}",
     "Çevre,, Şehircilik ve İklim Değişikliği Bakanlığı"),
    ("{Plato}", "Plato,"),
])
def test_endnote_name(given, stored):
    assert endnote_name(given) == stored


@pytest.mark.parametrize("bad", ["Scottish Government", "Smith", "{}", "{Open", "A, B, C, D", "Smith,"])
def test_endnote_name_rejects_what_it_cannot_file(bad):
    with pytest.raises(AddReferenceError):
        endnote_name(bad)


def test_display_name():
    assert display_name("Scottish Government,") == "Scottish Government (organisation)"
    assert display_name("Becton,, Dickinson and Company") == "Becton, Dickinson and Company (organisation)"
    assert display_name("Smith, John A.") == "Smith, John A."


# ---------------------------------------------------------------- drafting

def test_report_fields_land_in_endnotes_generic_fields():
    d = draft_record(
        "Report", "Scenarios for Scotland’s Blue Economy", ["{Scottish Government}"], "2025",
        "https://www.gov.scot/publications/scenarios/",
        {"Institution": "Scottish Government", "Place Published": "Edinburgh",
         "Report Number": "ISBN 978-1-83601-000-0", "Publisher": ["{Marine Directorate}"]},
        today=TODAY,
    )
    assert d.ref_type == "Report"
    assert values(d, "Author") == ["Scottish Government,"]
    assert d.values["publisher"] == ["Scottish Government"]          # Institution
    assert d.values["isbn"] == ["ISBN 978-1-83601-000-0"]            # Report Number
    assert d.values["contributors/tertiary-authors/author"] == ["Marine Directorate,"]  # Publisher
    assert d.values["access-date"] == ["11 November 2026"]
    assert d.values["label"] == [LABEL]


def test_web_page_access_date_goes_in_the_number_field():
    d = draft_record("Web Page", "A page", [], "2026", "https://example.org/p", today=TODAY)
    assert d.values["number"] == ["11 November 2026"]
    assert "access-date" not in d.values


def test_given_access_date_is_kept():
    d = draft_record("Report", "R", [], "2026", "https://example.org/r",
                     {"Access Date": "3 March 2026"}, today=TODAY)
    assert d.values["access-date"] == ["3 March 2026"]


def test_no_access_date_without_url_or_for_articles():
    assert "access-date" not in draft_record("Report", "R", today=TODAY).values
    article = draft_record("Journal Article", "A", url="https://doi.org/10.1/x", today=TODAY)
    assert "access-date" not in article.values


def test_journal_article_labels():
    d = draft_record("journal article", "T", ["Smith, J."], "2020", fields={
        "Journal": "Futures", "Volume": "12", "issue": "3", "Pages": "1–20",
        "DOI": "https://doi.org/10.1016/J.FUTURES.2020.1", "Keywords": ["a", " b ", ""],
    })
    assert d.ref_type == "Journal Article"
    assert d.values["titles/secondary-title"] == ["Futures"]
    assert d.values["number"] == ["3"]
    assert d.values["electronic-resource-num"] == ["10.1016/J.FUTURES.2020.1"]
    assert d.values["keywords/keyword"] == ["a", "b"]


def test_book_pages_is_endnotes_section_field():
    d = draft_record("Book", "B", fields={"Pages": "xii", "Number of Pages": "320",
                                          "Editor": ["Doe, Jane", "{Some Institute}"]})
    assert d.values["section"] == ["xii"]
    assert d.values["pages"] == ["320"]
    assert d.values["contributors/tertiary-authors/author"] == ["Doe, Jane", "Some Institute,"]


def test_conference_year_is_the_year_parameter():
    d = draft_record("Conference Proceedings", "P", year="2024")
    assert d.values["dates/year"] == ["2024"]
    with pytest.raises(AddReferenceError, match="year parameter"):
        draft_record("Conference Proceedings", "P", fields={"Year of Conference": "2024"})


@pytest.mark.parametrize("fields, message", [
    ({"Journal": "x"}, "has no field 'Journal'"),
    ({"Label": "x"}, "set automatically"),
    ({"URL": "https://x.org"}, "url parameter"),
    ({"Title": "x"}, "title parameter"),
    ({"Institution": ["a", "b"]}, "one value"),
    ({"Pages": "1", "pages": "2"}, "given twice"),
    ({"Editor": "Not A Person Format"}, "has no field"),
])
def test_report_rejects(fields, message):
    with pytest.raises(AddReferenceError, match=message):
        draft_record("Report", "R", fields=fields)


def test_unknown_field_lists_the_types_fields():
    with pytest.raises(AddReferenceError) as e:
        draft_record("Report", "R", fields={"Journal": "x"})
    assert "Institution" in str(e.value) and "Report Number" in str(e.value)
    assert "Label" not in str(e.value).split("Its fields:")[1]


@pytest.mark.parametrize("kwargs, message", [
    ({"reference_type": "Thesis"}, "Reference types"),
    ({"title": "  "}, "title is needed"),
    ({"year": "2025-03-01"}, "four-digit year"),
    ({"url": "www.example.org"}, "http"),
])
def test_rejects_bad_requests(kwargs, message):
    args = {"reference_type": "Report", "title": "T", **kwargs}
    with pytest.raises(AddReferenceError, match=message):
        draft_record(**args)


def test_year_may_be_in_press():
    assert draft_record("Report", "T", year="in press").values["dates/year"] == ["in press"]


def test_text_is_cleaned():
    d = draft_record("Report", " A\x0btitle \n split  ", fields={
        "Abstract": "Line one.\r\nLine  two.\r\n", "Notes": "x\x00y"})
    assert d.values["titles/title"] == ["Atitle split"]
    assert d.values["abstract"] == ["Line one.\nLine two."]
    assert d.values["notes"] == ["xy"]


def test_text_is_nfc():
    decomposed = "Güzel"  # ü as u + combining diaeresis
    d = draft_record("Report", decomposed)
    assert d.values["titles/title"] == ["Güzel"]


# ---------------------------------------------------------------- XML

def test_record_xml_round_trips_through_record_fields():
    d = draft_record("Report", "Türkiye’nin Su Kaynakları – 2025", ["{Çevre, Şehircilik}", "Öztürk, İ."],
                     "2025", "https://example.gov.tr/r.pdf",
                     {"Institution": "DSİ", "Keywords": ["su", "iklim"]}, today=TODAY)
    xml = record_xml(d, "internal-pdf://1234567890/r.pdf")
    rec = ET.fromstring(xml.encode()).find("records/record")
    assert rec.find("ref-type").get("name") == "Report" and rec.find("ref-type").text == "27"
    got = record_fields(rec)
    assert ("urls/pdf-urls/url", "internal-pdf://1234567890/r.pdf") in got
    assert ("contributors/authors/author", "Çevre,, Şehircilik") in got
    assert [v for p, v in got if p == "keywords/keyword"] == ["su", "iklim"]
    # contributors come before titles, and both URLs share one <urls>
    tags = [c.tag for c in rec]
    assert tags.index("contributors") < tags.index("titles")
    assert [c.tag for c in rec.find("urls")] == ["related-urls", "pdf-urls"]


def test_record_fields_ignores_styles_and_what_endnote_assigns():
    rec = ET.fromstring(
        '<record><database name="L.enl" path="/L.enl">L.enl</database><rec-number>9</rec-number>'
        '<foreign-keys><key app="EN">9</key></foreign-keys><ref-type name="Report">27</ref-type>'
        '<titles><title><style face="normal">A\r\nB</style></title></titles><mystery>x</mystery></record>'
    )
    assert record_fields(rec) == [("ref-type", "Report/27"), ("titles/title", "A\nB")]


def test_differences():
    sent = [("titles/title", "A"), ("issue", "3")]
    assert differences(sent, list(sent)) == []
    assert differences(sent, [("titles/title", "A")]) == [("issue", ["3"], [])]
    assert differences(sent, [("titles/title", "B"), ("issue", "3")]) == [("titles/title", ["A"], ["B"])]


# ---------------------------------------------------------------- library paths

def _cfg(tmp_path, **kw):
    base = dict(endnote_xml=tmp_path / "lib.xml", pdf_dir=tmp_path / "Test.Data" / "PDF",
                db_path=tmp_path / "index.db")
    base.update(kw)
    return Config(**base)


def test_library_path(tmp_path):
    assert library_path(_cfg(tmp_path, endnote_library=tmp_path / "X.enl")) == tmp_path / "X.enl"
    pkg = tmp_path / "My Library.enlp"
    assert library_path(_cfg(tmp_path, pdf_dir=pkg / "My Library.Data" / "PDF")) == pkg
    (tmp_path / "Test.enl").write_text("")
    assert library_path(_cfg(tmp_path)) == tmp_path / "Test.enl"
    with pytest.raises(AddReferenceError, match="endnote_library"):
        library_path(_cfg(tmp_path, pdf_dir=tmp_path / "PDFs"))


def test_library_pdf_dir(tmp_path):
    assert library_pdf_dir(tmp_path / "A.enlp") == tmp_path / "A.enlp" / "A.Data" / "PDF"
    assert library_pdf_dir(tmp_path / "A.enl") == tmp_path / "A.Data" / "PDF"


# ---------------------------------------------------------------- PDFs

class FakeResponse:
    def __init__(self, data, headers=None, url="https://example.org/files/report.pdf"):
        self._data, self.headers, self._url = data, headers or {}, url

    def read(self, n=-1):
        return self._data if n < 0 else self._data[:n]

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, response=None, error=None):
    def urlopen(request, timeout=None, context=None):
        if error:
            raise error
        return response
    monkeypatch.setattr("urllib.request.urlopen", urlopen)


def test_download_pdf_stores_it_like_endnote(tmp_path, monkeypatch):
    _serve(monkeypatch, FakeResponse(PDF_BYTES))
    att = writer.download_pdf("https://example.org/files/report.pdf", tmp_path / "PDF", "T")
    folder = att.path.parent.name
    assert folder.isdigit() and len(folder) == 10
    assert att.link == f"internal-pdf://{folder}/report.pdf"
    assert att.path.read_bytes() == PDF_BYTES and att.size == len(PDF_BYTES)


def test_download_pdf_names(tmp_path, monkeypatch):
    _serve(monkeypatch, FakeResponse(PDF_BYTES, {"Content-Disposition": 'attachment; filename="Su Raporu: 2025.pdf"'}))
    assert writer.download_pdf("https://x.org/dl?id=1", tmp_path, "T").path.name == "Su Raporu- 2025.pdf"
    _serve(monkeypatch, FakeResponse(PDF_BYTES, url="https://x.org/download?id=7"))
    assert writer.download_pdf("https://x.org/download?id=7", tmp_path, "My / Title").path.name == "My - Title.pdf"


@pytest.mark.parametrize("response, error, message", [
    (FakeResponse(b"<!doctype html><html>", {"Content-Type": "text/html"}), None, "rather than a PDF"),
    (None, urllib.error.HTTPError("u", 403, "Forbidden", {}, None), "HTTP 403"),
    (None, urllib.error.URLError("no route"), "could not be downloaded"),
])
def test_download_pdf_failures(tmp_path, monkeypatch, response, error, message):
    _serve(monkeypatch, response, error)
    with pytest.raises(AddReferenceError, match=message):
        writer.download_pdf("https://x.org/a.pdf", tmp_path / "PDF", "T")
    assert not (tmp_path / "PDF").exists()


# ---------------------------------------------------------------- the whole flow

LIB = "Test.enl"


class FakeApp:
    """Imports, finds and exports the way EndNote 2025 does, in memory."""

    def __init__(self, db_path="/x/Test.enl", mutate=None, fail_import=False):
        self.db_path, self.mutate, self.fail_import = db_path, mutate, fail_import
        self.records: dict[int, ET.Element] = {}
        self.imports: list[str] = []
        self.opened = None

    @staticmethod
    def rid(n, db=1):
        return f'<RecordID database="{db}" recNum="{n}" />'

    def open_library(self, path):
        self.opened = path

    def record_ids(self, library):
        assert library == LIB
        return [self.rid(n) for n in self.records]

    def find(self, text, generic_field):
        path = GENERIC_XML[generic_field]
        hits = [self.rid(n) for n, rec in self.records.items()
                if any(p == path and text.lower() in v.lower() for p, v in record_fields(rec))]
        return hits + [self.rid(99, db=2)]  # a hit in another open library

    def import_xml(self, xml, library):
        if self.fail_import:
            raise EndNoteError("EndNote did not respond in time.")
        self.imports.append(xml)
        for rec in ET.fromstring(xml.encode()).iter("record"):
            if self.mutate:
                self.mutate(rec)
            n = max(self.records, default=0) + 1
            rec.insert(0, ET.Element("database", name=LIB, path=self.db_path))
            ET.SubElement(rec, "rec-number").text = str(n)
            self.records[n] = rec

    def export(self, record_ids):
        recs = [self.records[parse_record_id(r)[1]] for r in record_ids if parse_record_id(r)[0] == 1]
        return ('<?xml version="1.0" encoding="UTF-8" ?><xml><records>'
                + "".join(ET.tostring(r, encoding="unicode") for r in recs) + "</records></xml>")

    def temporary_citation(self, record_id):
        return "{Fake, 2025 #%d}" % parse_record_id(record_id)[1]


@pytest.fixture
def setup(tmp_path):
    """A config whose index is built from the fake library, and the fake."""
    xml = tmp_path / "export.xml"
    xml.write_text('<xml><records><record><database name="Test.enl" path="/x/Test.enl">Test.enl'
                   "</database><rec-number>1</rec-number></record></records></xml>", encoding="utf-8")
    cfg = _cfg(tmp_path, endnote_xml=xml, endnote_library=tmp_path / LIB)
    return cfg, FakeApp()


REPORT = dict(
    reference_type="Report", title="Scenarios for Scotland’s Blue Economy: Final Report",
    authors=["{Scottish Government}"], year="2025",
    url="https://www.gov.scot/publications/scenarios-scotlands-blue-economy-final-report/",
    fields={"Institution": "Scottish Government", "Place Published": "Edinburgh"},
)


def test_adds_verifies_and_indexes(setup):
    cfg, app = setup
    out = add_reference(app, cfg, today=TODAY, **REPORT)
    assert out.startswith("Added to EndNote as record [1], a Report in Test.enl.")
    assert "  Author: Scottish Government (organisation)" in out
    assert "  Institution: Scottish Government" in out
    assert "  Access Date: 11 November 2026" in out
    assert "  Label: Added by Claude" in out
    assert "all 8 fields stored exactly as sent" in out
    assert "{Fake, 2025 #1}" in out and "Cite it here as [1]" in out
    assert app.opened == cfg.endnote_library

    conn = sqlite3.connect(cfg.db_path)
    row = conn.execute("SELECT ref_type, title, authors, publisher, label FROM references_ "
                       "WHERE rec_number = 1").fetchone()
    assert row == ("Report", REPORT["title"], json.dumps(["Scottish Government,"]),
                   "Scottish Government", LABEL)


def test_reports_fields_endnote_did_not_keep(setup):
    cfg, _ = setup
    def drop_place(rec):
        rec.remove(rec.find("pub-location"))
    out = add_reference(FakeApp(mutate=drop_place), cfg, today=TODAY, **REPORT)
    assert "1 field(s) differ" in out
    assert "  Place Published: sent Edinburgh, stored (nothing)" in out


@pytest.mark.parametrize("change, why", [
    ({"url": "http://gov.scot/publications/scenarios-scotlands-blue-economy-final-report"}, "same URL"),
    ({"url": "", "title": "Scenarios for Scotland's Blue Economy - Final Report"}, "same title and year"),
])
def test_refuses_a_duplicate(setup, change, why):
    cfg, app = setup
    add_reference(app, cfg, today=TODAY, **REPORT)
    out = add_reference(app, cfg, today=TODAY, **{**REPORT, **change})
    assert out.startswith("Not added: the library already has this source.")
    assert f"[1] Scottish Government (2025). {REPORT['title']} ({why}" in out
    assert len(app.imports) == 1


def test_same_title_other_year_is_not_a_duplicate(setup):
    cfg, app = setup
    add_reference(app, cfg, today=TODAY, **{**REPORT, "url": ""})
    out = add_reference(app, cfg, today=TODAY, **{**REPORT, "url": "", "year": "2026"})
    assert out.startswith("Added to EndNote as record [2]")


def test_duplicate_by_doi(setup):
    cfg, app = setup
    art = dict(reference_type="Journal Article", title="One", authors=["Smith, J."], year="2020",
               fields={"DOI": "10.1000/ABC"})
    add_reference(app, cfg, **art)
    out = add_reference(app, cfg, **{**art, "title": "Two", "fields": {"DOI": "https://doi.org/10.1000/abc"}})
    assert "(same DOI)" in out


def test_allow_duplicate(setup):
    cfg, app = setup
    add_reference(app, cfg, today=TODAY, **REPORT)
    out = add_reference(app, cfg, today=TODAY, allow_duplicate=True, **REPORT)
    assert out.startswith("Added to EndNote as record [2]")


def test_attaches_the_pdf(setup, monkeypatch):
    cfg, app = setup
    _serve(monkeypatch, FakeResponse(PDF_BYTES))
    out = add_reference(app, cfg, today=TODAY, pdf_url="https://example.org/files/report.pdf", **REPORT)
    assert "  PDF: report.pdf (1 KB), attached" in out
    assert "PDF text becomes searchable after the next index run" in out
    folder = next((cfg.endnote_library.parent / "Test.Data" / "PDF").iterdir())
    assert (folder / "report.pdf").read_bytes() == PDF_BYTES
    assert f"internal-pdf://{folder.name}/report.pdf" in app.imports[0]


def test_adds_without_the_pdf_when_it_cannot_be_fetched(setup, monkeypatch):
    cfg, app = setup
    _serve(monkeypatch, error=urllib.error.HTTPError("u", 403, "Forbidden", {}, None))
    out = add_reference(app, cfg, today=TODAY, pdf_url="https://example.org/r.pdf", **REPORT)
    assert out.startswith("Added to EndNote as record [1]")
    assert "PDF: not attached, because the PDF link returned HTTP 403." in out


def test_failed_import_removes_the_downloaded_pdf(setup, monkeypatch):
    cfg, _ = setup
    _serve(monkeypatch, FakeResponse(PDF_BYTES))
    out = add_reference(FakeApp(fail_import=True), cfg, pdf_url="https://example.org/r.pdf", **REPORT)
    assert out == "Not added: EndNote did not respond in time."
    pdf_dir = cfg.endnote_library.parent / "Test.Data" / "PDF"
    assert not pdf_dir.exists() or not any(pdf_dir.iterdir())


def test_bad_request_touches_nothing(setup):
    cfg, app = setup
    out = add_reference(app, cfg, reference_type="Report", title="T", authors=["Scottish Government"])
    assert out.startswith("Not added: Can't tell how to file the name 'Scottish Government'")
    assert app.opened is None and not app.imports


def test_not_indexed_when_the_index_is_another_library(setup):
    cfg, _ = setup
    out = add_reference(FakeApp(db_path="/elsewhere/Other.enl"), cfg, today=TODAY, **REPORT)
    assert out.startswith("Added to EndNote as record [1]")
    assert "Not added to the search index (the search index is built from a different EndNote library)" in out
    assert not Path(cfg.db_path).exists()
