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
    year = ref.get("year", "n.d.")
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

    return formatter(
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


# ---------- APA 7th Edition ----------

def _apa7(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []

    # Authors
    if authors:
        parts.append(_apa_authors(authors))
    else:
        parts.append(title + ".")
        title = ""

    # Year
    parts.append(f"({year}).")

    # Title
    if title:
        if _is_article(ref_type):
            parts.append(f"{title}.")
        else:
            parts.append(f"*{title}*.")

    # Source
    if _is_article(ref_type) and journal:
        source = f"*{journal}*"
        if volume:
            source += f", *{volume}*"
        if issue:
            source += f"({issue})"
        if pages:
            source += f", {pages}"
        source += "."
        parts.append(source)
    elif publisher:
        if place:
            parts.append(f"{place}: {publisher}.")
        else:
            parts.append(f"{publisher}.")

    # DOI
    if doi:
        doi_clean = doi.strip()
        if not doi_clean.startswith("http"):
            doi_clean = f"https://doi.org/{doi_clean}"
        parts.append(doi_clean)

    return " ".join(parts)


def _apa_authors(authors: list[str]) -> str:
    """Format author list for APA 7th."""
    formatted = [_invert_author(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} & {formatted[1]}"
    if len(formatted) <= 20:
        return ", ".join(formatted[:-1]) + ", & " + formatted[-1]
    # 20+ authors: first 19, ..., last
    return ", ".join(formatted[:19]) + ", ... " + formatted[-1]


# ---------- Harvard ----------

def _harvard(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []

    if authors:
        parts.append(_harvard_authors(authors))
    parts.append(f"({year})")

    if _is_article(ref_type):
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

    if authors:
        parts.append(_vancouver_authors(authors) + ".")

    parts.append(f"{title}.")

    if _is_article(ref_type) and journal:
        source = f"{journal}. {year}"
        if volume:
            source += f";{volume}"
        if issue:
            source += f"({issue})"
        if pages:
            source += f":{pages}"
        source += "."
        parts.append(source)
    else:
        if place and publisher:
            parts.append(f"{place}: {publisher}; {year}.")
        elif publisher:
            parts.append(f"{publisher}; {year}.")

    return " ".join(parts)


def _vancouver_authors(authors: list[str]) -> str:
    formatted = [_vancouver_author_name(a) for a in authors]
    if len(formatted) <= 6:
        return ", ".join(formatted)
    return ", ".join(formatted[:6]) + ", et al"


def _vancouver_author_name(name: str) -> str:
    """Convert 'Smith, John A.' → 'Smith JA'."""
    parts = name.split(",", 1)
    if len(parts) == 1:
        return name.strip()
    surname = parts[0].strip()
    given = parts[1].strip()
    initials = "".join(w[0].upper() for w in given.split() if w)
    return f"{surname} {initials}"


# ---------- Chicago (Author-Date, 17th ed.) ----------

def _chicago(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []

    if authors:
        parts.append(_chicago_authors(authors) + ".")

    parts.append(f"{year}.")

    if _is_article(ref_type):
        parts.append(f'"{title}."')
        if journal:
            source = f"*{journal}*"
            if volume:
                source += f" {volume}"
            if issue:
                source += f", no. {issue}"
            if pages:
                source += f": {pages}"
            source += "."
            parts.append(source)
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
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {_direct_order(authors[1])}"
    if len(authors) <= 3:
        middle = ", ".join(_direct_order(a) for a in authors[1:-1])
        return f"{authors[0]}, {middle}, and {_direct_order(authors[-1])}"
    return f"{authors[0]} et al."


# ---------- IEEE ----------

def _ieee(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type):
    parts = []

    if authors:
        parts.append(_ieee_authors(authors) + ",")

    parts.append(f'"{title},"')

    if _is_article(ref_type) and journal:
        source = f"*{journal}*"
        if volume:
            source += f", vol. {volume}"
        if issue:
            source += f", no. {issue}"
        if pages:
            source += f", pp. {pages}"
        source += f", {year}."
        parts.append(source)
    else:
        if publisher:
            parts.append(f"{place}: {publisher}, {year}." if place else f"{publisher}, {year}.")

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
    parts = name.split(",", 1)
    if len(parts) == 1:
        return name.strip()
    surname = parts[0].strip()
    given = parts[1].strip()
    initials = " ".join(f"{w[0]}." for w in given.split() if w)
    return f"{initials} {surname}"


# ---------- Helpers ----------

def _invert_author(name: str) -> str:
    """Ensure author name is in 'Surname, Initials.' format for APA/Harvard."""
    # If already inverted (contains comma), return as-is
    if "," in name:
        return name.strip()
    # Try to invert "John A. Smith" → "Smith, J. A."
    parts = name.strip().split()
    if len(parts) < 2:
        return name.strip()
    surname = parts[-1]
    initials = " ".join(f"{p[0]}." for p in parts[:-1])
    return f"{surname}, {initials}"


def _direct_order(name: str) -> str:
    """Convert 'Smith, John' → 'John Smith'."""
    parts = name.split(",", 1)
    if len(parts) == 1:
        return name.strip()
    return f"{parts[1].strip()} {parts[0].strip()}"


def _is_article(ref_type: str) -> bool:
    """Check if the reference type is a journal/periodical article."""
    rt = ref_type.lower()
    return any(kw in rt for kw in ("journal", "article", "magazine", "periodical"))


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
