"""The AppleScript bridge, with osascript replaced by a recorder."""

from __future__ import annotations

from pathlib import Path

import pytest

from endnote_mcp import endnote_app
from endnote_mcp.endnote_app import (
    EndNoteApp,
    EndNoteError,
    _explain,
    fix_export_encoding,
    parse_record_id,
)

SEP = "\x1e"


def test_parse_record_id():
    assert parse_record_id('<RecordID database="1" recNum="17814" />') == (1, 17814)
    assert parse_record_id(' <RecordID database="2" recNum="5"/> ') == (2, 5)
    with pytest.raises(EndNoteError):
        parse_record_id("17814")


@pytest.mark.parametrize("text", ["Scotland’s Blue Economy", "Şehircilik, Iğdır, İzmir – “su”", "ü é ñ"])
def test_fix_export_encoding_undoes_mac_roman(text):
    mangled = text.encode("utf-8").decode("mac_roman")  # what EndNote's export hands over
    assert mangled != text
    assert fix_export_encoding(mangled) == text


@pytest.mark.parametrize("text", ["plain ASCII", "Şehircilik", "café"])
def test_fix_export_encoding_leaves_good_text_alone(text):
    assert fix_export_encoding(text) == text


@pytest.mark.parametrize("stderr, advice", [
    ("execution error: Not authorized to send Apple events to EndNote. (-1743)", "Automation"),
    ("execution error: AppleEvent timed out. (-1712)", "dialog"),
    ("execution error: Can’t get application id \"x\". (-10814)", "installed"),
    ("execution error: something odd (-2700)", "something odd"),
])
def test_explain(stderr, advice):
    assert advice in _explain(stderr)


class Recorder:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, script, args, timeout):
        self.calls.append((script, args))
        return self.outputs.pop(0)


def test_lists_are_split_and_arguments_passed_as_argv():
    r = Recorder(f"Lib A.enl{SEP}My Library.enlp", f'<RecordID database="1" recNum="1" />{SEP}')
    app = EndNoteApp(runner=r)
    assert app.libraries() == ["Lib A.enl", "My Library.enlp"]
    assert app.record_ids("My Library.enlp") == ['<RecordID database="1" recNum="1" />']
    script, args = r.calls[1]
    assert args == ["My Library.enlp"]
    assert "item 1 of argv" in script and "My Library" not in script  # never spliced into source


def test_empty_results():
    app = EndNoteApp(runner=Recorder("", ""))
    assert app.libraries() == []
    assert app.find("x", "URL") == []


def test_export_fixes_encoding_and_field_reports_missing():
    mangled = "<title>Scotland’s</title>".encode("utf-8").decode("mac_roman")
    app = EndNoteApp(runner=Recorder(mangled, f"{SEP}missing", "Institution X"))
    assert app.export(["id"]) == "<title>Scotland’s</title>"
    assert app.field("id", "Journal") is None
    assert app.field("id", "Institution") == "Institution X"


def test_open_library_waits_for_it(monkeypatch):
    opened = []
    monkeypatch.setattr(endnote_app.subprocess, "run",
                        lambda cmd, **kw: opened.append(cmd) or type("R", (), {"returncode": 0, "stderr": ""})())
    monkeypatch.setattr(endnote_app.time, "sleep", lambda s: None)
    app = EndNoteApp(runner=Recorder("", "", "Lib.enl"))
    app.open_library(Path("/Users/me/Lib.enl"))
    assert opened == [["open", "-b", endnote_app.BUNDLE_ID, "/Users/me/Lib.enl"]]


def test_open_library_skips_an_open_library(monkeypatch):
    monkeypatch.setattr(endnote_app.subprocess, "run", lambda *a, **k: pytest.fail("should not open"))
    EndNoteApp(runner=Recorder("Lib.enl")).open_library(Path("/x/Lib.enl"))


def test_osascript_failure_becomes_endnote_error(monkeypatch):
    result = type("R", (), {"returncode": 1, "stdout": "", "stderr": "execution error: (-1743)"})()
    monkeypatch.setattr(endnote_app.subprocess, "run", lambda *a, **k: result)
    with pytest.raises(EndNoteError, match="Automation"):
        EndNoteApp().libraries()
