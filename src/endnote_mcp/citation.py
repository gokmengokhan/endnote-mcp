"""Citation formatters for APA 7th, Harvard, Vancouver, Chicago, and IEEE."""

from __future__ import annotations

import json
import re
from typing import Any


STYLES = ("apa7", "harvard", "vancouver", "chicago", "ieee")


def format_citation(ref: dict, style: str = "apa7") -> str:
    """Format a reference dict as a citation string.

    Args:
        ref: Reference dict with authors (list), title, year, journal, etc.
        style: One of 'apa7', 'harvard', 'vancouver', 'chicago', 'ieee'.
    """
    style = style.lower().strip()
    if style not in STYLES:
        raise ValueError(f"Unknown style '{style}'. Choose from: {', '.join(STYLES)}")

    # Ensure authors is a list
    authors = ref.get("authors", [])
    if isinstance(authors, str):
        try:
            authors = json.loads(authors)
        except (json.JSONDecodeError, TypeError):
            authors = [authors] if authors else []

    title = ref.get("title", "")
    year = ref.get("year") or "n.d."
    journal = ref.get("journal", "")
    volume = ref.get("volume", "")
    issue = ref.get("issue", "")
    pages = ref.get("pages", "")
    doi = ref.get("doi", "")
    publisher = ref.get("publisher", "")
    place = ref.get("place_published", "")
    ref_type = ref.get("ref_type", "Journal Article")

    formatter = {
        "apa7": _apa7,
        "harvard": _harvard,
        "vancouver": _vancouver,
        "chicago": _chicago,
        "ieee": _ieee,
    }[style]

    citation = formatter(
        authors=authors,
        title=title,
        year=year,
        journal=journal,
        volume=volume,
        issue=issue,
        pages=pages,
        doi=doi,
        publisher=publisher,
        place=place,
        ref_type=ref_type,
    )
    # A field that already ends in a full stop, question mark or exclamation
    # mark ("J. A.", "et al.", "n.d.", "Inc.", a title that asks a question)
    # takes no second full stop, even across closing italics; ellipses stay
    return re.sub(r"(?<!\.)([.?!])(\*?)\.(?!\.)", r"\1\2", citation)


# ---------- APA 7th Edition ----------

