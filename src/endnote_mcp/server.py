"""MCP server exposing 12 tools for Claude to interact with an EndNote library."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from endnote_mcp.config import Config
from endnote_mcp.db import connect, get_stats
from endnote_mcp.search import (
    search_references as _search_refs,
    search_fulltext as _search_ft,
    search_library as _search_lib,
    get_reference_details as _get_details,
    list_by_topic as _list_topic,
    find_related as _find_related,
    get_references_batch as _get_refs_batch,
    search_semantic as _search_semantic,
)
from endnote_mcp.citation import format_citation, format_bibtex, STYLES
from endnote_mcp.pdf_indexer import find_pdf, read_pages

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "EndNote Library",
    instructions="Search, cite, and read PDFs from your EndNote reference library.",
)

# --- Lazy globals (initialized on first tool call) ---
_config: Config | None = None
_conn = None


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def _get_conn():
    global _conn
    if _conn is None:
        cfg = _get_config()
        _conn = connect(cfg.db_path)
    return _conn


# ====================================================================
# Tool 1: search_references
# ====================================================================
@mcp.tool()
def search_references(
    query: str,
    year_from: str | None = None,
    year_to: str | None = None,
    author: str | None = None,
    ref_type: str | None = None,
    limit: int = 50,
) -> str:
    """Search your EndNote library by title, author, keywords, or abstract.

    Uses full-text search with BM25 relevance ranking.

    Args:
        query: Search terms (e.g. "social capital Bourdieu", "grounded theory").
        year_from: Optional start year filter (e.g. "2015").
        year_to: Optional end year filter (e.g. "2023").
        author: Optional author name filter (partial match).
        ref_type: Optional reference type filter (e.g. "Journal Article", "Book", "Patent").
        limit: Maximum results to return (default 50).
    """
    conn = _get_conn()
    results = _search_refs(conn, query, year_from=year_from, year_to=year_to, author=author, ref_type=ref_type, limit=limit)
    if not results:
        return f"No references found for: {query}"
    lines = [f"Found {len(results)} reference(s):\n"]
    for r in results:
        kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
        lines.append(
            f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
            + (f" *{r['journal']}*." if r.get("journal") else "")
            + (f"  Keywords: {kw}" if kw else "")
        )
    return "\n".join(lines)


# ====================================================================
# Tool 2: search_fulltext
# ====================================================================
@mcp.tool()
def search_fulltext(query: str, limit: int = 50) -> str:
    """Search inside the PDF content of your references.

    Finds specific quotes, methods, concepts, or passages within papers.
    Results are grouped by reference — each paper appears once with its
    top matching snippets listed underneath.

    Args:
        query: Search terms to find inside PDF text.
        limit: Maximum references to return (default 50).
    """
    conn = _get_conn()
    results = _search_ft(conn, query, limit=limit)
    if not results:
        return f"No fulltext matches for: {query}"
    total_snippets = sum(len(r["snippets"]) for r in results)
    lines = [f"Found {total_snippets} match(es) across {len(results)} reference(s):\n"]
    for r in results:
        lines.append(
            f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}"
        )
        for s in r["snippets"]:
            lines.append(f"      — page {s['page']}: ...{s['snippet']}...")
    return "\n".join(lines)


# ====================================================================
# Tool 3: search_library (combined metadata + PDF search)
# ====================================================================
@mcp.tool()
def search_library(
    query: str,
    year_from: str | None = None,
    year_to: str | None = None,
    author: str | None = None,
    ref_type: str | None = None,
    limit: int = 30,
) -> str:
    """Search your entire library — metadata, PDF content, and semantic similarity — in one call.

    Combines keyword search, full-text PDF search, and AI semantic search.
    References matching across multiple methods are ranked highest.

    Args:
        query: Search terms (e.g. "grounded theory", "social capital").
        year_from: Optional start year filter (e.g. "2015").
        year_to: Optional end year filter (e.g. "2023").
        author: Optional author name filter (partial match).
        ref_type: Optional reference type filter (e.g. "Journal Article", "Book", "Patent").
        limit: Maximum references to return (default 30).
    """
    conn = _get_conn()
    results = _search_lib(
        conn, query,
        year_from=year_from, year_to=year_to, author=author,
        ref_type=ref_type, limit=limit,
    )
    if not results:
        return f"No references found for: {query}"

    with_pdf = sum(1 for r in results if r.get("snippets"))
    lines = [f"Found {len(results)} reference(s) ({with_pdf} with PDF matches):\n"]
    for r in results:
        kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
        lines.append(
            f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
            + (f" *{r['journal']}*." if r.get("journal") else "")
        )
        if kw:
            lines.append(f"    Keywords: {kw}")
        if r.get("snippets"):
            lines.append("    PDF matches:")
            for s in r["snippets"]:
                lines.append(f"      — page {s['page']}: ...{s['snippet']}...")
    return "\n".join(lines)


# ====================================================================
# Tool 4: get_reference_details
# ====================================================================
@mcp.tool()
def get_reference_details(rec_number: int) -> str:
    """Get full metadata for a reference by its record number.

    Returns all fields: abstract, keywords, DOI, authors, journal info, etc.

    Args:
        rec_number: The EndNote record number (shown in search results as [number]).
    """
    conn = _get_conn()
    ref = _get_details(conn, rec_number)
    if ref is None:
        return f"Reference #{rec_number} not found."

    lines = [f"Reference #{rec_number}:"]
    lines.append(f"  Type: {ref.get('ref_type', 'Unknown')}")
    lines.append(f"  Title: {ref.get('title', '')}")
    authors = ref.get("authors", [])
    if authors:
        lines.append(f"  Authors: {'; '.join(authors)}")
    lines.append(f"  Year: {ref.get('year', '')}")
    if ref.get("journal"):
        lines.append(f"  Journal: {ref['journal']}")
    if ref.get("volume"):
        vol = ref["volume"]
        if ref.get("issue"):
            vol += f"({ref['issue']})"
        lines.append(f"  Volume: {vol}")
    if ref.get("pages"):
        lines.append(f"  Pages: {ref['pages']}")
    if ref.get("doi"):
        lines.append(f"  DOI: {ref['doi']}")
    if ref.get("url"):
        lines.append(f"  URL: {ref['url']}")
    if ref.get("publisher"):
        lines.append(f"  Publisher: {ref['publisher']}")
    if ref.get("isbn"):
        lines.append(f"  ISBN: {ref['isbn']}")
    keywords = ref.get("keywords", [])
    if keywords:
        lines.append(f"  Keywords: {', '.join(keywords)}")
    if ref.get("abstract"):
        lines.append(f"  Abstract: {ref['abstract']}")
    lines.append(f"  Indexed PDF pages: {ref.get('indexed_pdf_pages', 0)}")
    if ref.get("pdf_path"):
        lines.append(f"  PDF: {ref['pdf_path']}")
    return "\n".join(lines)


# ====================================================================
# Tool 5: get_citation
# ====================================================================
@mcp.tool()
def get_citation(rec_number: int, style: str = "apa7") -> str:
    """Format a reference as a citation in a specific style.

    Args:
        rec_number: The EndNote record number.
        style: Citation style — one of: apa7, harvard, vancouver, chicago, ieee.
    """
    conn = _get_conn()
    ref = _get_details(conn, rec_number)
    if ref is None:
        return f"Reference #{rec_number} not found."

    try:
        citation = format_citation(ref, style)
    except ValueError as e:
        return str(e)

    return f"[{style.upper()}] {citation}"


# ====================================================================
# Tool 6: read_pdf_section
# ====================================================================
@mcp.tool()
def read_pdf_section(rec_number: int, start_page: int = 1, end_page: int = 5) -> str:
    """Read specific pages from a reference's PDF attachment.

    Args:
        rec_number: The EndNote record number.
        start_page: First page to read (1-based, default 1).
        end_page: Last page to read (1-based, default 5).
    """
    cfg = _get_config()
    conn = _get_conn()

    ref = _get_details(conn, rec_number)
    if ref is None:
        return f"Reference #{rec_number} not found."

    pdf_filename = ref.get("pdf_path", "")
    if not pdf_filename:
        return f"No PDF attachment for reference #{rec_number}."

    pdf_path = find_pdf(cfg.pdf_dir, pdf_filename)
    if pdf_path is None:
        return f"PDF file not found: {pdf_filename}"

    # Enforce page limit
    max_pages = cfg.max_pdf_pages
    if end_page - start_page + 1 > max_pages:
        end_page = start_page + max_pages - 1

    try:
        pages = read_pages(pdf_path, start_page, end_page)
    except Exception as e:
        return f"Error reading PDF: {e}"

    if not pages:
        return f"No text extracted from pages {start_page}-{end_page}."

    lines = [f"PDF: {ref.get('title', '')} — pages {start_page}-{end_page} (of {pages[0]['total_pages']})\n"]
    for p in pages:
        lines.append(f"--- Page {p['page']} ---")
        lines.append(p["text"])
        lines.append("")
    return "\n".join(lines)


# ====================================================================
# Tool 7: list_references_by_topic
# ====================================================================
@mcp.tool()
def list_references_by_topic(
    topic: str,
    year_from: str | None = None,
    year_to: str | None = None,
    ref_type: str | None = None,
    limit: int = 50,
) -> str:
    """List references matching a broad topic or theme.

    Good for exploring what's in your library on a subject.

    Args:
        topic: Broad topic terms (e.g. "inequality", "qualitative methods").
        year_from: Optional start year filter.
        year_to: Optional end year filter.
        ref_type: Optional reference type filter (e.g. "Journal Article", "Book", "Patent").
        limit: Maximum results (default 50).
    """
    conn = _get_conn()
    results = _list_topic(conn, topic, year_from=year_from, year_to=year_to, ref_type=ref_type, limit=limit)
    if not results:
        return f"No references found for topic: {topic}"
    lines = [f"Found {len(results)} reference(s) on '{topic}':\n"]
    for r in results:
        kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
        lines.append(
            f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
            + (f" *{r['journal']}*." if r.get("journal") else "")
            + (f"  Keywords: {kw}" if kw else "")
        )
    return "\n".join(lines)


# ====================================================================
# Tool 8: find_related
# ====================================================================
@mcp.tool()
def find_related(rec_number: int, limit: int = 10) -> str:
    """Find references related to a given reference.

    Uses shared keywords, title terms, and topics to find similar papers
    in your library. Useful for literature reviews and discovering
    connected work.

    Args:
        rec_number: The record number to find related references for.
        limit: Maximum results (default 10).
    """
    conn = _get_conn()
    ref = _get_details(conn, rec_number)
    if ref is None:
        return f"Reference #{rec_number} not found."

    results = _find_related(conn, rec_number, limit=limit)
    if not results:
        return f"No related references found for #{rec_number}."

    title = ref.get("title", "")
    lines = [f"References related to [{rec_number}] {title}:\n"]
    for r in results:
        kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
        lines.append(
            f"  [{r['rec_number']}] {r['authors']} ({r['year']}). {r['title']}."
            + (f" *{r['journal']}*." if r.get("journal") else "")
            + (f"  Keywords: {kw}" if kw else "")
        )
    return "\n".join(lines)


# ====================================================================
# Tool 9: get_bibliography
# ====================================================================
@mcp.tool()
def get_bibliography(
    rec_numbers: str,
    style: str = "apa7",
    sort: str = "author",
) -> str:
    """Generate a formatted bibliography for multiple references.

    Produces a numbered reference list ready for use in a paper or report.

    Args:
        rec_numbers: Comma-separated record numbers (e.g. "12,45,78,102").
        style: Citation style — one of: apa7, harvard, vancouver, chicago, ieee.
        sort: Sort order — "author" (alphabetical) or "year" (chronological).
    """
    try:
        numbers = [int(x.strip()) for x in rec_numbers.split(",") if x.strip()]
    except ValueError:
        return "Invalid rec_numbers format. Use comma-separated integers (e.g. '12,45,78')."

    if not numbers:
        return "No record numbers provided."

    conn = _get_conn()
    refs = _get_refs_batch(conn, numbers)
    if not refs:
        return "None of the specified references were found."

    # Format citations
    entries: list[dict] = []
    not_found = set(numbers) - {r["rec_number"] for r in refs}
    for ref in refs:
        try:
            citation = format_citation(ref, style)
        except ValueError:
            citation = f"{ref.get('title', 'Unknown title')} (formatting error)"
        # Extract sort key
        authors = ref.get("authors", [])
        first_author = authors[0] if authors else ""
        entries.append({
            "citation": citation,
            "author_sort": first_author.lower(),
            "year": ref.get("year", ""),
            "rec_number": ref["rec_number"],
        })

    # Sort
    if sort == "year":
        entries.sort(key=lambda e: (e["year"] or "0", e["author_sort"]))
    else:
        entries.sort(key=lambda e: (e["author_sort"], e["year"] or "0"))

    lines = [f"Bibliography ({len(entries)} references, {style.upper()}):\n"]
    for i, e in enumerate(entries, 1):
        lines.append(f"  {i}. {e['citation']}")

    if not_found:
        lines.append(f"\nNot found: {', '.join(str(n) for n in sorted(not_found))}")

    return "\n".join(lines)


# ====================================================================
# Tool 10: search_semantic
# ====================================================================
@mcp.tool()
def search_semantic(query: str, limit: int = 20) -> str:
    """Search your library by meaning, not just keywords.

    Uses AI embeddings to find references related to your query even when
    they use different terminology. For example, searching "how companies
    prepare for uncertain futures" will find papers on scenario planning,
    strategic foresight, and risk management.

    Requires: pip install endnote-mcp[semantic]

    Args:
        query: Describe what you're looking for in natural language.
        limit: Maximum results (default 20).
    """
    from endnote_mcp import embeddings

    if not embeddings.is_available():
        return (
            "Semantic search is not available. Install the required dependencies:\n"
            "  pip install endnote-mcp[semantic]\n"
            "Then run: endnote-mcp embed"
        )

    conn = _get_conn()

    if not embeddings.has_embeddings(conn):
        return (
            "No embeddings found. Generate them first:\n"
            "  endnote-mcp embed"
        )

    results = _search_semantic(conn, query, limit=limit)
    if not results:
        return f"No semantic matches for: {query}"

    lines = [f"Found {len(results)} reference(s) by semantic similarity:\n"]
    for r in results:
        sim_pct = f"{r.get('similarity', 0):.0%}"
        kw = ", ".join(r["keywords"][:5]) if r.get("keywords") else ""
        lines.append(
            f"  [{r['rec_number']}] ({sim_pct}) {r['authors']} ({r['year']}). {r['title']}."
            + (f" *{r['journal']}*." if r.get("journal") else "")
            + (f"  Keywords: {kw}" if kw else "")
        )
    return "\n".join(lines)


# ====================================================================
# Tool 11: get_bibtex
# ====================================================================
@mcp.tool()
def get_bibtex(rec_numbers: str) -> str:
    """Export references as BibTeX entries for use in LaTeX.

    Returns complete BibTeX entries that can be pasted into a .bib file.

    Args:
        rec_numbers: Comma-separated record numbers (e.g. "12,45,78").
    """
    try:
        numbers = [int(x.strip()) for x in rec_numbers.split(",") if x.strip()]
    except ValueError:
        return "Invalid rec_numbers format. Use comma-separated integers (e.g. '12,45,78')."

    if not numbers:
        return "No record numbers provided."

    conn = _get_conn()
    refs = _get_refs_batch(conn, numbers)
    if not refs:
        return "None of the specified references were found."

    entries = []
    not_found = set(numbers) - {r["rec_number"] for r in refs}
    for ref in refs:
        entries.append(format_bibtex(ref))

    result = "\n\n".join(entries)

    if not_found:
        result += f"\n\n% Not found: {', '.join(str(n) for n in sorted(not_found))}"

    return result


# ====================================================================
# Tool 12: rebuild_index
# ====================================================================
@mcp.tool()
def rebuild_index() -> str:
    """Re-index your EndNote library after adding new references.

    Run this after you've exported a new XML file from EndNote.
    This will re-parse the XML and re-extract all PDFs.
    """
    try:
        cfg = _get_config()
        result = subprocess.run(
            [sys.executable, "-m", "endnote_mcp.cli", "index"],
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout for large libraries
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\nErrors:\n{result.stderr}"

        # Reconnect to pick up new data
        global _conn
        if _conn:
            _conn.close()
        _conn = connect(cfg.db_path)

        stats = get_stats(_conn)
        return (
            f"Re-indexing complete.\n"
            f"  References: {stats['total_references']}\n"
            f"  PDFs indexed: {stats['references_with_pdf']}\n"
            f"  PDF pages: {stats['total_pdf_pages']}\n\n"
            f"Output:\n{output}"
        )
    except subprocess.TimeoutExpired:
        return "Re-indexing timed out after 2 hours. Try running the indexing script manually."
    except Exception as e:
        return f"Re-indexing failed: {e}"


# ====================================================================
# Entry point
# ====================================================================
def main():
    mcp.run()


if __name__ == "__main__":
    main()
