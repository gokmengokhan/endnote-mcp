"""FTS5-backed search engine for references and PDF content."""

from __future__ import annotations

import json
import sqlite3
from collections import OrderedDict
from typing import Any


def search_references(
    conn: sqlite3.Connection,
    query: str,
    *,
    year_from: str | None = None,
    year_to: str | None = None,
    author: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search reference metadata using FTS5 with BM25 ranking.

    The FTS5 columns are weighted: title (10), authors (5), abstract (3),
    keywords (8), journal (2).
    """
    if not query.strip():
        return []

    # Build the FTS query - escape double quotes in user input
    fts_query = query.replace('"', '""')

    sql = """
        SELECT
            r.rec_number,
            r.title,
            r.authors,
            r.year,
            r.journal,
            r.ref_type,
            r.doi,
            r.keywords,
            bm25(references_fts, 10.0, 5.0, 3.0, 8.0, 2.0) AS rank
        FROM references_fts
        JOIN references_ r ON r.rec_number = references_fts.rowid
        WHERE references_fts MATCH ?
    """
    params: list[Any] = [fts_query]

    if year_from:
        sql += " AND CAST(r.year AS INTEGER) >= ?"
        params.append(int(year_from))
    if year_to:
        sql += " AND CAST(r.year AS INTEGER) <= ?"
        params.append(int(year_to))
    if author:
        sql += " AND r.authors LIKE ?"
        params.append(f"%{author}%")

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_ref_summary(row) for row in rows]


def search_fulltext(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 50,
    max_snippets_per_ref: int = 3,
) -> list[dict]:
    """Search inside PDF content using FTS5 with BM25 ranking.

    Returns results grouped by reference. Each result dict contains a
    list of ``snippets`` with (page, snippet) matches.
    """
    if not query.strip():
        return []

    fts_query = query.replace('"', '""')

    # Fetch a generous pool of raw matches, then group by reference
    inner_limit = max(limit * 10, 200)
    sql = """
        SELECT
            pp.rec_number,
            pp.page_number,
            r.title,
            r.authors,
            r.year,
            r.journal,
            r.keywords,
            snippet(pdf_fts, 0, '>>>', '<<<', '...', 400) AS snippet,
            bm25(pdf_fts) AS rank
        FROM pdf_fts
        JOIN pdf_pages pp ON pp.id = pdf_fts.rowid
        JOIN references_ r ON r.rec_number = pp.rec_number
        WHERE pdf_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """
    rows = conn.execute(sql, [fts_query, inner_limit]).fetchall()

    # Group by rec_number, keeping per-ref snippet order (best rank first)
    grouped: OrderedDict[int, dict] = OrderedDict()
    for row in rows:
        rn = row["rec_number"]
        if rn not in grouped:
            grouped[rn] = {
                "rec_number": rn,
                "title": row["title"],
                "authors": _parse_authors_short(row["authors"]),
                "year": row["year"],
                "journal": row["journal"],
                "keywords": _parse_json_list(
                    row["keywords"] if "keywords" in row.keys() else "[]"
                ),
                "snippets": [],
            }
        if len(grouped[rn]["snippets"]) < max_snippets_per_ref:
            grouped[rn]["snippets"].append({
                "page": row["page_number"],
                "snippet": row["snippet"],
            })

    # Return up to `limit` unique references
    return list(grouped.values())[:limit]


def get_reference_details(conn: sqlite3.Connection, rec_number: int) -> dict | None:
    """Get full metadata for a single reference."""
    row = conn.execute(
        "SELECT * FROM references_ WHERE rec_number = ?", (rec_number,)
    ).fetchone()
    if row is None:
        return None

    ref = dict(row)
    ref["authors"] = json.loads(ref["authors"]) if ref["authors"] else []
    ref["keywords"] = json.loads(ref["keywords"]) if ref["keywords"] else []

    # Count indexed PDF pages
    page_count = conn.execute(
        "SELECT COUNT(*) FROM pdf_pages WHERE rec_number = ?", (rec_number,)
    ).fetchone()[0]
    ref["indexed_pdf_pages"] = page_count

    return ref


def list_by_topic(
    conn: sqlite3.Connection,
    topic: str,
    *,
    year_from: str | None = None,
    year_to: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List references matching a broad topic across keywords, title, abstract."""
    if not topic.strip():
        return []

    fts_query = topic.replace('"', '""')

    sql = """
        SELECT
            r.rec_number,
            r.title,
            r.authors,
            r.year,
            r.journal,
            r.ref_type,
            r.keywords,
            bm25(references_fts, 10.0, 5.0, 3.0, 8.0, 2.0) AS rank
        FROM references_fts
        JOIN references_ r ON r.rec_number = references_fts.rowid
        WHERE references_fts MATCH ?
    """
    params: list[Any] = [fts_query]

    if year_from:
        sql += " AND CAST(r.year AS INTEGER) >= ?"
        params.append(int(year_from))
    if year_to:
        sql += " AND CAST(r.year AS INTEGER) <= ?"
        params.append(int(year_to))

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_ref_summary(row) for row in rows]


