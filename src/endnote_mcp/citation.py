"""Citation formatters for APA 7th, Harvard, Vancouver, Chicago, and IEEE."""

from __future__ import annotations

import datetime as _dt
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

    title = _bare_title(ref.get("title", ""))
    year = ref.get("year") or "n.d."
    journal = ref.get("journal", "")
    volume = ref.get("volume", "")
    issue = ref.get("issue", "")
    pages = ref.get("pages", "")
    doi = ref.get("doi", "")
    publisher = ref.get("publisher", "")
    place = ref.get("place_published", "")
    ref_type = ref.get("ref_type", "Journal Article")
    url = (ref.get("url") or "").strip()
    access_date = (ref.get("access_date") or "").strip()

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
        url=url,
        access_date=access_date,
    )
    # A field that already ends in a full stop, question mark or exclamation
    # mark ("J. A.", "et al.", "n.d.", "Inc.", a title that asks a question)
    # takes no second full stop, even across closing italics; ellipses stay
    return re.sub(r"(?<!\.)([.?!])(\*?)\.(?!\.)", r"\1\2", citation)


# ---------- APA 7th Edition ----------

def _apa7(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type,
          url="", access_date=""):
    parts = []
    kind = _source_kind(ref_type, journal)

    # Authors
    if authors:
        # A group author needs this full stop; format_citation drops a doubled one
        parts.append(_apa_authors(authors) + ".")
    else:
        # The title takes the author's place, italic if the work stands alone
        if title:
            parts.append(f"*{title}*." if kind in _STANDALONE else f"{title}.")
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
    elif publisher and not _is_author(publisher, authors):
        # APA 7 leaves out the publisher's location, and the publisher itself
        # when it is also the author
        parts.append(f"{publisher}.")

    # DOI, or for a report or web page without one, where it can be read;
    # an undated page may change, so APA adds when it was read
    if doi:
        parts.append(_doi_url(doi))
    elif url and kind == "web" and year == "n.d." and access_date:
        parts.append(f"Retrieved {_format_date(access_date, 'apa7')}, from {url}")
    elif url and kind in _ONLINE:
        parts.append(url)

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

def _harvard(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type,
             url="", access_date=""):
    parts = []
    kind = _source_kind(ref_type, journal)

    if authors:
        parts.append(_harvard_authors(authors))
    elif kind in _STANDALONE and title:
        # Without an author, the title leads (Cite Them Right)
        parts.append(f"*{title}*")
        title = ""
    parts.append(f"({year})")

    if kind == "article":
        if title:
            quoted = _nest(title, "'")
            parts.append(f"'{quoted}',")
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
        if title:
            quoted = _nest(title, "'")
            parts.append(f"'{quoted}',")
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
        if title:
            parts.append(f"*{title}*.")
        # A web page is cited by its address, not its site's owner
        if publisher and kind != "web":
            pub = f"{place}: {publisher}." if place else f"{publisher}."
            parts.append(pub)
        if url and not doi and kind in _ONLINE:
            accessed = f" (Accessed: {_format_date(access_date, 'harvard')})" if access_date else ""
            parts.append(f"Available at: {url}{accessed}.")

    if doi:
        parts.append(_doi_url(doi))

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

def _vancouver(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type,
               url="", access_date=""):
    parts = []
    kind = _source_kind(ref_type, journal)
    online = kind in _ONLINE and bool(url or doi)
    if year == "n.d.":
        year = "[date unknown]"  # Citing Medicine's wording

    if authors:
        parts.append(_vancouver_authors(authors) + ".")

    if title:
        parts.append(f"{title} [Internet]." if online else f"{title}.")

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
        # Citing Medicine dates an online source by when it was read: [cited 2026 Nov 11]
        cited = f" [cited {_format_date(access_date, 'vancouver')}]" if online and access_date else ""
        if place and publisher:
            parts.append(f"{place}: {publisher}; {year}{cited}.")
        elif publisher:
            parts.append(f"{publisher}; {year}{cited}.")
        else:
            parts.append(f"{year}{cited}.")
        if online:
            parts.append(f"Available from: {_doi_url(doi) if doi else url}")

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