def _apa7(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []
    kind = _source_kind(ref_type, journal)

    # Authors
    if authors:
        # A group author needs this full stop; format_citation drops a doubled one
        parts.append(_apa_authors(authors) + ".")
    else:
        parts.append(title + ".")
        title = ""

    # Year
    parts.append(f"({year}).")

    # Title
    if title:
        if kind in ("article", "chapter", "proceedings"):
            parts.append(f"{title}.")
        elif kind == "presentation":
            parts.append(f"*{title}* [Paper presentation].")
        else:
            parts.append(f"*{title}*.")

    # Source
    if kind == "article" and journal:
        source = f"*{journal}*"
        if volume:
            source += f", *{volume}*"
        if issue:
            source += f"({issue})"
        if pages:
            source += f", {_page_range(pages)}"
        source += "."
        parts.append(source)
    elif kind in ("chapter", "proceedings"):
        source = f"In *{journal}*"
        if pages:
            source += f" (pp. {_page_range(pages)})"
        parts.append(source + ".")
        if publisher:
            parts.append(f"{publisher}.")
    elif kind == "presentation":
        parts.append(f"{journal}, {place}." if place else f"{journal}.")
    elif publisher:
        # APA 7 leaves out the publisher's location
        parts.append(f"{publisher}.")

    # DOI
    if doi:
        doi_clean = doi.strip()
        if not doi_clean.startswith("http"):
            doi_clean = f"https://doi.org/{doi_clean}"
        parts.append(doi_clean)

    return " ".join(parts)


def _page_range(pages: str) -> str:
    """Join a page range with an en dash, as APA requires: '244-253' → '244–253'."""
    return re.sub(r"\s*-+\s*", "–", pages.strip())


def _apa_authors(authors: list[str]) -> str:
    """Format author list for APA 7th."""
    formatted = [_invert_author(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    # APA puts a comma before the ampersand even with two authors
    if len(formatted) <= 20:
        return ", ".join(formatted[:-1]) + ", & " + formatted[-1]
    # 20+ authors: first 19, ..., last
    return ", ".join(formatted[:19]) + ", ... " + formatted[-1]


# ---------- Harvard ----------

def _harvard(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []
    kind = _source_kind(ref_type, journal)

    if authors:
        parts.append(_harvard_authors(authors))
    parts.append(f"({year})")

    if kind == "article":
        parts.append(f"'{title}',")
        if journal:
            source = f"*{journal}*"
            if volume:
                source += f", vol. {volume}"
            if issue:
                source += f", no. {issue}"
            if pages:
                source += f", pp. {pages}"
            source += "."
            parts.append(source)
    elif kind in ("chapter", "proceedings", "presentation"):
        parts.append(f"'{title}',")
        # A chapter is "in" its book; a conference paper names the conference
        source = f"in *{journal}*" if kind == "chapter" else f"*{journal}*"
        if publisher:
            source += f". {place}: {publisher}" if place else f". {publisher}"
        elif place:
            source += f". {place}"
        if pages:
            source += f", pp. {pages}"
        parts.append(source + ".")
    else:
        parts.append(f"*{title}*.")
        if publisher:
            pub = f"{place}: {publisher}." if place else f"{publisher}."
            parts.append(pub)

    if doi:
        doi_clean = doi.strip()
        if not doi_clean.startswith("http"):
            doi_clean = f"https://doi.org/{doi_clean}"
        parts.append(doi_clean)

    return " ".join(parts)


def _harvard_authors(authors: list[str]) -> str:
    formatted = [_invert_author(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    if len(formatted) <= 3:
        return ", ".join(formatted[:-1]) + " and " + formatted[-1]
    return f"{formatted[0]} et al."


# ---------- Vancouver ----------

def _vancouver(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []
    kind = _source_kind(ref_type, journal)

    if authors:
        parts.append(_vancouver_authors(authors) + ".")

    parts.append(f"{title}.")

    if kind == "article" and journal:
        source = f"{journal}. {year}"
        if volume:
            source += f";{volume}"
        if issue:
            source += f"({issue})"
        if pages:
            source += f":{pages}"
        source += "."
        parts.append(source)
    elif kind in ("chapter", "proceedings"):
        if publisher:
            pub = f"{place}: {publisher}" if place else publisher
            source = f"In: {journal}. {pub}; {year}."
        else:
            source = f"In: {journal}; {year}."
        if pages:
            source += f" p. {pages}."
        parts.append(source)
    elif kind == "presentation":
        parts.append(f"Paper presented at: {journal}; {year}" + (f"; {place}." if place else "."))
    else:
        if place and publisher:
            parts.append(f"{place}: {publisher}; {year}.")
        elif publisher:
            parts.append(f"{publisher}; {year}.")
        else:
            parts.append(f"{year}.")

    return " ".join(parts)


def _vancouver_authors(authors: list[str]) -> str:
    formatted = [_vancouver_author_name(a) for a in authors]
    if len(formatted) <= 6:
        return ", ".join(formatted)
    return ", ".join(formatted[:6]) + ", et al"


def _vancouver_author_name(name: str) -> str:
    """Convert 'Smith, John A.' → 'Smith JA'."""
    surname, given, suffix = _split_name(name)
    initials = "".join(ch for ch in _initials(given) if ch.isalpha())
    vancouver = f"{surname} {initials}" if initials else surname
    return f"{vancouver} {suffix.rstrip('.')}" if suffix else vancouver


# ---------- Chicago (Author-Date, 17th ed.) ----------

def _chicago(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []
    kind = _source_kind(ref_type, journal)

    if authors:
        parts.append(_chicago_authors(authors) + ".")

    parts.append(f"{year}.")

    if kind == "article":
        parts.append(f'"{title}."')
        if journal:
            source = f"*{journal}*"
            if volume:
                source += f" {volume}"
            if issue:
                source += f", no. {issue}"
            if pages:
                source += f": {_page_range(pages)}"
            source += "."
            parts.append(source)
    elif kind in ("chapter", "proceedings"):
        parts.append(f'"{title}."')
        source = f"In *{journal}*"
        if pages:
            source += f", {_page_range(pages)}"
        parts.append(source + ".")
        if place and publisher:
            parts.append(f"{place}: {publisher}.")
        elif publisher:
            parts.append(f"{publisher}.")
    elif kind == "presentation":
        parts.append(f'"{title}."')
        parts.append(f"Paper presented at {journal}, {place}." if place else f"Paper presented at {journal}.")
    else:
        parts.append(f"*{title}*.")
        if place and publisher:
            parts.append(f"{place}: {publisher}.")
        elif publisher:
            parts.append(f"{publisher}.")

    if doi:
        doi_clean = doi.strip()
        if not doi_clean.startswith("http"):
            doi_clean = f"https://doi.org/{doi_clean}"
        parts.append(doi_clean)

    return " ".join(parts)


def _chicago_authors(authors: list[str]) -> str:
    first = _full_name(authors[0], inverted=True)
    if len(authors) == 1:
        return first
    if len(authors) == 2:
        return f"{first} and {_direct_order(authors[1])}"
    if len(authors) <= 3:
        middle = ", ".join(_direct_order(a) for a in authors[1:-1])
        return f"{first}, {middle}, and {_direct_order(authors[-1])}"
    return f"{first} et al."


# ---------- IEEE ----------

def _ieee(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []
    kind = _source_kind(ref_type, journal)

    if authors:
        parts.append(_ieee_authors(authors) + ",")

    parts.append(f'"{title},"')

    if kind == "article" and journal:
        source = f"*{journal}*"
        if volume:
            source += f", vol. {volume}"
        if issue:
            source += f", no. {issue}"
        if pages:
            source += f", pp. {_page_range(pages)}"
        source += f", {year}."
        parts.append(source)
    elif kind == "chapter":
        source = f"in *{journal}*."
        if publisher:
            source += f" {place}: {publisher}," if place else f" {publisher},"
        source += f" {year}"
        if pages:
            source += f", pp. {_page_range(pages)}"
        parts.append(source + ".")
    elif kind == "proceedings":
        source = f"in *{journal}*"
        if place:
            source += f", {place}"
        source += f", {year}"
        if pages:
            source += f", pp. {_page_range(pages)}"
        parts.append(source + ".")
    elif kind == "presentation":
        parts.append(f"presented at {journal}, {place}, {year}." if place else f"presented at {journal}, {year}.")
    else:
        if publisher:
            parts.append(f"{place}: {publisher}, {year}." if place else f"{publisher}, {year}.")
        else:
            parts.append(f"{year}.")

    if doi:
        doi_clean = doi.strip()
        if not doi_clean.startswith("http"):
            doi_clean = f"doi: {doi_clean}"
        parts.append(doi_clean)

    return " ".join(parts)


def _ieee_authors(authors: list[str]) -> str:
    formatted = [_direct_order_initials(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + ", and " + formatted[-1]


def _direct_order_initials(name: str) -> str:
    """Convert 'Smith, John A.' → 'J. A. Smith'."""
    surname, given, suffix = _split_name(name)
    initials = _initials(given)
    direct = f"{initials} {surname}" if initials else surname
    return f"{direct}, {suffix}" if suffix else direct


# ---------- Helpers ----------

# Suffixes EndNote keeps after the given names ("Smith, John, Jr.")
_NAME_SUFFIX = re.compile(r"^(Jr|Sr|II|III|IV)\.?$", re.IGNORECASE)


def _split_name(name: str) -> tuple[str, str, str]:
    """Split an author into (surname, given names, suffix), reading it as EndNote does.

    EndNote exports people as "Surname, Given names" and corporate authors
    with a trailing comma ("World Health Organization,"), writing a comma
    inside a corporate name as ",,". A name without a comma is a person in
    direct order ("John A. Smith"). A corporate author, or several people
    typed into one field, comes back whole as the surname.
    """
    name = name.strip()
    if ",," in name:
        return name.replace(",,", ",").rstrip(", "), "", ""
    if "," not in name:
        words = name.split()
        if len(words) < 2:
            return name, "", ""
        return words[-1], " ".join(words[:-1]), ""
    surname, *rest = (p.strip() for p in name.split(","))
    rest = [p for p in rest if p]
    if len(rest) > 2:  # several people in one field; leave it as entered
        return name.rstrip(", "), "", ""
    suffix = rest.pop() if len(rest) == 2 and _NAME_SUFFIX.match(rest[1]) else ""
    return surname, " ".join(rest), suffix


def _invert_author(name: str) -> str:
    """Format an author as 'Surname, I. I.' for APA/Harvard."""
    surname, given, suffix = _split_name(name)
    initials = _initials(given)
    inverted = f"{surname}, {initials}" if initials else surname
    return f"{inverted}, {suffix}" if suffix else inverted


def _initials(given: str) -> str:
    """Reduce given names to initials: 'Paul J.H.' → 'P. J. H.', 'Jean-Paul' → 'J.-P.'."""
    words = given.split()
    # Lowercase words are particles ("van") or debris from imported records
    # ("author", e-mail fragments); skip them unless that leaves nothing.
    words = [w for w in words if not w[0].islower()] or words
    initials = []
    for word in words:
        hyphenated = []
        for part in word.split("-"):
            letters = []
            for piece in filter(None, part.split(".")):
                if piece.isupper() and piece.isalpha() and len(piece) <= 3:
                    letters.extend(piece)  # "JA" is two initials, not a name
                else:
                    first = next((ch for ch in piece if ch.isalpha()), "")
                    if first:
                        letters.append(first.upper())
            if letters:
                hyphenated.append(" ".join(f"{ch}." for ch in letters))
        if hyphenated:
            initials.append("-".join(hyphenated))
    return " ".join(initials)


def _full_name(name: str, *, inverted: bool) -> str:
    """Spell out a name as 'Smith, John A.' (inverted) or 'John A. Smith'."""
    surname, given, suffix = _split_name(name)
    if not given:
        return surname
    full = f"{surname}, {given}" if inverted else f"{given} {surname}"
    return f"{full}, {suffix}" if suffix else full


def _direct_order(name: str) -> str:
    """Convert 'Smith, John' → 'John Smith'."""
    return _full_name(name, inverted=False)


def _is_article(ref_type: str) -> bool:
    """Check if the reference type is a journal/periodical article."""
    rt = ref_type.lower()
    return any(kw in rt for kw in ("journal", "article", "magazine", "periodical"))


def _source_kind(ref_type: str, container: str) -> str:
    """Say where a reference appeared: article, chapter, proceedings, presentation or book.

    EndNote keeps a journal's name, the book a section appears in and the
    conference a paper was given at in the same field, which the parser
    calls `journal`; without it a chapter or paper is cited like a book.
    """
    if _is_article(ref_type):
        return "article"
    rt = ref_type.lower()
    if container and "conference paper" in rt:
        return "presentation"
    if container and "conference" in rt:
        return "proceedings"
    if container and "section" in rt:
        return "chapter"
    return "book"


# ---------- BibTeX ----------

def format_bibtex(ref: dict) -> str:
    """Format a reference dict as a BibTeX entry.

    Args:
        ref: Reference dict with authors (list), title, year, journal, etc.

    Returns:
        A complete BibTeX entry string.
    """
    authors = ref.get("authors", [])
    if isinstance(authors, str):
        try:
            authors = json.loads(authors)
        except (json.JSONDecodeError, TypeError):
            authors = [authors] if authors else []

    title = ref.get("title", "")
    year = ref.get("year", "")
    journal = ref.get("journal", "")
    volume = ref.get("volume", "")
    issue = ref.get("issue", "")
    pages = ref.get("pages", "")
    doi = ref.get("doi", "")
    publisher = ref.get("publisher", "")
    place = ref.get("place_published", "")
    isbn = ref.get("isbn", "")
    ref_type = ref.get("ref_type", "Journal Article")
    rec_number = ref.get("rec_number", 0)

    # Determine BibTeX entry type
    entry_type = _bibtex_entry_type(ref_type)

    # Build cite key: first author surname + year + rec_number
    cite_key = _bibtex_cite_key(authors, year, rec_number)

    # Format authors for BibTeX: "Surname, Given and Surname, Given"
    bib_authors = " and ".join(authors) if authors else ""

    # Build fields
    fields: list[tuple[str, str]] = []
    if bib_authors:
        fields.append(("author", bib_authors))
    if title:
        fields.append(("title", f"{{{title}}}"))
    if year:
        fields.append(("year", year))
    if journal and _is_article(ref_type):
        fields.append(("journal", journal))
    if volume:
        fields.append(("volume", volume))
    if issue:
        fields.append(("number", issue))
    if pages:
        fields.append(("pages", pages.replace("-", "--")))
    if publisher:
        fields.append(("publisher", publisher))
    if place:
        fields.append(("address", place))
    if doi:
        doi_clean = doi.strip()
        if doi_clean.startswith("https://doi.org/"):
            doi_clean = doi_clean[len("https://doi.org/"):]
        elif doi_clean.startswith("http://doi.org/"):
            doi_clean = doi_clean[len("http://doi.org/"):]
        fields.append(("doi", doi_clean))
    if isbn:
        fields.append(("isbn", isbn))

    # Keywords
    keywords = ref.get("keywords", [])
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except (json.JSONDecodeError, TypeError):
            keywords = []
    if keywords:
        fields.append(("keywords", ", ".join(keywords)))

    # Build the entry
    lines = [f"@{entry_type}{{{cite_key},"]
    for key, val in fields:
        lines.append(f"  {key} = {{{val}}},")
    lines.append("}")

    return "\n".join(lines)


def _bibtex_entry_type(ref_type: str) -> str:
    """Map EndNote reference type to BibTeX entry type."""
    rt = ref_type.lower()
    if _is_article(rt):
        return "article"
    if "book section" in rt or "chapter" in rt:
        return "incollection"
    if "book" in rt:
        return "book"
    if "conference" in rt or "proceeding" in rt:
        return "inproceedings"
    if "thesis" in rt or "dissertation" in rt:
        return "phdthesis"
    if "report" in rt:
        return "techreport"
    if "patent" in rt:
        return "misc"
    if "web" in rt or "electronic" in rt:
        return "misc"
    return "misc"


def _bibtex_cite_key(authors: list[str], year: str, rec_number: int) -> str:
    """Generate a BibTeX cite key like 'smith2020r42'."""
    if authors:
        first = authors[0].split(",")[0].strip()
        # Remove non-alphanumeric chars
        first = re.sub(r"[^a-zA-Z]", "", first).lower()
    else:
        first = "unknown"
    return f"{first}{year}r{rec_number}"
