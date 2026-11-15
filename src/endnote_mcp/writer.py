"""Add a reference to the user's EndNote library (macOS, opt-in).

The record is built as EndNote XML, imported through the EndNote app, read
back and compared field by field, then put in the search index so it can be
cited at once. endnote_app.py talks to EndNote; this module decides what to
write and checks what EndNote kept.
"""

from __future__ import annotations

import datetime as dt
import random
import re
import shutil
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from endnote_mcp.endnote_app import EndNoteApp, EndNoteError, parse_record_id
from endnote_mcp.reftypes import GENERIC_XML, LIST_FIELDS, NAME_FIELDS, REF_TYPES

LABEL = "Added by Claude"
MAX_PDF_BYTES = 200 * 1024 * 1024  # the indexer skips bigger PDFs
PDF_PATH = "urls/pdf-urls/url"

# Generic fields the tool fills from its own parameters (or itself), so the
# `fields` argument may not set them.
_RESERVED = {"Author": "authors", "Title": "title", "Year": "year", "URL": "url", "Label": None}

# Types whose URL is usually where the source was read: Access Date gets
# today's date unless one is given.
_ACCESS_DATE_TYPES = {"Report", "Web Page"}

# Free-text fields that keep their line breaks.
_MULTILINE = {"Abstract", "Notes", "Research Notes"}

# The order EndNote writes paths in; built XML follows it.
_ORDER = [*GENERIC_XML.values(), PDF_PATH]
_KNOWN_PATHS = {"ref-type", *_ORDER}
_NAME_PATHS = {GENERIC_XML[g] for g in NAME_FIELDS}

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class AddReferenceError(ValueError):
    """The reference can't be added as asked; the message says why."""


# ---------------------------------------------------------------- values

def _clean(value: object, multiline: bool = False) -> str:
    text = unicodedata.normalize("NFC", _CONTROL.sub("", str(value)))
    if multiline:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return "\n".join(" ".join(line.split()) for line in lines).strip()
    return " ".join(text.split())


def access_date(day: dt.date) -> str:
    """'11 November 2026': day first and the month in words, in any locale."""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def endnote_name(entry: str) -> str:
    """A name as EndNote stores it.

    People are "Last, First" (a suffix may follow: "King, Martin Luther, Jr.").
    Organisations come in braces, "{Scottish Government}". EndNote keeps an
    organisation whole when it ends in a comma, or, if it contains a comma,
    when that comma is doubled: "Scottish Government,", "Becton,, Dickinson
    and Company". Using both leaves a stray comma in formatted references.
    """
    s = _clean(entry)
    if s.startswith("{") and s.endswith("}"):
        org = re.sub(r",{2,}", ",", s[1:-1]).strip(" ,")
        if not org or "{" in org or "}" in org:
            raise AddReferenceError(f"Can't read the organisation name {entry!r}.")
        return org.replace(",", ",,") if "," in org else org + ","
    parts = [p.strip() for p in s.split(",")]
    if "{" not in s and "}" not in s and len(parts) in (2, 3) and all(parts):
        return ", ".join(parts)
    raise AddReferenceError(
        f"Can't tell how to file the name {entry!r}. Write a person as 'Last, First' "
        "(e.g. 'Öztürk, İsmail Çağrı') and an organisation, or anyone known by one "
        "name, in braces (e.g. '{Scottish Government}')."
    )


def display_name(stored: str) -> str:
    """How a stored name reads: organisations lose EndNote's extra commas."""
    if ",," in stored:
        return stored.replace(",,", ",") + " (organisation)"
    if stored.endswith(","):
        return stored[:-1] + " (organisation)"
    return stored


def _bare_doi(doi: str) -> str:
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi.strip(), flags=re.I)


def _check_web_address(url: str, what: str) -> None:
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise AddReferenceError(f"{what} must be a web address starting with http:// or https://, not {url!r}.")


# ---------------------------------------------------------------- the record

@dataclass
class Draft:
    """What will be written: XML path -> values, for one reference type."""

    ref_type: str
    values: dict[str, list[str]]

    def first(self, generic: str) -> str:
        return (self.values.get(GENERIC_XML[generic]) or [""])[0]


def _type_named(name: str) -> str:
    key = " ".join(str(name).split()).casefold()
    for ref_type in REF_TYPES:
        if ref_type.casefold() == key:
            return ref_type
    raise AddReferenceError(f"Can't add a {name!r}. Reference types: {', '.join(REF_TYPES)}.")


