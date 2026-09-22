"""The server must import and register its tools on both mcp 1.x and 2.x.

mcp 2.0 renamed FastMCP to MCPServer; server.py picks whichever the installed
SDK provides. These tests fail loudly if that shim stops resolving, instead of
the failure surfacing as `CONNECTION_CLOSED` in a client.
"""

import importlib
import json
from pathlib import Path

import pytest

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