def _chicago(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type,
             url="", access_date=""):
    parts = []
    kind = _source_kind(ref_type, journal)

    if authors:
        parts.append(_chicago_authors(authors) + ".")
    elif kind in _STANDALONE and title:
        # Without an author, the title leads
        parts.append(f'"{_nest(title)}."' if kind == "web" else f"*{title}*.")
        title = ""

    parts.append(f"{year}.")

    if kind == "article":
        if title:
            parts.append(f'"{_nest(title)}."')
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
        if title:
            parts.append(f'"{_nest(title)}."')
        source = f"In *{journal}*"
        if pages:
            source += f", {_page_range(pages)}"
        parts.append(source + ".")
        if place and publisher:
            parts.append(f"{place}: {publisher}.")
        elif publisher:
            parts.append(f"{publisher}.")
    elif kind == "presentation":
        if title:
            parts.append(f'"{_nest(title)}."')
        parts.append(f"Paper presented at {journal}, {place}." if place else f"Paper presented at {journal}.")
    elif kind == "web":
        # A page's title goes in quotation marks, its site in roman
        if title:
            parts.append(f'"{_nest(title)}."')
        if publisher:
            parts.append(f"{publisher}.")
    else:
        if title:
            parts.append(f"*{title}*.")
        if place and publisher:
            parts.append(f"{place}: {publisher}.")
        elif publisher:
            parts.append(f"{publisher}.")

    if doi:
        parts.append(_doi_url(doi))
    elif url and kind in _ONLINE:
        # Chicago wants an access date only when the source has no date of its own
        if year == "n.d." and access_date:
            parts.append(f"Accessed {_format_date(access_date, 'chicago')}.")
        parts.append(f"{url}.")

    return " ".join(parts)


def _chicago_authors(authors: list[str]) -> str:
    names = [_full_name(authors[0], inverted=True)] + [_direct_order(a) for a in authors[1:]]
    if len(names) == 1:
        return names[0]
    # The reference list names up to ten authors; beyond ten, the first seven
    if len(names) > 10:
        return ", ".join(names[:7]) + ", et al."
    # A comma closes the inverted first name ("Ward, Geoffrey C., and Ken
    # Burns"); a group author has no given name to close
    if len(names) == 2 and not _split_name(authors[0])[1]:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + ", and " + names[-1]


# ---------- IEEE ----------