def _label_named(ref_type: str, key: str) -> str:
    labels = REF_TYPES[ref_type][1]
    wanted = " ".join(str(key).split()).casefold()
    for label in labels:
        if label.casefold() == wanted:
            return label
    usable = ", ".join(lab for lab, gen in labels.items() if gen not in _RESERVED)
    raise AddReferenceError(f"A {ref_type} has no field {key!r}. Its fields: {usable}.")


def draft_record(
    reference_type: str,
    title: str,
    authors: list[str] | None = None,
    year: str = "",
    url: str = "",
    fields: dict | None = None,
    today: dt.date | None = None,
) -> Draft:
    """Check the request and map it onto EndNote's fields for its type."""
    ref_type = _type_named(reference_type)
    labels = REF_TYPES[ref_type][1]
    values: dict[str, list[str]] = {}

    def put(generic: str, items: list[str]) -> None:
        values.setdefault(GENERIC_XML[generic], []).extend(items)

    title = _clean(title)
    if not title:
        raise AddReferenceError("A title is needed.")
    put("Title", [title])
    names = [endnote_name(a) for a in authors or [] if _clean(a)]
    if names:
        put("Author", names)
    year = _clean(year)
    if year:
        if not re.fullmatch(r"\d{4}|in press|forthcoming", year, flags=re.I):
            raise AddReferenceError(
                f"Year takes a four-digit year, not {year!r}; a full date goes in the 'Date' field."
            )
        put("Year", [year])
    url = _clean(url)
    if url:
        _check_web_address(url, "url")
        put("URL", [url])

    seen: set[str] = set()
    for key, raw in (fields or {}).items():
        label = _label_named(ref_type, key)
        generic = labels[label]
        if label in seen:
            raise AddReferenceError(f"{label} is given twice.")
        seen.add(label)
        if generic in _RESERVED:
            param = _RESERVED[generic]
            raise AddReferenceError(
                f"{label} is set by the {param} parameter." if param
                else f"{label} is set automatically, to {LABEL!r}."
            )
        items = raw if isinstance(raw, (list, tuple)) else [raw]
        if generic in NAME_FIELDS:
            vals = [endnote_name(x) for x in items if _clean(x)]
        elif generic in LIST_FIELDS:
            vals = [v for v in (_clean(x) for x in items) if v]
        elif len(items) != 1:
            raise AddReferenceError(f"{label} takes one value, not a list.")
        else:
            vals = [v for v in [_clean(items[0], multiline=generic in _MULTILINE)] if v]
        if generic == "DOI":
            vals = [_bare_doi(v) for v in vals]
        if vals:
            put(generic, vals)

    if url and ref_type in _ACCESS_DATE_TYPES and "Access Date" not in seen:
        put(labels["Access Date"], [access_date(today or dt.date.today())])
    put("Label", [LABEL])
    return Draft(ref_type, values)


def record_xml(draft: Draft, pdf_link: str = "") -> str:
    """The draft as EndNote XML, the form `import` reads."""
    values = dict(draft.values)
    if pdf_link:
        values[PDF_PATH] = [pdf_link]
    rec = ET.Element("record")
    ET.SubElement(rec, "ref-type", name=draft.ref_type).text = str(REF_TYPES[draft.ref_type][0])
    for path in _ORDER:
        for value in values.get(path, ()):
            *parents, leaf = path.split("/")
            node = rec
            for tag in parents:
                child = node.find(tag)
                node = child if child is not None else ET.SubElement(node, tag)
            ET.SubElement(node, leaf).text = value
    return (
        '<?xml version="1.0" encoding="UTF-8" ?><xml><records>'
        + ET.tostring(rec, encoding="unicode")
        + "</records></xml>"
    )


def record_fields(record: ET.Element) -> list[tuple[str, str]]:
    """(path, text) for each field of a <record>, minus what EndNote assigns."""
    out: list[tuple[str, str]] = []

    def walk(node: ET.Element, prefix: str) -> None:
        for child in node:
            if child.tag == "style":
                continue
            path = f"{prefix}/{child.tag}" if prefix else child.tag
            if path == "ref-type":
                out.append((path, f"{child.get('name')}/{(child.text or '').strip()}"))
            elif any(c.tag != "style" for c in child):
                walk(child, path)
            elif path in _KNOWN_PATHS:
                text = "".join(child.itertext())
                out.append((path, text.replace("\r\n", "\n").replace("\r", "\n").strip()))

    walk(record, "")
    return out


