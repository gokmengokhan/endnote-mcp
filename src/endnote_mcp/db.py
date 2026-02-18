"""SQLite schema with FTS5 full-text search indexes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the database and ensure the schema exists."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_schema(conn)
    return conn


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
            notes        TEXT,
            pdf_path     TEXT           -- relative to pdf_dir
        );

        -- FTS5 index over reference metadata (weighted BM25)
        CREATE VIRTUAL TABLE IF NOT EXISTS references_fts USING fts5(
            title,
            authors,
            abstract,
            keywords,
            journal,
            content='references_',
            content_rowid='rec_number',
            tokenize='porter unicode61'
        );

        -- Triggers to keep references_fts in sync
        CREATE TRIGGER IF NOT EXISTS references_ai AFTER INSERT ON references_
        BEGIN
            INSERT INTO references_fts(rowid, title, authors, abstract, keywords, journal)
            VALUES (NEW.rec_number, NEW.title, NEW.authors, NEW.abstract, NEW.keywords, NEW.journal);
        END;

        CREATE TRIGGER IF NOT EXISTS references_ad AFTER DELETE ON references_
        BEGIN
            INSERT INTO references_fts(references_fts, rowid, title, authors, abstract, keywords, journal)
            VALUES ('delete', OLD.rec_number, OLD.title, OLD.authors, OLD.abstract, OLD.keywords, OLD.journal);
        END;

        CREATE TRIGGER IF NOT EXISTS references_au AFTER UPDATE ON references_
        BEGIN
            INSERT INTO references_fts(references_fts, rowid, title, authors, abstract, keywords, journal)
            VALUES ('delete', OLD.rec_number, OLD.title, OLD.authors, OLD.abstract, OLD.keywords, OLD.journal);
            INSERT INTO references_fts(rowid, title, authors, abstract, keywords, journal)
            VALUES (NEW.rec_number, NEW.title, NEW.authors, NEW.abstract, NEW.keywords, NEW.journal);
        END;

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
    """Insert or replace a reference record."""
    conn.execute("""
        INSERT OR REPLACE INTO references_(
            rec_number, ref_type, title, authors, year, journal,
            volume, issue, pages, abstract, keywords, doi, url,
            publisher, place_published, edition, isbn, label, notes, pdf_path
        ) VALUES (
            :rec_number, :ref_type, :title, :authors, :year, :journal,
            :volume, :issue, :pages, :abstract, :keywords, :doi, :url,
            :publisher, :place_published, :edition, :isbn, :label, :notes, :pdf_path
        )
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
