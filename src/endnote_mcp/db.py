"""SQLite schema with FTS5 full-text search indexes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Bumped whenever the on-disk schema changes; see _migrate().
#   1 - initial schema
#   2 - research_notes column; research_notes + notes added to references_fts
SCHEMA_VERSION = 2

# The FTS5 index columns and their BM25 weights, in order. Both the schema and
# the search queries are generated from these, so a column can never be added
# in one place and forgotten in another.
FTS_COLUMNS = (
    "title",
    "authors",
    "abstract",
    "keywords",
    "journal",
    "research_notes",
    "notes",
)
FTS_WEIGHTS = (10.0, 5.0, 3.0, 8.0, 2.0, 6.0, 1.0)

# EndNote's Notes field is where reference managers dump import residue —
# author affiliations, email addresses, thesaurus terms — so it is indexed but
# excluded from matching unless the user opts in (config: search_notes).
NOISY_FTS_COLUMNS = ("notes",)


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the database and ensure the schema is up to date."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    _migrate(conn)
    return conn


def _references_fts_sql() -> str:
    """Build the references_fts table and its sync triggers from FTS_COLUMNS."""
    cols = ", ".join(FTS_COLUMNS)
    new_vals = ", ".join(f"NEW.{c}" for c in FTS_COLUMNS)
    old_vals = ", ".join(f"OLD.{c}" for c in FTS_COLUMNS)
    return f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS references_fts USING fts5(
            {cols},
            content='references_',
            content_rowid='rec_number',
            tokenize='porter unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS references_ai AFTER INSERT ON references_
        BEGIN
            INSERT INTO references_fts(rowid, {cols})
            VALUES (NEW.rec_number, {new_vals});
        END;

        CREATE TRIGGER IF NOT EXISTS references_ad AFTER DELETE ON references_
        BEGIN
            INSERT INTO references_fts(references_fts, rowid, {cols})
            VALUES ('delete', OLD.rec_number, {old_vals});
        END;

        CREATE TRIGGER IF NOT EXISTS references_au AFTER UPDATE ON references_
        BEGIN
            INSERT INTO references_fts(references_fts, rowid, {cols})
            VALUES ('delete', OLD.rec_number, {old_vals});
            INSERT INTO references_fts(rowid, {cols})
            VALUES (NEW.rec_number, {new_vals});
        END;
    """


def _fts_columns(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Return the current column names of references_fts, or () if absent."""
    try:
        rows = conn.execute("PRAGMA table_info(references_fts)").fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(row["name"] for row in rows)


def _rebuild_references_fts(conn: sqlite3.Connection) -> None:
    """Recreate references_fts with the current column set and repopulate it.

    Only the reference metadata index is touched — pdf_fts, which holds the
    bulk of the data, is left alone, so this stays fast even on large
    libraries.
    """
    conn.executescript("""
        DROP TRIGGER IF EXISTS references_ai;
        DROP TRIGGER IF EXISTS references_ad;
        DROP TRIGGER IF EXISTS references_au;
        DROP TABLE IF EXISTS references_fts;
    """)
    conn.executescript(_references_fts_sql())
    conn.execute("INSERT INTO references_fts(references_fts) VALUES('rebuild')")


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to SCHEMA_VERSION.

    Each step checks the live schema rather than trusting the version stamp,
    so it is safe to run against a database created before user_version was
    recorded (every release up to 1.4.9 left it at 0).
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(references_)")}
    if "research_notes" not in columns:
        conn.execute("ALTER TABLE references_ ADD COLUMN research_notes TEXT")

    if _fts_columns(conn) != FTS_COLUMNS:
        _rebuild_references_fts(conn)

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        -- Main references table
        CREATE TABLE IF NOT EXISTS references_ (
            rec_number   INTEGER PRIMARY KEY,
            ref_type     TEXT,
            title        TEXT,
            authors      TEXT,          -- JSON array of author names
            year         TEXT,
            journal      TEXT,
            volume       TEXT,
            issue        TEXT,
            pages        TEXT,
            abstract     TEXT,
            keywords     TEXT,          -- JSON array
            doi          TEXT,
            url          TEXT,
            publisher    TEXT,
            place_published TEXT,
            edition      TEXT,
            isbn         TEXT,
            label        TEXT,
            notes        TEXT,          -- EndNote Notes (often import residue)
            research_notes TEXT,        -- EndNote Research Notes (user's own)
            pdf_path     TEXT           -- relative to pdf_dir
        );

    """)

    # references_fts and its triggers are generated from FTS_COLUMNS.
    conn.executescript(_references_fts_sql())

    conn.executescript("""
        -- PDF page content
        CREATE TABLE IF NOT EXISTS pdf_pages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_number   INTEGER NOT NULL REFERENCES references_(rec_number) ON DELETE CASCADE,
            page_number  INTEGER NOT NULL,
            text_content TEXT,
            UNIQUE(rec_number, page_number)
        );

        -- FTS5 index over PDF text
        CREATE VIRTUAL TABLE IF NOT EXISTS pdf_fts USING fts5(
            text_content,
            content='pdf_pages',
            content_rowid='id',
            tokenize='porter unicode61'
        );

        -- Triggers for pdf_fts sync
        CREATE TRIGGER IF NOT EXISTS pdf_pages_ai AFTER INSERT ON pdf_pages
        BEGIN
            INSERT INTO pdf_fts(rowid, text_content)
            VALUES (NEW.id, NEW.text_content);
        END;

        CREATE TRIGGER IF NOT EXISTS pdf_pages_ad AFTER DELETE ON pdf_pages
        BEGIN
            INSERT INTO pdf_fts(pdf_fts, rowid, text_content)
            VALUES ('delete', OLD.id, OLD.text_content);
        END;

        CREATE TRIGGER IF NOT EXISTS pdf_pages_au AFTER UPDATE ON pdf_pages
        BEGIN
            INSERT INTO pdf_fts(pdf_fts, rowid, text_content)
            VALUES ('delete', OLD.id, OLD.text_content);
            INSERT INTO pdf_fts(rowid, text_content)
            VALUES (NEW.id, NEW.text_content);
        END;

        -- Indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_references_year ON references_(year);
        CREATE INDEX IF NOT EXISTS idx_references_doi ON references_(doi);
        CREATE INDEX IF NOT EXISTS idx_pdf_pages_rec ON pdf_pages(rec_number);

        -- Embedding vectors for semantic search
        CREATE TABLE IF NOT EXISTS reference_embeddings (
            rec_number  INTEGER PRIMARY KEY REFERENCES references_(rec_number) ON DELETE CASCADE,
            embedding   BLOB NOT NULL,
            model_name  TEXT NOT NULL
        );
    """)