def differences(sent: list[tuple[str, str]], back: list[tuple[str, str]]):
    """[(path, sent values, stored values)] wherever EndNote kept something else."""
    s, b = Counter(sent), Counter(back)
    paths: list[str] = []
    for path, _ in [*(s - b).elements(), *(b - s).elements()]:
        if path not in paths:
            paths.append(path)
    return [
        (p, [v for q, v in sent if q == p], [v for q, v in back if q == p]) for p in paths
    ]


def _labels_by_path(ref_type: str) -> dict[str, str]:
    by_path = {GENERIC_XML[gen]: lab for lab, gen in REF_TYPES[ref_type][1].items()}
    by_path[PDF_PATH] = "File Attachments"
    by_path["ref-type"] = "Reference Type"
    return by_path


# ---------------------------------------------------------------- library

def library_path(cfg) -> Path:
    """The library to write to: endnote_library, or the one pdf_dir sits in."""
    if cfg.endnote_library:
        return Path(cfg.endnote_library)
    data = Path(cfg.pdf_dir).parent  # ".../<name>.Data"
    if data.name.endswith(".Data"):
        if data.parent.suffix == ".enlp":
            return data.parent
        enl = data.parent / (data.name[: -len(".Data")] + ".enl")
        if enl.exists():
            return enl
    raise AddReferenceError(
        "Can't tell which EndNote library to add to. Set endnote_library in "
        "config.yaml to the library file (.enl or .enlp)."
    )


def library_pdf_dir(library: Path) -> Path:
    """Where EndNote keeps the library's attachments."""
    base = library if library.suffix == ".enlp" else library.parent
    return base / f"{library.stem}.Data" / "PDF"


def _first_database_path(xml_path: Path) -> str | None:
    """The library an EndNote XML export came from, read off its first record."""
    from lxml import etree

    try:
        for _event, el in etree.iterparse(str(xml_path), events=("end",), tag="database"):
            return el.get("path")
    except (OSError, etree.XMLSyntaxError):
        return None
    return None


# ---------------------------------------------------------------- duplicates

def _norm_url(url: str) -> str:
    p = urllib.parse.urlsplit(url.strip())
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + urllib.parse.unquote(p.path).rstrip("/") + (f"?{p.query}" if p.query else "")


def _norm_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def _title_probe(title: str) -> str:
    """The longest stretch of the title without punctuation.

    `find` matches text literally, and the library's copy of a title may use
    other quotes or dashes; such a stretch still matches.
    """
    runs = [r.strip() for r in re.split(r"[^\w\s]+", title) if r.strip()]
    return max(runs, key=len) if runs else title


@dataclass
class Match:
    rec_number: int
    why: str
    summary: str


def _summary(rec: ET.Element) -> str:
    def text(path: str) -> str:
        el = rec.find(path)
        return "".join(el.itertext()).strip() if el is not None else ""

    authors = ["".join(a.itertext()).strip() for a in rec.findall("contributors/authors/author")]
    who = display_name(authors[0]).replace(" (organisation)", "") if authors else "No author"
    if len(authors) > 1:
        who += " et al."
    year = text("dates/year") or "n.d."
    return f"{who} ({year}). {text('titles/title')}"


def find_duplicates(app: EndNoteApp, database: int, draft: Draft) -> list[Match]:
    """Records in the library with the same DOI, URL, or title and year."""
    title, url, doi, year = (draft.first(g) for g in ("Title", "URL", "DOI", "Year"))
    probes = [(doi, "DOI")] if doi else []
    if url:
        probes.append((_norm_url(url), "URL"))
    probes.append((_title_probe(title), "Title"))

    ids: list[str] = []
    for text, generic in probes:
        for rid in app.find(text, generic):
            try:
                in_library = parse_record_id(rid)[0] == database
            except EndNoteError:
                continue
            if in_library and rid not in ids:
                ids.append(rid)
    if not ids:
        return []

    matches = []
    root = ET.fromstring(app.export(ids[:50]).encode("utf-8"))
    for rec in root.iter("record"):
        fields = dict(record_fields(rec))
        why = []
        if doi and _bare_doi(fields.get(GENERIC_XML["DOI"], "")).lower() == doi.lower():
            why.append("same DOI")
        their_url = fields.get(GENERIC_XML["URL"], "")
        if url and their_url and _norm_url(their_url) == _norm_url(url):
            why.append("same URL")
        their_year = fields.get(GENERIC_XML["Year"], "")
        if _norm_title(fields.get(GENERIC_XML["Title"], "")) == _norm_title(title) and (
            not year or not their_year or their_year == year
        ):
            why.append("same title" + (" and year" if year and their_year else ""))
        if why:
            number = int(rec.findtext("rec-number") or 0)
            matches.append(Match(number, ", ".join(why), _summary(rec)))
    return matches