def _ieee(*, authors, title, year, journal, volume, issue, pages, doi, publisher, place, ref_type,
          url="", access_date=""):
    parts = []
    kind = _source_kind(ref_type, journal)

    if kind == "web":
        # IEEE website: A. Author. "Title." Site. URL (accessed Mon. D, YYYY).
        if authors:
            parts.append(_ieee_authors(authors) + ".")
        if title:
            parts.append(f'"{_nest(title)}."')
        if publisher:
            parts.append(f"{publisher}.")
        link = _doi_url(doi) if doi else url
        if link:
            accessed = f" (accessed {_format_date(access_date, 'ieee')})" if access_date else ""
            parts.append(f"{link}{accessed}.")
        else:
            parts.append(f"{year}.")
        return " ".join(parts)

    if authors:
        parts.append(_ieee_authors(authors) + ",")

    if title:
        # A book's title is italic; the title of a part (article, chapter, report) is quoted
        parts.append(f"*{title}*." if kind == "book" else f'"{_nest(title)},"')

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
    elif kind == "report":
        # IEEE report: "Title," Publisher, Place, Year. Accessed: ... [Online]. Available: URL
        parts.append(", ".join([p for p in (publisher, place) if p] + [year]) + ".")
        if url and not doi:
            accessed = f"Accessed: {_format_date(access_date, 'ieee')}. " if access_date else ""
            parts.append(f"{accessed}[Online]. Available: {url}")
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
    # IEEE names up to six authors; beyond six, the first and "et al."
    if len(formatted) > 6:
        return f"{formatted[0]} et al."
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
    """Say where a reference appeared: article, chapter, proceedings,
    presentation, report, web (page) or book.

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
    if "report" in rt or "government document" in rt:
        return "report"
    if "web page" in rt or "blog" in rt:
        return "web"
    return "book"


# Kinds that stand alone (italic titles), and kinds cited with their web address
_STANDALONE = ("book", "report", "web")
_ONLINE = ("report", "web")


def _bare_title(title: str) -> str:
    """Drop quotation marks around a whole title: '"BASIC"' -> 'BASIC'.

    EndNote's capture of encyclopedia and web entries sometimes stores the
    marks with the title, and styles that quote titles would double them.
    """
    t = (title or "").strip()
    if len(t) > 1 and t[0] in '"\u201c' and t[-1] in '"\u201d' and not any(q in t[1:-1] for q in '"\u201c\u201d'):
        return t[1:-1].strip()
    return t


# Quoted stretches of a title. A single quotation mark must open after a
# non-letter and close before one, so apostrophes (Scotland's) don't count.
_DOUBLE_PAIR = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d')
_SINGLE_PAIR = re.compile(r"(?<!\w)'.*?'(?!\w)|\u2018.*?\u2019(?!\w)")


def _nest(title: str, outer: str = '"') -> str:
    """Make quotations inside a title alternate with the style's own marks.

    Chicago and IEEE put a title in double quotation marks, so a quotation
    inside it takes single ones; Harvard does the reverse. When the title
    quotes with the style's own mark, single and double swap throughout.
    Only the outermost quotation decides: a title already alternating its
    marks the right way round is left alone.
    """
    double, single = _DOUBLE_PAIR.search(title), _SINGLE_PAIR.search(title)
    if not double and not single:
        return title
    outermost = '"' if double and (not single or double.start() < single.start()) else "'"
    if outermost != outer:
        return title
    marks = {"\x01": "'", "\x02": "\u2018", "\x03": "\u2019"}
    title = re.sub(r'"([^"]*)"', "\x01\\1\x01", title)
    title = re.sub("\u201c([^\u201d]*)\u201d", "\x02\\1\x03", title)
    title = re.sub(r"(?<!\w)'(.*?)'(?!\w)", r'"\1"', title)
    title = re.sub("\u2018(.*?)\u2019(?!\w)", "\u201c\\1\u201d", title)
    for placeholder, mark in marks.items():
        title = title.replace(placeholder, mark)
    return title


def _doi_url(doi: str) -> str:
    doi = doi.strip()
    return doi if doi.startswith("http") else f"https://doi.org/{doi}"


def _party(name: str) -> str:
    """A name reduced for comparison: 'The Scottish Government,' -> 'scottish government'."""
    words = re.sub(r"[\W_]+", " ", name.casefold()).split()
    return " ".join(words[1:] if words[:1] == ["the"] else words)


def _is_author(publisher: str, authors: list[str]) -> bool:
    """Whether the publisher is one of the (group) authors, as with most agency reports."""
    key = _party(publisher)
    return bool(key) and any(
        _party(surname) == key for surname, given, _ in map(_split_name, authors) if not given
    )


_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_MONTH_NUMBER = {m.lower(): i for i, m in enumerate(_MONTHS, 1)}
_MONTH_NUMBER.update({m[:3].lower(): i for i, m in enumerate(_MONTHS, 1)})
_MONTH_NUMBER["sept"] = 9
# The IEEE Editorial Style Manual's month abbreviations
_IEEE_MONTHS = ("Jan.", "Feb.", "Mar.", "Apr.", "May", "June", "July",
                "Aug.", "Sept.", "Oct.", "Nov.", "Dec.")


def _parse_date(text: str) -> _dt.date | None:
    """Read a date typed in one of the usual ways; None when it is unclear.

    EndNote keeps Access Date as typed: "11 November 2026", "Nov 11, 2026",
    "29.03.2016", "2025-02-01T11:43:59", "2025/02/01/". A slashed date with
    the year last ("2/10/2025") reads either way round, so it counts only
    when one of its first two numbers is over 12.
    """
    s = text.strip().rstrip(".")
    day = month = year = None
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[Tt ][\d:.]+Z?)?/?", s):
        year, month, day = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s):
        day, month, year = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
        first, second, year = m.groups()
        if int(first) > 12 >= int(second) or first.lstrip("0") == second.lstrip("0"):
            day, month = first, second
        elif int(second) > 12 >= int(first):
            month, day = first, second
    elif m := re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})", s):
        day, name, year = m.groups()
        month = _MONTH_NUMBER.get(name.lower())
    elif m := re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", s):
        name, day, year = m.groups()
        month = _MONTH_NUMBER.get(name.lower())
    if not (day and month and year):
        return None
    try:
        return _dt.date(int(year), int(month), int(day))
    except ValueError:
        return None


def _format_date(text: str, style: str) -> str:
    """An access date the way *style* writes it; as typed if it can't be read."""
    d = _parse_date(text)
    if d is None:
        return text.strip()
    month = _MONTHS[d.month - 1]
    if style == "vancouver":
        return f"{d.year} {month[:3]} {d.day}"
    if style == "ieee":
        return f"{_IEEE_MONTHS[d.month - 1]} {d.day}, {d.year}"
    if style in ("chicago", "apa7"):
        return f"{month} {d.day}, {d.year}"
    return f"{d.day} {month} {d.year}"


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

    title = _bare_title(ref.get("title", ""))
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

    # "Surname, Given and Surname, Given"; an organisation goes in braces so
    # BibTeX keeps it whole instead of reading it as a person
    bib_authors = " and ".join(_bibtex_author(a) for a in authors)

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
    url = (ref.get("url") or "").strip()
    if url and _source_kind(ref_type, journal) in _ONLINE:
        fields.append(("url", url))
        read = _parse_date(ref.get("access_date") or "")
        if read:
            fields.append(("urldate", read.isoformat()))

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


def _bibtex_author(name: str) -> str:
    """'Smith, John A.' stays; 'Scottish Government,' becomes '{Scottish Government}'."""
    surname, given, suffix = _split_name(name)
    if not given:
        return f"{{{surname.rstrip(', ')}}}"
    return f"{surname}, {suffix}, {given}" if suffix else f"{surname}, {given}"


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
