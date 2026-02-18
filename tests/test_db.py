"""Tests for database schema, CRUD, and stats."""

import json

from endnote_mcp.db import (
    upsert_reference,
    insert_pdf_page,
    get_stats,
    clear_all,
    upsert_embedding,
    clear_embeddings,
)


def _make_ref(rec_number=1, title="Test Title", year="2020"):
    """Create a minimal reference dict for DB insertion."""
    return {
        "rec_number": rec_number,
        "ref_type": "Journal Article",
        "title": title,
        "authors": json.dumps(["Smith, J."]),
        "year": year,
        "journal": "Test Journal",
        "volume": "1",
        "issue": "1",
        "pages": "1-10",
        "abstract": "Test abstract.",
        "keywords": json.dumps(["test"]),
        "doi": "10.1234/test",
        "url": "",
        "publisher": "",
        "place_published": "",
        "edition": "",
        "isbn": "",
        "label": "",
        "notes": "",
        "pdf_path": "",
    }


def test_upsert_reference(db_conn):
    upsert_reference(db_conn, _make_ref())
    db_conn.commit()
    row = db_conn.execute("SELECT * FROM references_ WHERE rec_number = 1").fetchone()
    assert row is not None
    assert row["title"] == "Test Title"
    assert row["year"] == "2020"


def test_upsert_reference_update(db_conn):
    upsert_reference(db_conn, _make_ref(title="Original"))
    db_conn.commit()
    upsert_reference(db_conn, _make_ref(title="Updated"))
    db_conn.commit()
    row = db_conn.execute("SELECT title FROM references_ WHERE rec_number = 1").fetchone()
    assert row["title"] == "Updated"


def test_insert_pdf_page(db_conn):
    upsert_reference(db_conn, _make_ref())
    insert_pdf_page(db_conn, 1, 1, "Page one content")
    insert_pdf_page(db_conn, 1, 2, "Page two content")
    db_conn.commit()
    count = db_conn.execute("SELECT COUNT(*) FROM pdf_pages WHERE rec_number = 1").fetchone()[0]
    assert count == 2


def test_get_stats_empty(db_conn):
    stats = get_stats(db_conn)
    assert stats["total_references"] == 0
    assert stats["total_pdf_pages"] == 0
    assert stats["references_with_pdf"] == 0
    assert stats["references_with_embeddings"] == 0


def test_get_stats_populated(db_conn):
    upsert_reference(db_conn, _make_ref(rec_number=1))
    upsert_reference(db_conn, _make_ref(rec_number=2))
    insert_pdf_page(db_conn, 1, 1, "text")
    insert_pdf_page(db_conn, 1, 2, "text")
    db_conn.commit()
    stats = get_stats(db_conn)
    assert stats["total_references"] == 2
    assert stats["total_pdf_pages"] == 2
    assert stats["references_with_pdf"] == 1


def test_clear_all(db_conn):
    upsert_reference(db_conn, _make_ref())
    insert_pdf_page(db_conn, 1, 1, "text")
    db_conn.commit()
    clear_all(db_conn)
    stats = get_stats(db_conn)
    assert stats["total_references"] == 0
    assert stats["total_pdf_pages"] == 0


def test_upsert_embedding(db_conn):
    upsert_reference(db_conn, _make_ref())
    db_conn.commit()
    fake_blob = b"\x00" * (384 * 4)  # 384 float32s
    upsert_embedding(db_conn, 1, fake_blob, "test-model")
    db_conn.commit()
    row = db_conn.execute("SELECT * FROM reference_embeddings WHERE rec_number = 1").fetchone()
    assert row is not None
    assert row["model_name"] == "test-model"
    assert len(row["embedding"]) == 384 * 4


def test_clear_embeddings(db_conn):
    upsert_reference(db_conn, _make_ref())
    db_conn.commit()
    upsert_embedding(db_conn, 1, b"\x00" * (384 * 4), "test-model")
    db_conn.commit()
    clear_embeddings(db_conn)
    stats = get_stats(db_conn)
    assert stats["references_with_embeddings"] == 0


def test_fts_trigger_sync(db_conn):
    upsert_reference(db_conn, _make_ref(title="Unique Quantum Computing Paper"))
    db_conn.commit()
    rows = db_conn.execute(
        "SELECT rowid FROM references_fts WHERE references_fts MATCH 'quantum'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 1