# ---------------------------------------------------------------- PDF

@dataclass
class Attachment:
    link: str  # internal-pdf://<folder>/<name>
    path: Path
    size: int


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _pdf_name(url: str, disposition: str, title: str) -> str:
    name = ""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition, flags=re.I)
    if m:
        name = urllib.parse.unquote(m.group(1))
    if not name.lower().endswith(".pdf"):
        tail = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
        name = tail if tail.lower().endswith(".pdf") else f"{title}.pdf"
    name = unicodedata.normalize("NFC", name)
    stem = re.sub(r'[\x00-\x1f/\\:*?"<>|%#]+', "-", name[:-4])
    stem = " ".join(stem.split()).strip(" .-") or "document"
    while len(stem.encode("utf-8")) > 180:
        stem = stem[:-1]
    return stem + ".pdf"


def download_pdf(url: str, pdf_dir: Path, title: str, timeout: float = 60) -> Attachment:
    """Fetch a PDF into a new folder in the library's PDF folder, the way EndNote stores one."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        agent = f"endnote-mcp/{version('endnote-mcp')}"
    except PackageNotFoundError:
        agent = "endnote-mcp"
    request = urllib.request.Request(url, headers={
        "User-Agent": f"{agent} (+https://github.com/gokmengokhan/endnote-mcp)",
        "Accept": "application/pdf,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
            data = resp.read(MAX_PDF_BYTES + 1)
            final_url = resp.geturl()
            disposition = resp.headers.get("Content-Disposition", "")
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise AddReferenceError(f"the PDF link returned HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise AddReferenceError(f"the PDF could not be downloaded ({getattr(e, 'reason', e)})") from None
    if len(data) > MAX_PDF_BYTES:
        raise AddReferenceError("the PDF is larger than 200 MB")
    if b"%PDF-" not in data[:1024]:
        raise AddReferenceError(
            f"the link returned {content_type or 'something'} rather than a PDF; "
            "pdf_url needs the direct link to the PDF file"
        )
    name = _pdf_name(final_url, disposition, title)
    rng = random.SystemRandom()
    for _ in range(100):
        folder = str(rng.randint(1_000_000_000, 4_294_967_295))
        if not (pdf_dir / folder).exists():
            break
    target = pdf_dir / folder
    target.mkdir(parents=True)
    path = target / name
    path.write_bytes(data)
    return Attachment(f"internal-pdf://{folder}/{name}", path, len(data))


# ---------------------------------------------------------------- index

def _index(cfg, library_xml_path: str | None, exported: str, rec_number: int) -> str:
    """Put the new record in the search index; '' on success, else the reason it wasn't."""
    from endnote_mcp.db import connect, upsert_reference
    from endnote_mcp.endnote_parser import parse_endnote_xml_string

    indexed_from = _first_database_path(Path(cfg.endnote_xml))
    if indexed_from and library_xml_path and indexed_from != library_xml_path:
        return "the search index is built from a different EndNote library"
    refs = [r for r in parse_endnote_xml_string(exported) if r["rec_number"] == rec_number]
    if not refs:
        return "the record could not be read for indexing"
    conn = connect(cfg.db_path)
    try:
        upsert_reference(conn, refs[0])
        conn.commit()
    finally:
        conn.close()
    return ""


# ---------------------------------------------------------------- the tool

def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