def search_library(
    conn: sqlite3.Connection,
    query: str,
    *,
    year_from: str | None = None,
    year_to: str | None = None,
    author: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Combined search across metadata and PDF content.

    Runs both ``search_references`` and ``search_fulltext``, then merges
    results by ``rec_number``.  References that appear in *both* result
    sets are boosted to the top.
    """
    meta_results = search_references(
        conn, query, year_from=year_from, year_to=year_to, author=author, limit=limit
    )
    ft_results = search_fulltext(conn, query, limit=limit)

    # Index fulltext results by rec_number for fast lookup
    ft_by_rn: dict[int, dict] = {r["rec_number"]: r for r in ft_results}

    both: list[dict] = []      # matched in metadata AND fulltext
    meta_only: list[dict] = [] # matched in metadata only

    seen: set[int] = set()
    for ref in meta_results:
        rn = ref["rec_number"]
        seen.add(rn)
        ft = ft_by_rn.get(rn)
        entry = {**ref, "snippets": ft["snippets"] if ft else []}
        if ft:
            both.append(entry)
        else:
            meta_only.append(entry)

    # Fulltext-only results (not in metadata results)
    ft_only: list[dict] = []
    for rn, ft in ft_by_rn.items():
        if rn not in seen:
            ft_only.append(ft)

    merged = both + meta_only + ft_only
    return merged[:limit]


def _row_to_ref_summary(row: sqlite3.Row) -> dict:
    """Convert a DB row to a summary dict for display."""
    return {
        "rec_number": row["rec_number"],
        "title": row["title"],
        "authors": _parse_authors_short(row["authors"]),
        "year": row["year"],
        "journal": row["journal"],
        "ref_type": row["ref_type"],
        "keywords": _parse_json_list(row["keywords"] if "keywords" in row.keys() else "[]"),
    }


def _parse_authors_short(authors_json: str) -> str:
    """Convert JSON author list to a short display string."""
    try:
        authors = json.loads(authors_json) if authors_json else []
    except (json.JSONDecodeError, TypeError):
        return str(authors_json)

    if not authors:
        return "Unknown"
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} & {authors[1]}"
    return f"{authors[0]} et al."


def search_semantic(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[dict]:
    """Search references by semantic similarity using embeddings.

    Requires sentence-transformers to be installed (endnote-mcp[semantic]).
    Returns results in the same format as ``search_references()``.
    """
    from endnote_mcp import embeddings

    if not embeddings.is_available():
        return []

    model = embeddings.load_model()
    query_emb = embeddings.encode_text(model, query)
    return embeddings.search_semantic(conn, query_emb, limit=limit)


def find_related(
    conn: sqlite3.Connection,
    rec_number: int,
    *,
    limit: int = 10,
) -> list[dict]:
    """Find references related to a given reference.

    Uses embedding similarity when available, falls back to FTS keyword matching.
    """
    # Try embedding-based search first
    try:
        from endnote_mcp import embeddings

        if embeddings.is_available() and embeddings.has_embeddings(conn):
            emb = embeddings.get_embedding(conn, rec_number)
            if emb is not None:
                return embeddings.search_by_embedding(
                    conn, emb, exclude_rec=rec_number, limit=limit,
                )
    except Exception:
        pass  # Fall through to FTS

    # Fallback: FTS keyword matching
    return _find_related_fts(conn, rec_number, limit=limit)


def _find_related_fts(
    conn: sqlite3.Connection,
    rec_number: int,
    *,
    limit: int = 10,
) -> list[dict]:
    """Find related references using FTS5 keyword matching (fallback)."""
    target = get_reference_details(conn, rec_number)
    if target is None:
        return []

    # Collect query terms from keywords and title
    terms: list[str] = []

    # Keywords are the strongest signal
    keywords = target.get("keywords", [])
    terms.extend(keywords)

    # Add meaningful title words (skip short/common words)
    _stopwords = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall", "not",
        "no", "nor", "so", "if", "then", "than", "that", "this", "these",
        "those", "it", "its", "into", "upon", "about", "between", "through",
        "during", "before", "after", "above", "below", "each", "every",
        "all", "both", "few", "more", "most", "other", "some", "such",
        "only", "own", "same", "also", "just", "how", "what", "which",
        "who", "whom", "why", "where", "when", "up", "out", "over", "under",
        "again", "further", "once", "here", "there", "any", "very", "using",
        "based", "study", "case", "analysis", "approach", "review", "new",
    }
    if target.get("title"):
        title_words = [
            w for w in target["title"].split()
            if len(w) > 2 and w.lower().strip(".:,;!?()") not in _stopwords
        ]
        terms.extend(title_words[:8])

    if not terms:
        return []

    # Build an OR query for FTS5
    fts_query = " OR ".join(
        f'"{t.replace(chr(34), "")}"' for t in terms if t.strip()
    )
    if not fts_query:
        return []

    sql = """
        SELECT
            r.rec_number,
            r.title,
            r.authors,
            r.year,
            r.journal,
            r.ref_type,
            r.doi,
            r.keywords,
            bm25(references_fts, 10.0, 5.0, 3.0, 8.0, 2.0) AS rank
        FROM references_fts
        JOIN references_ r ON r.rec_number = references_fts.rowid
        WHERE references_fts MATCH ?
          AND r.rec_number != ?
        ORDER BY rank
        LIMIT ?
    """
    rows = conn.execute(sql, [fts_query, rec_number, limit]).fetchall()
    return [_row_to_ref_summary(row) for row in rows]


def get_references_batch(
    conn: sqlite3.Connection,
    rec_numbers: list[int],
) -> list[dict]:
    """Get full metadata for multiple references in one query.

    Returns dicts in the same format as ``get_reference_details``,
    ordered by the input ``rec_numbers`` list.
    """
    if not rec_numbers:
        return []

    placeholders = ",".join("?" for _ in rec_numbers)
    rows = conn.execute(
        f"SELECT * FROM references_ WHERE rec_number IN ({placeholders})",
        rec_numbers,
    ).fetchall()

    # Index by rec_number for ordering
    by_rn: dict[int, dict] = {}
    for row in rows:
        ref = dict(row)
        ref["authors"] = json.loads(ref["authors"]) if ref["authors"] else []
        ref["keywords"] = json.loads(ref["keywords"]) if ref["keywords"] else []
        by_rn[ref["rec_number"]] = ref

    # Return in the order requested
    return [by_rn[rn] for rn in rec_numbers if rn in by_rn]


def _parse_json_list(val: str) -> list[str]:
    try:
        return json.loads(val) if val else []
    except (json.JSONDecodeError, TypeError):
        return []
