"""The server must import and register its tools on both mcp 1.x and 2.x.

mcp 2.0 renamed FastMCP to MCPServer; server.py picks whichever the installed
SDK provides. These tests fail loudly if that shim stops resolving, instead of
the failure surfacing as `CONNECTION_CLOSED` in a client.
"""

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from endnote_mcp.config import Config
from endnote_mcp.db import connect, upsert_reference

EXPECTED_TOOLS = {
    "search_references",
    "search_fulltext",
    "search_library",
    "get_reference_details",
    "get_citation",
    "read_pdf_section",
    "list_references_by_topic",
    "find_related",
    "get_bibliography",
    "search_semantic",
    "get_bibtex",
    "rebuild_index",
}


@pytest.fixture(scope="module")
def server():
    return importlib.import_module("endnote_mcp.server")


def test_server_module_imports(server):
    """Importing the server must not raise, whichever mcp major is installed."""
    assert server.mcp is not None


def test_server_class_matches_installed_sdk(server):
    """The shim must resolve to the class the installed mcp actually ships."""
    from importlib.metadata import version

    major = int(version("mcp").split(".")[0])
    expected = "MCPServer" if major >= 2 else "FastMCP"
    assert type(server.mcp).__name__ == expected


@pytest.mark.anyio
async def test_all_tools_registered(server):
    """All 12 tools must be registered and exposed to clients."""
    tools = await server.mcp.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_add_reference_is_opt_in_and_mac_only(server, monkeypatch, tmp_path):
    """add_reference writes to the user's library: only with add_references: true, only on macOS."""
    fresh = server._Server("test")
    monkeypatch.setattr(server, "mcp", fresh)
    cfg = Config(endnote_xml=tmp_path / "x.xml", pdf_dir=tmp_path, db_path=tmp_path / "db")
    monkeypatch.setattr(server, "_config", cfg)

    monkeypatch.setattr(server.sys, "platform", "darwin")
    assert server.register_optional_tools() == []
    cfg.add_references = True
    monkeypatch.setattr(server.sys, "platform", "win32")
    assert server.register_optional_tools() == []
    monkeypatch.setattr(server.sys, "platform", "darwin")
    assert server.register_optional_tools() == ["add_reference"]
    assert {t.name for t in await fresh.list_tools()} == {"add_reference"}


def test_no_config_registers_nothing(server, monkeypatch):
    monkeypatch.setattr(server, "_config", None)
    monkeypatch.setattr(server, "_get_config", lambda: (_ for _ in ()).throw(FileNotFoundError("none")))
    monkeypatch.setattr(server.sys, "platform", "darwin")
    assert server.register_optional_tools() == []


def test_bundle_manifest_lists_the_same_tools():
    """mcpb/manifest.json advertises the tool list; it must not drift from the server."""
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "mcpb" / "manifest.json").read_text("utf-8")
    )
    assert {t["name"] for t in manifest["tools"]} == EXPECTED_TOOLS


def test_bundle_entry_point_exists():
    """A manifest pointing at a missing entry point fails only at install time."""
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "mcpb" / "manifest.json").read_text("utf-8"))
    assert (root / "mcpb" / manifest["server"]["entry_point"]).is_file()


def test_bundle_exports_its_source_dir_to_subprocesses(monkeypatch):
    """rebuild_index starts the indexer with `python -m endnote_mcp.cli`. The
    bundle vendors that package under src/, which only PYTHONPATH reaches."""
    entry = Path(__file__).resolve().parents[1] / "mcpb" / "src" / "server.py"
    monkeypatch.setenv("PYTHONPATH", "")
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("_mcpb_entry", entry)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert os.environ["PYTHONPATH"].split(os.pathsep)[0] == str(entry.parent)


# mcp 2.x runs sync tools on anyio worker threads and retires idle workers
# after 10 s, so consecutive calls routinely land on different threads. No tool
# may depend on the thread that served an earlier call (issues #7 and #8).

def _on_new_thread(fn, *args):
    """Run fn on a fresh thread and return its result, re-raising its error."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args).result()


@pytest.fixture
def library(server, sample_ref, tmp_path, monkeypatch):
    """Point the server at a throwaway on-disk library holding sample_ref."""
    db_path = tmp_path / "library.db"
    conn = connect(db_path)
    upsert_reference(conn, {
        **sample_ref,
        "authors": json.dumps(sample_ref["authors"]),
        "keywords": json.dumps(sample_ref["keywords"]),
    })
    conn.commit()
    conn.close()
    monkeypatch.setattr(server, "_config", Config(
        endnote_xml=tmp_path / "library.xml", pdf_dir=tmp_path, db_path=db_path,
    ))
    return sample_ref


def test_consecutive_calls_on_different_threads(server, library):
    """The idle-gap case: each call runs on a thread the previous one did not."""
    title = library["title"]
    assert title in server.get_reference_details(42)
    assert title in _on_new_thread(server.get_reference_details, 42)
    assert title in _on_new_thread(server.search_references, "shipping")


def test_concurrent_calls(server, library):
    """Clients that batch independent calls run them on several threads at once."""
    workers = 8
    barrier = threading.Barrier(workers)

    def call(_):
        barrier.wait()
        return server.search_references("shipping")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(call, range(workers)))
    assert all(library["title"] in r for r in results)


def test_rebuild_index_after_an_earlier_call(server, library, monkeypatch):
    """#8: the indexer finished, then reopening the shared connection failed."""
    server.get_reference_details(42)
    # Stand in for the indexer subprocess, which would index the real library.
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="", stderr=""),
    )
    out = _on_new_thread(server.rebuild_index)
    assert out.startswith("Re-indexing complete.")
    assert "References: 1" in out


def test_rebuild_index_reports_a_failed_indexer(server, library, monkeypatch):
    """A failed indexer run must not be reported as a completed one."""
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 1, stdout="", stderr="No module named 'endnote_mcp'",
        ),
    )
    out = server.rebuild_index()
    assert out.startswith("Re-indexing failed (exit code 1).")
    assert "No module named 'endnote_mcp'" in out
