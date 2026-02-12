#!/usr/bin/env python3
"""Index an EndNote library into SQLite for MCP search.

Usage:
    python scripts/index_library.py                # Incremental (default) — only new/changed
    python scripts/index_library.py --full         # Full re-index from scratch
    python scripts/index_library.py --skip-pdfs    # Metadata only, skip PDF extraction
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to path so imports work when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from endnote_mcp.config import Config
from endnote_mcp.db import connect, clear_all, upsert_reference, insert_pdf_page, get_stats
from endnote_mcp.endnote_parser import parse_endnote_xml
from endnote_mcp.pdf_indexer import extract_pages, find_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _get_indexed_rec_numbers(conn) -> set[int]:
    """Return set of rec_numbers that already have PDF pages indexed."""
    rows = conn.execute("SELECT DISTINCT rec_number FROM pdf_pages").fetchall()
    return {row[0] for row in rows}


def main():
    parser = argparse.ArgumentParser(description="Index an EndNote library into SQLite.")
    parser.add_argument("--config", type=str, help="Path to config.yaml")
    parser.add_argument("--skip-pdfs", action="store_true", help="Skip PDF text extraction")
    parser.add_argument("--full", action="store_true", help="Full re-index (clear all data first)")
    args = parser.parse_args()

    cfg = Config.load(args.config)

    logger.info("EndNote XML: %s", cfg.endnote_xml)
    logger.info("PDF directory: %s", cfg.pdf_dir)
    logger.info("Database: %s", cfg.db_path)
    logger.info("Mode: %s", "FULL re-index" if args.full else "INCREMENTAL (new/changed only)")

    if not cfg.endnote_xml.exists():
        logger.error("EndNote XML file not found: %s", cfg.endnote_xml)
        sys.exit(1)

    conn = connect(cfg.db_path)

    if args.full:
        logger.info("Clearing existing data...")
        clear_all(conn)

    # --- Phase 1: Parse XML (always upserts — new records added, existing updated) ---
    logger.info("Parsing EndNote XML...")
    t0 = time.time()
    ref_count = 0
    pdf_refs = []

    for ref in parse_endnote_xml(cfg.endnote_xml):
        upsert_reference(conn, ref)
        ref_count += 1
        if ref.get("pdf_path"):
            pdf_refs.append((ref["rec_number"], ref["pdf_path"]))
        if ref_count % 500 == 0:
            conn.commit()
            logger.info("  ...parsed %d references", ref_count)

    conn.commit()
    xml_time = time.time() - t0
    logger.info("Parsed %d references in %.1f seconds.", ref_count, xml_time)
    logger.info("  %d references have PDF attachments.", len(pdf_refs))

    # --- Phase 2: Extract PDF text ---
    if not args.skip_pdfs and pdf_refs:
        # Find which PDFs are already indexed (skip them in incremental mode)
        already_indexed = set()
        if not args.full:
            already_indexed = _get_indexed_rec_numbers(conn)
            if already_indexed:
                logger.info("  %d PDFs already indexed — skipping those.", len(already_indexed))

        new_pdf_refs = [
            (rec, pdf) for rec, pdf in pdf_refs if rec not in already_indexed
        ]

        if not new_pdf_refs:
            logger.info("No new PDFs to index.")
        else:
            logger.info("Extracting text from %d new PDFs...", len(new_pdf_refs))
            t0 = time.time()
            pdf_ok = 0
            pdf_fail = 0
            total_pages = 0

            for i, (rec_number, pdf_filename) in enumerate(new_pdf_refs, 1):
                pdf_path = find_pdf(cfg.pdf_dir, pdf_filename)
                if pdf_path is None:
                    pdf_fail += 1
                    if pdf_fail <= 10:
                        logger.warning("  PDF not found: %s (ref #%d)", pdf_filename, rec_number)
                    continue

                try:
                    page_count = 0
                    for page_num, text in extract_pages(pdf_path):
                        insert_pdf_page(conn, rec_number, page_num, text)
                        page_count += 1
                    total_pages += page_count
                    pdf_ok += 1
                except Exception as e:
                    pdf_fail += 1
                    if pdf_fail <= 10:
                        logger.warning("  Error extracting %s: %s", pdf_filename, e)

                if i % 100 == 0:
                    conn.commit()
                    elapsed = time.time() - t0
                    rate = i / elapsed if elapsed > 0 else 0
                    eta = (len(new_pdf_refs) - i) / rate if rate > 0 else 0
                    logger.info(
                        "  ...processed %d/%d PDFs (%.0f/sec, ETA: %.0f min)",
                        i, len(new_pdf_refs), rate, eta / 60,
                    )

            conn.commit()
            pdf_time = time.time() - t0
            logger.info(
                "PDF extraction done: %d OK, %d failed, %d total pages in %.1f seconds.",
                pdf_ok, pdf_fail, total_pages, pdf_time,
            )
    elif args.skip_pdfs:
        logger.info("Skipping PDF extraction (--skip-pdfs).")

    # --- Summary ---
    stats = get_stats(conn)
    logger.info("=== Indexing Complete ===")
    logger.info("  Total references: %d", stats["total_references"])
    logger.info("  References with PDF: %d", stats["references_with_pdf"])
    logger.info("  Total PDF pages indexed: %d", stats["total_pdf_pages"])
    logger.info("  Database: %s", cfg.db_path)

    conn.close()


if __name__ == "__main__":
    main()
