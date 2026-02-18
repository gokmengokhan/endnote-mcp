"""Optional semantic search using sentence-transformers embeddings.

Install with:  pip install endnote-mcp[semantic]
"""

from __future__ import annotations

import json
import logging
import struct
import sqlite3
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model = None


def is_available() -> bool:
    """Check if sentence-transformers is installed."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def load_model(model_name: str = MODEL_NAME):
    """Load the embedding model (cached after first call)."""
    global _model
    if _model is not None:
        return _model

    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model: %s", model_name)
    _model = SentenceTransformer(model_name)
    return _model


def encode_text(model, text: str) -> bytes:
    """Encode a single text string to float32 bytes."""
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32).tobytes()


def encode_batch(model, texts: list[str]) -> list[bytes]:
    """Encode a batch of texts to float32 bytes."""
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=64)
    return [v.astype(np.float32).tobytes() for v in vecs]


def build_search_text(ref: dict) -> str:
    """Combine title + abstract + keywords into embedding input text."""
    parts = []
    if ref.get("title"):
        parts.append(ref["title"])
    if ref.get("abstract"):
        parts.append(ref["abstract"])
    keywords = ref.get("keywords")
    if keywords:
        if isinstance(keywords, str):
            try:
                keywords = json.loads(keywords)
            except (json.JSONDecodeError, TypeError):
                keywords = []
        if keywords:
            parts.append("Keywords: " + ", ".join(keywords))
    return " ".join(parts)


def _blob_to_array(blob: bytes) -> np.ndarray:
    """Convert a float32 bytes blob to a numpy array."""
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embedding blobs."""
    va = _blob_to_array(a)
    vb = _blob_to_array(b)
    # Vectors are already normalized, so dot product = cosine similarity
    return float(np.dot(va, vb))


def search_semantic(
    conn: sqlite3.Connection,
    query_embedding: bytes,
    *,
    limit: int = 20,
) -> list[dict]:
    """Find nearest references by cosine similarity.

    Uses Python-side computation (fast enough for ~4K vectors).
    Returns list of dicts with rec_number, similarity, and metadata.
    """
    rows = conn.execute(
        "SELECT rec_number, embedding FROM reference_embeddings"
    ).fetchall()

    if not rows:
        return []

    query_vec = _blob_to_array(query_embedding)

    # Build matrix of all embeddings for vectorized computation
    rec_numbers = [row["rec_number"] for row in rows]
    matrix = np.stack([_blob_to_array(row["embedding"]) for row in rows])

    # Cosine similarity (vectors are normalized, so just dot product)
    similarities = matrix @ query_vec

    # Get top-k indices
    top_k = min(limit, len(rec_numbers))
    top_indices = np.argpartition(-similarities, top_k)[:top_k]
    top_indices = top_indices[np.argsort(-similarities[top_indices])]

    # Fetch metadata for top results
    results = []
    for idx in top_indices:
        rn = rec_numbers[idx]
        sim = float(similarities[idx])
        if sim < 0.1:  # skip very low similarity
            continue
        row = conn.execute(
            "SELECT rec_number, title, authors, year, journal, ref_type, doi, keywords "
            "FROM references_ WHERE rec_number = ?",
            (rn,),
        ).fetchone()
        if row:
            results.append({
                "rec_number": row["rec_number"],
                "title": row["title"],
                "authors": _parse_authors_short(row["authors"]),
                "year": row["year"],
                "journal": row["journal"],
                "ref_type": row["ref_type"],
                "doi": row["doi"] or "",
                "keywords": _parse_json_list(row["keywords"] if "keywords" in row.keys() else "[]"),
                "similarity": sim,
            })

    return results


def search_by_embedding(
    conn: sqlite3.Connection,
    embedding: bytes,
    *,
    exclude_rec: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """Find nearest references to a given embedding (for find_related)."""
    results = search_semantic(conn, embedding, limit=limit + 1)
    if exclude_rec is not None:
        results = [r for r in results if r["rec_number"] != exclude_rec]
    return results[:limit]


def get_embedding(conn: sqlite3.Connection, rec_number: int) -> bytes | None:
    """Get the stored embedding for a reference."""
    row = conn.execute(
        "SELECT embedding FROM reference_embeddings WHERE rec_number = ?",
        (rec_number,),
    ).fetchone()
    return row["embedding"] if row else None


def has_embeddings(conn: sqlite3.Connection) -> bool:
    """Check if any embeddings exist in the database."""
    count = conn.execute("SELECT COUNT(*) FROM reference_embeddings").fetchone()[0]
    return count > 0


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


def _parse_json_list(val: str) -> list[str]:
    try:
        return json.loads(val) if val else []
    except (json.JSONDecodeError, TypeError):
        return []
