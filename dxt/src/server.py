#!/usr/bin/env python3
"""Claude Desktop Extension entry point for endnote-mcp.

Translates user_config env vars (set by Claude Desktop) into a config.yaml,
runs a fast synchronous metadata index so the MCP server is responsive within
seconds, then kicks off PDF text extraction and semantic embeddings in a
background thread before handing off to the MCP server's stdio loop.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

# Make the vendored endnote_mcp package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from endnote_mcp.config import Config, get_config_dir, get_default_config_path  # noqa: E402


def _log(msg: str) -> None:
    """stderr is forwarded to Claude Desktop's MCP log viewer."""
    print(f"[endnote-mcp] {msg}", file=sys.stderr, flush=True)


def _truthy(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.lower() not in ("false", "0", "no", "off")


def _bootstrap_config() -> Path:
    xml_env = os.environ.get("ENDNOTE_XML", "").strip()
    pdf_env = os.environ.get("ENDNOTE_PDF_DIR", "").strip()

    if not xml_env or not pdf_env:
        _log("ERROR: extension is not configured.")
        _log("Open Claude Desktop → Settings → Extensions → EndNote Library and set:")
        _log("  • EndNote XML Export (file)")
        _log("  • PDF Attachments Folder (directory)")
        sys.exit(1)

    xml_path = Path(xml_env).expanduser().resolve()
    pdf_dir = Path(pdf_env).expanduser().resolve()

    if not xml_path.exists():
        _log(f"ERROR: EndNote XML file not found: {xml_path}")
        sys.exit(1)
    if not pdf_dir.exists():
        _log(f"ERROR: PDF directory not found: {pdf_dir}")
        sys.exit(1)

    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_default_config_path()

    try:
        max_pages = int(os.environ.get("ENDNOTE_MAX_PDF_PAGES") or 30)
    except ValueError:
        max_pages = 30

    config = {
        "endnote_xml": str(xml_path),
        "pdf_dir": str(pdf_dir),
        "db_path": str(config_dir / "library.db"),
        "max_pdf_pages": max_pages,
    }
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    _log(f"Config:  {config_path}")
    _log(f"  XML:     {xml_path}")
    _log(f"  PDFs:    {pdf_dir}")
    _log(f"  DB:      {config['db_path']}")
    return config_path


def _xml_newer_than_db(cfg: Config) -> bool:
    if not cfg.db_path.exists():
        return True
    try:
        return cfg.endnote_xml.stat().st_mtime > cfg.db_path.stat().st_mtime
    except OSError:
        return True


def _index_metadata_sync(cfg: Config) -> int:
    """Parse XML and upsert reference rows. Fast — completes in seconds for thousands of refs."""
    from endnote_mcp.db import connect, upsert_reference
    from endnote_mcp.endnote_parser import parse_endnote_xml

    conn = connect(cfg.db_path)
    ref_count = 0
    pdf_count = 0
    for ref in parse_endnote_xml(cfg.endnote_xml):
        upsert_reference(conn, ref)
        ref_count += 1
        if ref.get("pdf_path"):
            pdf_count += 1
        if ref_count % 1000 == 0:
            conn.commit()
    conn.commit()
    conn.close()
    _log(f"Indexed {ref_count} references ({pdf_count} have PDFs).")
    return ref_count


def _background_index(cfg: Config, *, do_pdfs: bool, do_embeddings: bool) -> None:
    """PDF text extraction + semantic embeddings. Runs in a background thread."""
    try:
        if do_pdfs:
            _extract_pending_pdfs(cfg)
        if do_embeddings:
            _embed_pending_references(cfg)
        _log("Background indexing complete.")
    except Exception as e:
        _log(f"Background indexing error: {e}")


def _extract_pending_pdfs(cfg: Config) -> None:
    from endnote_mcp.db import connect, insert_pdf_page
    from endnote_mcp.pdf_indexer import extract_pages, find_pdf

    conn = connect(cfg.db_path)
    rows = conn.execute(
        """
        SELECT r.rec_number, r.pdf_path
        FROM references_ r
        WHERE r.pdf_path IS NOT NULL AND r.pdf_path != ''
          AND r.rec_number NOT IN (SELECT rec_number FROM pdf_pages)
        """
    ).fetchall()

    if not rows:
        conn.close()
        return

    _log(f"Background: extracting text from {len(rows)} PDFs (this can take a while)...")

    max_size = 200 * 1024 * 1024
    ok = fail = skipped = total_pages = 0

    for i, row in enumerate(rows, 1):
        rec_number = row["rec_number"]
        pdf_path = find_pdf(cfg.pdf_dir, row["pdf_path"])
        if pdf_path is None:
            fail += 1
            continue
        try:
            size = pdf_path.stat().st_size
        except OSError:
            fail += 1
            continue
        if size > max_size:
            skipped += 1
            continue

        timeout = 120 if size > 50 * 1024 * 1024 else 30
        try:
            pages = 0
            for page_num, text in extract_pages(pdf_path, timeout=timeout):
                insert_pdf_page(conn, rec_number, page_num, text)
                pages += 1
            total_pages += pages
            ok += 1
        except Exception:
            fail += 1

        if i % 25 == 0:
            conn.commit()
            _log(f"  PDFs: {ok} ok / {fail} failed / {skipped} skipped (of {i}/{len(rows)})")

    conn.commit()
    conn.close()
    _log(f"PDFs: {ok} extracted ({total_pages} pages), {fail} failed, {skipped} skipped (>200 MB).")


def _embed_pending_references(cfg: Config) -> None:
    try:
        from endnote_mcp import embeddings
    except Exception as e:
        _log(f"Semantic search unavailable ({e}); skipping embeddings.")
        return

    if not embeddings.is_available():
        _log("Semantic search dependencies not installed; skipping embeddings.")
        return

    from endnote_mcp.db import connect, upsert_embedding

    conn = connect(cfg.db_path)
    rows = conn.execute(
        """
        SELECT r.rec_number, r.title, r.abstract, r.keywords
        FROM references_ r
        WHERE r.rec_number NOT IN (SELECT rec_number FROM reference_embeddings)
        """
    ).fetchall()

    if not rows:
        conn.close()
        return

    _log(f"Background: generating semantic embeddings for {len(rows)} references...")
    _log(f"Loading embedding model {embeddings.MODEL_NAME} (downloads ~100 MB on first use)...")
    model = embeddings.load_model()

    batch_size = 64
    embedded = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        texts: list[str] = []
        rec_numbers: list[int] = []
        for row in batch:
            text = embeddings.build_search_text({
                "title": row["title"],
                "abstract": row["abstract"],
                "keywords": row["keywords"],
            })
            if text.strip():
                texts.append(text)
                rec_numbers.append(row["rec_number"])
        if texts:
            blobs = embeddings.encode_batch(model, texts)
            for rn, blob in zip(rec_numbers, blobs):
                upsert_embedding(conn, rn, blob, embeddings.MODEL_NAME)
            embedded += len(blobs)

        if (i // batch_size) % 4 == 0:
            conn.commit()
            _log(f"  Embeddings: {embedded}/{len(rows)}")

    conn.commit()
    conn.close()
    _log(f"Embeddings: {embedded} generated.")


def main() -> None:
    config_path = _bootstrap_config()
    cfg = Config.load(config_path)

    do_pdfs = _truthy(os.environ.get("ENDNOTE_INDEX_PDFS_ON_FIRST_LAUNCH"), True)
    do_embeddings = _truthy(os.environ.get("ENDNOTE_GENERATE_EMBEDDINGS"), True)

    if _xml_newer_than_db(cfg):
        _log("Indexing reference metadata...")
        _index_metadata_sync(cfg)
    else:
        _log("Metadata index up to date.")

    if do_pdfs or do_embeddings:
        threading.Thread(
            target=_background_index,
            args=(cfg,),
            kwargs={"do_pdfs": do_pdfs, "do_embeddings": do_embeddings},
            daemon=True,
            name="endnote-mcp-bg-index",
        ).start()

    _log("Starting MCP server.")
    from endnote_mcp.server import mcp
    mcp.run()


if __name__ == "__main__":
    main()