def upsert_reference(conn: sqlite3.Connection, ref: dict) -> None:
    """Insert or update a reference record.

    Uses ON CONFLICT DO UPDATE instead of INSERT OR REPLACE to avoid
    triggering ON DELETE CASCADE on pdf_pages and reference_embeddings.
    """
    conn.execute("""
        INSERT INTO references_(
            rec_number, ref_type, title, authors, year, journal,
            volume, issue, pages, abstract, keywords, doi, url,
            publisher, place_published, edition, isbn, label, notes,
            research_notes, pdf_path
        ) VALUES (
            :rec_number, :ref_type, :title, :authors, :year, :journal,
            :volume, :issue, :pages, :abstract, :keywords, :doi, :url,
            :publisher, :place_published, :edition, :isbn, :label, :notes,
            :research_notes, :pdf_path
        )
        ON CONFLICT(rec_number) DO UPDATE SET
            ref_type=excluded.ref_type, title=excluded.title,
            authors=excluded.authors, year=excluded.year,
            journal=excluded.journal, volume=excluded.volume,
            issue=excluded.issue, pages=excluded.pages,
            abstract=excluded.abstract, keywords=excluded.keywords,
            doi=excluded.doi, url=excluded.url,
            publisher=excluded.publisher, place_published=excluded.place_published,
            edition=excluded.edition, isbn=excluded.isbn,
            label=excluded.label, notes=excluded.notes,
            research_notes=excluded.research_notes,
            pdf_path=excluded.pdf_path
    """, ref)


def insert_pdf_page(conn: sqlite3.Connection, rec_number: int, page_number: int, text: str) -> None:
    """Insert a single PDF page's text."""
    conn.execute("""
        INSERT OR REPLACE INTO pdf_pages(rec_number, page_number, text_content)
        VALUES (?, ?, ?)
    """, (rec_number, page_number, text))


def clear_all(conn: sqlite3.Connection) -> None:
    """Drop all data for a full re-index."""
    conn.executescript("""
        DELETE FROM reference_embeddings;
        DELETE FROM pdf_pages;
        DELETE FROM references_;
        -- Rebuild FTS indexes
        INSERT INTO references_fts(references_fts) VALUES('rebuild');
        INSERT INTO pdf_fts(pdf_fts) VALUES('rebuild');
    """)


def upsert_embedding(conn: sqlite3.Connection, rec_number: int, embedding: bytes, model_name: str) -> None:
    """Insert or replace an embedding vector for a reference."""
    conn.execute(
        "INSERT OR REPLACE INTO reference_embeddings(rec_number, embedding, model_name) VALUES (?, ?, ?)",
        (rec_number, embedding, model_name),
    )


def clear_embeddings(conn: sqlite3.Connection) -> None:
    """Delete all embeddings."""
    conn.execute("DELETE FROM reference_embeddings")
    conn.commit()


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return index statistics."""
    ref_count = conn.execute("SELECT COUNT(*) FROM references_").fetchone()[0]
    pdf_page_count = conn.execute("SELECT COUNT(*) FROM pdf_pages").fetchone()[0]
    refs_with_pdf = conn.execute(
        "SELECT COUNT(DISTINCT rec_number) FROM pdf_pages"
    ).fetchone()[0]
    embeddings_count = conn.execute("SELECT COUNT(*) FROM reference_embeddings").fetchone()[0]
    return {
        "total_references": ref_count,
        "total_pdf_pages": pdf_page_count,
        "references_with_pdf": refs_with_pdf,
        "references_with_embeddings": embeddings_count,
    }
