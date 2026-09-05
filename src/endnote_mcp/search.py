"""FTS5-backed search engine for references and PDF content."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import OrderedDict
from typing import Any

from endnote_mcp.db import FTS_COLUMNS, FTS_WEIGHTS, NOISY_FTS_COLUMNS

# Derived from db.FTS_WEIGHTS so the ranking weights cannot drift out of step
# with the index columns.
_BM25_RANK = "bm25(references_fts, " + ", ".join(str(w) for w in FTS_WEIGHTS) + ")"

# The columns searched when the user has not opted into noisy ones.
_DEFAULT_SCOPE = "{" + " ".join(
    c for c in FTS_COLUMNS if c not in NOISY_FTS_COLUMNS
) + "}"


def _scope(fts_query: str, *, search_notes: bool) -> str:
    """Restrict a MATCH expression to the columns worth searching.

    EndNote's Notes field is indexed but excluded by default, so imported
    affiliations and thesaurus terms do not surface as matches.
    """
    if search_notes:
        return fts_query
    return f"{_DEFAULT_SCOPE} : ({fts_query})"


# Explicit FTS5 boolean operators. FTS5 only recognises them in uppercase, so
# lowercase "and"/"or"/"not" stay ordinary search words.
_FTS_OPERATORS = frozenset({"AND", "OR", "NOT"})

_FTS_TOKEN_RE = re.compile(
    r'"(?P<phrase>[^"]*)"?'  # quoted phrase; the closing quote may be missing
    r'|(?P<paren>[()])'
    r'|(?P<word>[^\s()"]+)'
)


def build_fts_query(query: str) -> str:
    """Turn free-text user input into a safe FTS5 MATCH expression.

    Bare terms are wrapped in double quotes so characters FTS5 reads as syntax
    — hyphens, colons, punctuation — are matched literally rather than raising
    ``no such column: ...``.  Quoted phrases, the uppercase operators ``AND``,
    ``OR`` and ``NOT``, parentheses and a trailing ``*`` prefix marker are all
    preserved; anything that would leave the expression malformed (a dangling
    operator, an unbalanced or empty parenthesis) is dropped.

    Column filters (``title:foo``) and ``NEAR()`` are not supported — they are
    matched as literal text.  Returns "" when nothing searchable remains.
    """
    # Each stack frame is one parenthesised group of (kind, text) tokens,
    # where kind is "term" or "op".
    stack: list[list[tuple[str, str]]] = [[]]

    for match in _FTS_TOKEN_RE.finditer(query):
        paren = match.group("paren")
        if paren == "(":
            stack.append([])
            continue
        if paren == ")":
            if len(stack) > 1:  # a stray ")" is simply dropped
                _close_group(stack)
            continue

        phrase = match.group("phrase")
        if phrase is not None:
            _add_term(stack[-1], _quote(phrase))
            continue

        word = match.group("word")
        if word in _FTS_OPERATORS:
            _add_operator(stack[-1], word)
            continue

        is_prefix = word.endswith("*")
        term = _quote(word.rstrip("*") if is_prefix else word)
        if term:
            _add_term(stack[-1], term + "*" if is_prefix else term)

    while len(stack) > 1:  # close whatever the user left open
        _close_group(stack)

    tokens = stack[0]
    _drop_trailing_operators(tokens)
    return " ".join(text for _, text in tokens)


def _quote(text: str) -> str:
    """Quote a term as an FTS5 phrase, or return "" if it holds no tokens."""
    if not any(ch.isalnum() for ch in text):
        return ""
    return '"' + text.replace('"', '""') + '"'


def _add_term(tokens: list[tuple[str, str]], text: str) -> None:
    if not text:
        return
    # FTS5 only allows implicit AND between bare phrases, not around a
    # parenthesised group, so spell every conjunction out.
    if tokens and tokens[-1][0] == "term":
        tokens.append(("op", "AND"))
    tokens.append(("term", text))


def _add_operator(tokens: list[tuple[str, str]], op: str) -> None:
    if not tokens:
        return  # an operator needs a left operand
    if tokens[-1][0] == "op":
        # Keep the last of a run, so the common "a AND NOT b" still excludes b.
        tokens[-1] = ("op", op)
    else:
        tokens.append(("op", op))


def _drop_trailing_operators(tokens: list[tuple[str, str]]) -> None:
    while tokens and tokens[-1][0] == "op":
        tokens.pop()


def _close_group(stack: list[list[tuple[str, str]]]) -> None:
    """Pop the innermost group and fold it into its parent, unless it is empty."""
    group = stack.pop()
    _drop_trailing_operators(group)
    if group:
        _add_term(stack[-1], "(" + " ".join(text for _, text in group) + ")")


def search_references(
    conn: sqlite3.Connection,
    query: str,
    *,
    year_from: str | None = None,
    year_to: str | None = None,
    author: str | None = None,
    ref_type: str | None = None,
    limit: int = 50,
    search_notes: bool = False,
) -> list[dict]:
    """Search reference metadata using FTS5 with BM25 ranking.

    The FTS5 columns are weighted: title (10), keywords (8), research notes
    (6), authors (5), abstract (3), journal (2), notes (1).  The EndNote Notes
    field only participates when *search_notes* is true.
    """
    fts_query = build_fts_query(query)
    if not fts_query:
        return []
    fts_query = _scope(fts_query, search_notes=search_notes)

    sql = f"""
        SELECT
            r.rec_number,
            r.title,
            r.authors,
            r.year,
            r.journal,
            r.ref_type,
            r.doi,
            r.keywords,
            {_BM25_RANK} AS rank
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
    if ref_type:
        sql += " AND r.ref_type LIKE ?"
        params.append(f"%{ref_type}%")

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
    fts_query = build_fts_query(query)
    if not fts_query:
        return []

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
            r.doi,
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
                "doi": row["doi"] or "",
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
    ref_type: str | None = None,
    limit: int = 50,
    search_notes: bool = False,
) -> list[dict]:
    """List references matching a broad topic across keywords, title, abstract."""
    fts_query = build_fts_query(topic)
    if not fts_query:
        return []
    fts_query = _scope(fts_query, search_notes=search_notes)

    sql = f"""
        SELECT
            r.rec_number,
            r.title,
            r.authors,
            r.year,
            r.journal,
            r.ref_type,
            r.doi,
            r.keywords,
            {_BM25_RANK} AS rank
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
    if ref_type:
        sql += " AND r.ref_type LIKE ?"
        params.append(f"%{ref_type}%")

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
    ref_type: str | None = None,
    limit: int = 30,
    search_notes: bool = False,
) -> list[dict]:
    """Combined search across metadata, PDF content, and semantic similarity.

    Runs ``search_references``, ``search_fulltext``, and (when available)
    ``search_semantic``, then merges results by ``rec_number``.  References
    that appear in more result sets are ranked higher.
    """
    meta_results = search_references(
        conn, query, year_from=year_from, year_to=year_to, author=author,
        ref_type=ref_type, limit=limit, search_notes=search_notes,
    )
    ft_results = search_fulltext(conn, query, limit=limit)

    # Try semantic search if available
    sem_by_rn: dict[int, dict] = {}
    try:
        from endnote_mcp import embeddings
        if embeddings.is_available() and embeddings.has_embeddings(conn):
            sem_results = search_semantic(conn, query, limit=limit)
            sem_by_rn = {r["rec_number"]: r for r in sem_results}
    except Exception:
        pass

    # Index fulltext results by rec_number for fast lookup
    ft_by_rn: dict[int, dict] = {r["rec_number"]: r for r in ft_results}

    # Score each reference by how many search methods found it
    all_rns: OrderedDict[int, dict] = OrderedDict()

    # Process metadata results first (preserves BM25 order)
    for ref in meta_results:
        rn = ref["rec_number"]
        ft = ft_by_rn.get(rn)
        sem = sem_by_rn.get(rn)
        score = 1 + (1 if ft else 0) + (1 if sem else 0)
        entry = {**ref, "snippets": ft["snippets"] if ft else [], "_score": score}
        if sem:
            entry["similarity"] = sem.get("similarity")
        all_rns[rn] = entry

    # Add fulltext-only results
    for rn, ft in ft_by_rn.items():
        if rn not in all_rns:
            sem = sem_by_rn.get(rn)
            score = 1 + (1 if sem else 0)
            entry = {**ft, "_score": score}
            if sem:
                entry["similarity"] = sem.get("similarity")
            all_rns[rn] = entry

    # Add semantic-only results
    for rn, sem in sem_by_rn.items():
        if rn not in all_rns:
            entry = {**sem, "snippets": [], "_score": 1}
            all_rns[rn] = entry

    # Sort by score (descending), then preserve original order within each tier
    merged = sorted(all_rns.values(), key=lambda r: -r["_score"])

    # Remove internal score key
    for r in merged:
        r.pop("_score", None)

    return merged[:limit]


def _row_to_ref_summary(row: sqlite3.Row) -> dict:
    """Convert a DB row to a summary dict for display."""
    result = {
        "rec_number": row["rec_number"],
        "title": row["title"],
        "authors": _parse_authors_short(row["authors"]),
        "year": row["year"],
        "journal": row["journal"],
        "ref_type": row["ref_type"],
        "keywords": _parse_json_list(row["keywords"] if "keywords" in row.keys() else "[]"),
    }
    if "doi" in row.keys():
        result["doi"] = row["doi"] or ""
    return result


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

    # Build an OR query for FTS5; build_fts_query drops any term that would
    # leave the expression malformed.
    fts_query = build_fts_query(
        " OR ".join(f'"{t.replace(chr(34), "")}"' for t in terms if t.strip())
    )
    if not fts_query:
        return []
    # Always scoped: this is a similarity lookup with no user intent behind it,
    # so matching against imported note residue would only add noise.
    fts_query = _scope(fts_query, search_notes=False)

    sql = f"""
        SELECT
            r.rec_number,
            r.title,
            r.authors,
            r.year,
            r.journal,
            r.ref_type,
            r.doi,
            r.keywords,
            {_BM25_RANK} AS rank
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