def add_reference(
    app: EndNoteApp,
    cfg,
    *,
    reference_type: str,
    title: str,
    authors: list[str] | None = None,
    year: str = "",
    url: str = "",
    fields: dict | None = None,
    pdf_url: str = "",
    allow_duplicate: bool = False,
    today: dt.date | None = None,
) -> str:
    """Add one reference and report what EndNote stored. Never raises for the user's input."""
    try:
        draft = draft_record(reference_type, title, authors, year, url, fields, today)
        pdf_url = _clean(pdf_url)
        if pdf_url:
            _check_web_address(pdf_url, "pdf_url")
        library = library_path(cfg)
        app.open_library(library)
        before = app.record_ids(library.name)
        if before and not allow_duplicate:
            matches = find_duplicates(app, parse_record_id(before[0])[0], draft)
            if matches:
                lines = ["Not added: the library already has this source."]
                lines += [f"  [{m.rec_number}] {m.summary} ({m.why})" for m in matches]
                lines.append(
                    "Cite the existing record, or call add_reference again with "
                    "allow_duplicate=true to add another copy."
                )
                return "\n".join(lines)
    except (AddReferenceError, EndNoteError) as e:
        return f"Not added: {e}"

    attachment, pdf_problem = None, ""
    if pdf_url:
        try:
            attachment = download_pdf(pdf_url, library_pdf_dir(library), draft.first("Title"))
        except (AddReferenceError, OSError) as e:
            pdf_problem = str(e)

    xml = record_xml(draft, attachment.link if attachment else "")
    try:
        app.import_xml(xml, library.name)
        known = set(before)
        new = [rid for rid in app.record_ids(library.name) if rid not in known]
        if not new:
            raise EndNoteError(f"EndNote accepted the record, but no new record appeared in {library.name}.")
        exported = app.export(new)
    except EndNoteError as e:
        if attachment:
            shutil.rmtree(attachment.path.parent, ignore_errors=True)
        return f"Not added: {e}"

    # Normally one new record; if a sync added others at the same moment, take ours.
    sent = record_fields(ET.fromstring(xml.encode("utf-8")).find("records/record"))
    candidates = list(ET.fromstring(exported.encode("utf-8")).iter("record"))
    if not candidates:
        numbers = ", ".join(f"[{parse_record_id(r)[1]}]" for r in new)
        return (
            f"Added to EndNote as record {numbers} in {library.name}, but EndNote did not "
            "return it to be checked. Look it over in EndNote under Recently Added."
        )
    ours = min(candidates, key=lambda r: len(differences(sent, record_fields(r))))
    back = record_fields(ours)
    rec_number = int(ours.findtext("rec-number") or 0)
    rid = next((r for r in new if parse_record_id(r)[1] == rec_number), new[0])
    database = ours.find("database")
    diffs = differences(sent, back)

    by_path = _labels_by_path(draft.ref_type)
    lines = [f"Added to EndNote as record [{rec_number}], a {draft.ref_type} in {library.name}."]
    stored: dict[str, list[str]] = {}
    for path, value in back:
        stored.setdefault(path, []).append(display_name(value) if path in _NAME_PATHS else value)
    for label, generic in REF_TYPES[draft.ref_type][1].items():  # EndNote's own order
        path = GENERIC_XML[generic]
        if path in stored:
            lines.append(f"  {label}: {'; '.join(stored[path])}")
    if attachment:
        lines.append(f"  PDF: {attachment.path.name} ({_size(attachment.size)}), attached")
    elif pdf_problem:
        lines.append(f"  PDF: not attached, because {pdf_problem}. The record was added without it.")

    if not diffs:
        n_fields = len({path for path, _ in sent if path != "ref-type"})
        lines.append(f"Read back from EndNote: all {n_fields} fields stored exactly as sent.")
    else:
        lines.append(f"Read back from EndNote: {len(diffs)} field(s) differ from what was sent; check them in EndNote:")
        for path, was, now in diffs:
            lines.append(
                f"  {by_path.get(path, path)}: sent {'; '.join(was) or '(nothing)'}, "
                f"stored {'; '.join(now) or '(nothing)'}"
            )

    try:
        lines.append(f"Temporary citation for Word: {app.temporary_citation(rid)}")
    except EndNoteError:
        pass

    try:
        problem = _index(cfg, database.get("path") if database is not None else None, exported, rec_number)
    except Exception as e:  # the record is in EndNote either way
        problem = str(e)
    if problem:
        lines.append(
            f"Not added to the search index ({problem}); it will be there after "
            "the next XML export and index run."
        )
    else:
        lines.append(
            f"Cite it here as [{rec_number}]. In EndNote it is under Recently Added"
            + (", and its PDF text becomes searchable after the next index run." if attachment else ".")
        )
    return "\n".join(lines)
