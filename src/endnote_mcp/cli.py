"""Command-line interface for endnote-mcp.

Commands:
    endnote-mcp setup    — Interactive setup wizard (finds your library, configures paths)
    endnote-mcp index    — Index your library (incremental by default)
    endnote-mcp serve    — Start the MCP server (used by Claude Desktop)
    endnote-mcp status   — Show index statistics
    endnote-mcp install  — Add MCP server to Claude Desktop config
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
from pathlib import Path

import click
import yaml

from endnote_mcp.config import Config, get_config_dir, get_default_config_path


# ====================================================================
# Main group
# ====================================================================
@click.group()
@click.version_option()
def cli():
    """Connect your EndNote library to Claude via MCP.

    Get started:  endnote-mcp setup
    """
    pass


# ====================================================================
# setup — Interactive wizard
# ====================================================================
@cli.command()
def setup():
    """Interactive setup wizard — finds your library and configures everything."""
    click.echo()
    click.secho("  EndNote MCP — Setup Wizard", bold=True)
    click.secho("  Connect your reference library to Claude\n", dim=True)

    config_dir = get_config_dir()
    config_path = get_default_config_path()

    # --- Step 1: Find EndNote XML ---
    click.secho("Step 1: EndNote XML Export", bold=True)
    xml_path = _find_or_ask_xml()
    if xml_path is None:
        click.echo("\nSetup cancelled.")
        return
    click.secho(f"  ✓ {xml_path}\n", fg="green")

    # --- Step 2: Find PDF directory ---
    click.secho("Step 2: PDF Attachments Directory", bold=True)
    pdf_dir = _find_or_ask_pdf_dir(xml_path)
    if pdf_dir is None:
        click.echo("\nSetup cancelled.")
        return
    click.secho(f"  ✓ {pdf_dir}\n", fg="green")

    # --- Step 3: Database location ---
    db_path = config_dir / "library.db"

    # --- Step 4: Save config ---
    config_dir.mkdir(parents=True, exist_ok=True)
    config_data = {
        "endnote_xml": str(xml_path),
        "pdf_dir": str(pdf_dir),
        "db_path": str(db_path),
        "max_pdf_pages": 30,
    }
    with open(config_path, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

    click.secho(f"Configuration saved to: {config_path}\n", fg="green")

    # --- Step 5: Offer to index now ---
    if click.confirm("Index your library now? (metadata takes ~1 sec, PDFs take longer)", default=True):
        skip_pdfs = not click.confirm(
            "Also extract text from PDFs? (enables fulltext search, takes ~1 min per 100 PDFs)",
            default=True,
        )
        click.echo()
        _run_index(config_path, full=True, skip_pdfs=skip_pdfs)

    # --- Step 6: Offer to install into Claude Desktop ---
    click.echo()
    if click.confirm("Add to Claude Desktop automatically?", default=True):
        _install_claude_desktop()

    click.echo()
    click.secho("Setup complete!", bold=True, fg="green")
    click.echo("Restart Claude Desktop, then try asking:")
    click.echo('  "Search my library for scenario planning"')
    click.echo('  "Give me the APA citation for reference #42"')


# ====================================================================
# index — Run indexing
# ====================================================================
@cli.command()
@click.option("--full", is_flag=True, help="Full re-index (clear and rebuild from scratch)")
@click.option("--skip-pdfs", is_flag=True, help="Skip PDF text extraction (metadata only)")
@click.option("--config", type=click.Path(exists=True), help="Path to config.yaml")
def index(full, skip_pdfs, config):
    """Index your EndNote library into the search database.

    By default, runs incrementally — only processes new references and PDFs.
    """
    config_path = config or get_default_config_path()
    if not Path(config_path).exists():
        click.secho("No configuration found. Run 'endnote-mcp setup' first.", fg="red")
        raise SystemExit(1)
    _run_index(config_path, full=full, skip_pdfs=skip_pdfs)


# ====================================================================
# serve — Start MCP server
# ====================================================================
@cli.command()
def serve():
    """Start the MCP server (called by Claude Desktop automatically)."""
    from endnote_mcp.server import mcp as mcp_server
    mcp_server.run()


# ====================================================================
# status — Show stats
# ====================================================================
@cli.command()
@click.option("--config", type=click.Path(exists=True), help="Path to config.yaml")
def status(config):
    """Show index statistics."""
    config_path = config or get_default_config_path()
    if not Path(config_path).exists():
        click.secho("No configuration found. Run 'endnote-mcp setup' first.", fg="red")
        raise SystemExit(1)

    cfg = Config.load(config_path)
    if not cfg.db_path.exists():
        click.secho("Database not found. Run 'endnote-mcp index' first.", fg="yellow")
        return

    from endnote_mcp.db import connect, get_stats
    conn = connect(cfg.db_path)
    stats = get_stats(conn)
    conn.close()

    click.echo()
    click.secho("  EndNote MCP — Library Status", bold=True)
    click.echo(f"  Config:       {config_path}")
    click.echo(f"  XML source:   {cfg.endnote_xml}")
    click.echo(f"  PDF dir:      {cfg.pdf_dir}")
    click.echo(f"  Database:     {cfg.db_path} ({cfg.db_path.stat().st_size / 1024 / 1024:.1f} MB)")
    click.echo()
    click.echo(f"  References:        {stats['total_references']:,}")
    click.echo(f"  PDFs indexed:      {stats['references_with_pdf']:,}")
    click.echo(f"  PDF pages:         {stats['total_pdf_pages']:,}")
    click.echo()


# ====================================================================
# install — Add to Claude Desktop
# ====================================================================
@cli.command()
def install():
    """Add the MCP server to Claude Desktop configuration."""
    _install_claude_desktop()


# ====================================================================
# Helpers
# ====================================================================

def _find_endnote_libraries() -> list[Path]:
    """Auto-detect EndNote library files on the system."""
    candidates = []
    home = Path.home()

    search_dirs = [
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
    ]

    # Also check common macOS/Windows locations
    if platform.system() == "Darwin":
        search_dirs.append(home / "Library")
    elif platform.system() == "Windows":
        search_dirs.append(Path(os.environ.get("APPDATA", "")))

    for d in search_dirs:
        if not d.exists():
            continue
        # Look for .enlp (EndNote library package) and .enl files
        for pattern in ("**/*.enlp", "**/*.enl"):
            try:
                for path in d.glob(pattern):
                    candidates.append(path)
            except PermissionError:
                continue

    return sorted(set(candidates))


def _find_xml_exports() -> list[Path]:
    """Find XML files that look like EndNote exports."""
    candidates = []
    home = Path.home()

    for d in [home / "Desktop", home / "Documents", home / "Downloads"]:
        if not d.exists():
            continue
        for xml_file in d.glob("*.xml"):
            # Quick check: is it an EndNote XML? (look for <records> tag)
            try:
                with open(xml_file, "rb") as f:
                    head = f.read(2048)
                if b"<records>" in head or b"<record>" in head:
                    candidates.append(xml_file)
            except (PermissionError, OSError):
                continue

    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def _find_pdf_dir_for_library(library_path: Path) -> Path | None:
    """Given an .enlp or .enl path, find the PDF directory."""
    # For .enlp packages, look inside
    if library_path.suffix == ".enlp":
        for pdf_dir in library_path.rglob("PDF"):
            if pdf_dir.is_dir():
                return pdf_dir

    # For .enl files, look for sibling .Data directory
    data_dir = library_path.with_suffix(".Data")
    if data_dir.exists():
        pdf_dir = data_dir / "PDF"
        if pdf_dir.exists():
            return pdf_dir

    # Look next to the library file
    parent = library_path.parent
    for d in parent.iterdir():
        if d.is_dir() and d.name.endswith(".Data"):
            pdf_dir = d / "PDF"
            if pdf_dir.exists():
                return pdf_dir

    return None


def _find_or_ask_xml() -> Path | None:
    """Find XML exports or ask the user to provide one."""
    xml_files = _find_xml_exports()

    if xml_files:
        click.echo("  Found EndNote XML export(s):")
        for i, path in enumerate(xml_files[:5], 1):
            size_mb = path.stat().st_size / 1024 / 1024
            click.echo(f"    [{i}] {path.name} ({size_mb:.1f} MB) — {path.parent}")

        click.echo(f"    [0] Enter a different path")
        choice = click.prompt("  Select", type=int, default=1)

        if 1 <= choice <= len(xml_files):
            return xml_files[choice - 1]

    click.echo("  No EndNote XML export found automatically.")
    click.echo("  In EndNote: File → Export → choose XML format")
    path_str = click.prompt("  Path to your exported XML file")
    path = Path(path_str).expanduser().resolve()
    if path.exists():
        return path

    click.secho(f"  File not found: {path}", fg="red")
    return None


def _find_or_ask_pdf_dir(xml_path: Path) -> Path | None:
    """Find PDF directory or ask the user."""
    # Try to find libraries and their PDF dirs
    libraries = _find_endnote_libraries()
    pdf_dirs = []
    for lib in libraries:
        pdf_dir = _find_pdf_dir_for_library(lib)
        if pdf_dir:
            pdf_count = sum(1 for _ in pdf_dir.glob("*.pdf"))
            pdf_dirs.append((pdf_dir, pdf_count, lib))

    if pdf_dirs:
        click.echo("  Found PDF directories:")
        for i, (path, count, lib) in enumerate(pdf_dirs[:5], 1):
            click.echo(f"    [{i}] {path} ({count:,} PDFs)")

        click.echo(f"    [0] Enter a different path")
        choice = click.prompt("  Select", type=int, default=1)

        if 1 <= choice <= len(pdf_dirs):
            return pdf_dirs[choice - 1][0]

    click.echo("  Could not auto-detect PDF directory.")
    click.echo("  This is usually inside your EndNote library's .Data/PDF folder.")
    path_str = click.prompt("  Path to your PDF directory")
    path = Path(path_str).expanduser().resolve()
    if path.exists():
        return path

    click.secho(f"  Directory not found: {path}", fg="red")
    return None


def _run_index(config_path, *, full=False, skip_pdfs=False):
    """Run the indexing process with progress display."""
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
    from endnote_mcp.config import Config
    from endnote_mcp.db import connect, clear_all, upsert_reference, insert_pdf_page, get_stats
    from endnote_mcp.endnote_parser import parse_endnote_xml
    from endnote_mcp.pdf_indexer import extract_pages, find_pdf

    cfg = Config.load(config_path)

    if not cfg.endnote_xml.exists():
        click.secho(f"XML file not found: {cfg.endnote_xml}", fg="red")
        raise SystemExit(1)

    conn = connect(cfg.db_path)

    if full:
        click.echo("Clearing existing data...")
        clear_all(conn)

    # --- Phase 1: Parse XML ---
    # First pass to count records
    click.echo(f"Reading {cfg.endnote_xml.name}...")
    ref_count = 0
    pdf_refs = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("Parsing references...", total=None)

        for ref in parse_endnote_xml(cfg.endnote_xml):
            upsert_reference(conn, ref)
            ref_count += 1
            if ref.get("pdf_path"):
                pdf_refs.append((ref["rec_number"], ref["pdf_path"]))
            progress.update(task, completed=ref_count, description=f"Parsing references... {ref_count}")
            if ref_count % 500 == 0:
                conn.commit()

        conn.commit()
        progress.update(task, description=f"Parsed {ref_count} references", completed=ref_count, total=ref_count)

    click.secho(f"  ✓ {ref_count:,} references parsed ({len(pdf_refs):,} with PDFs)", fg="green")

    # --- Phase 2: Extract PDFs ---
    if not skip_pdfs and pdf_refs:
        # Check already indexed
        already_indexed = set()
        if not full:
            rows = conn.execute("SELECT DISTINCT rec_number FROM pdf_pages").fetchall()
            already_indexed = {row[0] for row in rows}
            if already_indexed:
                click.echo(f"  {len(already_indexed):,} PDFs already indexed — skipping")

        new_pdf_refs = [(r, p) for r, p in pdf_refs if r not in already_indexed]

        if new_pdf_refs:
            pdf_ok = 0
            pdf_fail = 0
            total_pages = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task("Extracting PDFs...", total=len(new_pdf_refs))

                for i, (rec_number, pdf_filename) in enumerate(new_pdf_refs, 1):
                    pdf_path = find_pdf(cfg.pdf_dir, pdf_filename)
                    if pdf_path is None:
                        pdf_fail += 1
                        progress.update(task, advance=1)
                        continue

                    try:
                        page_count = 0
                        for page_num, text in extract_pages(pdf_path):
                            insert_pdf_page(conn, rec_number, page_num, text)
                            page_count += 1
                        total_pages += page_count
                        pdf_ok += 1
                    except Exception:
                        pdf_fail += 1

                    progress.update(task, advance=1, description=f"Extracting PDFs... ({pdf_ok} OK, {pdf_fail} failed)")

                    if i % 100 == 0:
                        conn.commit()

                conn.commit()

            click.secho(
                f"  ✓ {pdf_ok:,} PDFs extracted ({total_pages:,} pages)"
                + (f", {pdf_fail} not found" if pdf_fail else ""),
                fg="green",
            )
        else:
            click.echo("  No new PDFs to index.")

    elif skip_pdfs:
        click.echo("  Skipping PDF extraction.")

    # --- Summary ---
    stats = get_stats(conn)
    conn.close()

    click.echo()
    click.secho("Indexing complete!", bold=True, fg="green")
    click.echo(f"  References:   {stats['total_references']:,}")
    click.echo(f"  PDFs indexed: {stats['references_with_pdf']:,}")
    click.echo(f"  PDF pages:    {stats['total_pdf_pages']:,}")
    click.echo(f"  Database:     {cfg.db_path}")


def _install_claude_desktop():
    """Add MCP server entry to Claude Desktop config."""
    if platform.system() == "Darwin":
        config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif platform.system() == "Windows":
        config_path = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    else:
        config_path = Path.home() / ".config" / "claude" / "claude_desktop_config.json"

    if not config_path.parent.exists():
        click.secho("Claude Desktop config directory not found. Is Claude Desktop installed?", fg="red")
        return

    # Find uv or python executable
    uv_path = _find_uv()

    if uv_path:
        server_entry = {
            "command": str(uv_path),
            "args": ["run", "--directory", str(Path(__file__).resolve().parents[2]), "endnote-mcp", "serve"],
        }
    else:
        # Fallback to direct python
        server_entry = {
            "command": sys.executable,
            "args": ["-m", "endnote_mcp.cli", "serve"],
        }

    # Read existing config or create new
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = {}

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"]["endnote-library"] = server_entry

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    click.secho(f"  ✓ Added to Claude Desktop config: {config_path}", fg="green")
    click.echo("  Restart Claude Desktop to activate.")


def _find_uv() -> Path | None:
    """Find the uv executable."""
    import shutil
    # Check common locations
    uv = shutil.which("uv")
    if uv:
        return Path(uv)

    for candidate in [
        Path.home() / ".local" / "bin" / "uv",
        Path.home() / ".cargo" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
        Path("/opt/homebrew/bin/uv"),
    ]:
        if candidate.exists():
            return candidate

    return None


def main():
    cli()


if __name__ == "__main__":
    main()
