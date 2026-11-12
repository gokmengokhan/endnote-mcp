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
    "get_word_endnote_status",
    "audit_word_endnote_document",
    "prepare_word_endnote_conversion",
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


@pytest.mark.anyio
async def test_word_tool_schemas(server):
    tools = {t.name:(getattr(t,"inputSchema",None) or t.input_schema) for t in await server.mcp.list_tools()}
    assert 'update_word_endnote_document' not in tools
    assert tools['get_word_endnote_status'].get('properties',{}) == {}
    audit = tools['audit_word_endnote_document']
    assert set(audit['properties']) == {'docx_path','expected_groups','record_map_path','numbering_mode'}
    assert audit['required'] == ['docx_path']
    prepare = tools['prepare_word_endnote_conversion']
    assert set(prepare['properties']) == set(prepare['required']) == {
        'source_path','destination_path','citation_plan_path','expected_source_sha256'}


@pytest.mark.parametrize('explicit_root', [False, True])
def test_bundle_optional_working_root(tmp_path, monkeypatch, explicit_root):
    import yaml
    entry = Path(__file__).resolve().parents[1]/'mcpb'/'src'/'server.py'
    spec = importlib.util.spec_from_file_location('_bundle_root_test', entry)
    bundle = importlib.util.module_from_spec(spec); spec.loader.exec_module(bundle)
    xml = tmp_path/'library.xml'; xml.write_text('<xml/>')
    monkeypatch.setenv('ENDNOTE_XML',str(xml))
    monkeypatch.setenv('ENDNOTE_PDF_DIR',str(tmp_path))
    monkeypatch.delenv('ENDNOTE_DOCX_WORKING_ROOT',raising=False)
    monkeypatch.setenv('ENDNOTE_MCP_CONFIG',str(tmp_path/'cli.yaml'))
    cli = tmp_path/'cli.yaml'; cli.write_text('preserve CLI config')
    monkeypatch.setattr(bundle,'get_config_dir',lambda:tmp_path)
    if explicit_root: monkeypatch.setenv('ENDNOTE_DOCX_WORKING_ROOT',str(tmp_path/'work'))
    for _ in range(2):
        result = yaml.safe_load(bundle._bootstrap_config().read_text())
        assert result.get('native_working_root') == (str(tmp_path/'work') if explicit_root else None)
        assert result['native_word_enabled'] is False
        assert cli.read_text() == 'preserve CLI config'


def test_real_stdio_initialize_list_and_portable_calls(tmp_path):
    """Exercise actual JSON-RPC framing with whichever supported SDK is installed."""
    import queue
    env = os.environ.copy()
    env['ENDNOTE_MCP_CONFIG'] = str(tmp_path/'absent-config.yaml')
    process = subprocess.Popen([sys.executable,'-m','endnote_mcp.server'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    errors = []
    threading.Thread(target=lambda:errors.extend(process.stderr),daemon=True).start()
    output = queue.Queue()
    threading.Thread(target=lambda:[output.put(line) for line in process.stdout],daemon=True).start()
    def request(identifier, method, params):
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':identifier,
            'method':method,'params':params})+'\n')
        process.stdin.flush()
        while True:
            try:
                reply = json.loads(output.get(timeout=60))
            except queue.Empty:
                pytest.fail(f'Stdio timeout calling {method}; stderr: {errors!r}')
            if reply.get('id') == identifier:
                assert 'error' not in reply, reply
                return reply['result']
    try:
        request(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},
            'clientInfo':{'name':'portable-test','version':'1'}})
        process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        process.stdin.flush()
        tools = request(2,'tools/list',{})
        assert {t['name'] for t in tools['tools']} == EXPECTED_TOOLS
        for identifier,name,args,status in [
            (3,'get_word_endnote_status',{},'unqualified'),
            (4,'audit_word_endnote_document',{'docx_path':str(tmp_path/'missing.docx')},'error'),
            (5,'prepare_word_endnote_conversion',{'source_path':str(tmp_path/'a.docx'),
                'destination_path':str(tmp_path/'b.docx'),'citation_plan_path':str(tmp_path/'plan.json'),
                'expected_source_sha256':'0'*64},None)]:
            result = request(identifier,'tools/call',{'name':name,'arguments':args})
            assert not result.get('isError'), result
            payload = json.loads(result['content'][0]['text'])
            if status:
                assert payload['status'] == status
            else:
                assert payload['status'] in ('blocked','error')
    finally:
        process.terminate()
        process.communicate(timeout=10)
