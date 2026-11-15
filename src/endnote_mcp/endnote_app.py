"""Drive the EndNote desktop app on macOS through its AppleScript dictionary.

Only add_reference writes to EndNote, and only through this module. It uses
the commands checked against EndNote 2025 (22.4):

    import <XML> into document <name>   the one write path; `create record`
                                        rejects the XML that `export` produces
    retrieve "all" records in document  IDs of one open library's records
    find <text> in field <generic name> searches every open library
    export <IDs> as "RSXML"             reads records back as EndNote XML
    unformatted record <ID>             EndNote's temporary citation
    field <label> of record <ID>        one field, by the type's own label

A record ID is a string such as '<RecordID database="1" recNum="17814" />'.
`find` takes generic field names ("ISBN/ISSN"), `field` the labels a
reference type shows ("Report Number").
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

BUNDLE_ID = "com.ThomsonResearchSoft.EndNote"
_TELL = f'tell application id "{BUNDLE_ID}"'
_SEP = "\x1e"  # joins list items in osascript output

_RECORD_ID = re.compile(r'<RecordID database="(\d+)" recNum="(\d+)"\s*/>')

# Each script reads its arguments from argv, so no text is ever spliced into
# AppleScript source. List results come back joined by _SEP.
_JOIN = """
    if r is missing value then return ""
    set AppleScript's text item delimiters to (character id 30)
    set s to r as text
    set AppleScript's text item delimiters to ""
    return s
"""
_SCRIPTS = {
    "libraries": f"""on run argv
    {_TELL}
        set r to name of every document
    end tell{_JOIN}end run""",
    "record_ids": f"""on run argv
    {_TELL}
        set r to retrieve "all" records in document (item 1 of argv)
    end tell{_JOIN}end run""",
    "find": f"""on run argv
    {_TELL}
        set r to find (item 1 of argv) in field (item 2 of argv)
    end tell{_JOIN}end run""",
    "import": f"""on run argv
    {_TELL}
        import (item 1 of argv) into document (item 2 of argv)
    end tell
    return "ok"
end run""",
    "export": f"""on run argv
    {_TELL}
        return export argv as "RSXML"
    end tell
end run""",
    "citation": f"""on run argv
    {_TELL}
        return unformatted record (item 1 of argv)
    end tell
end run""",
    "field": f"""on run argv
    {_TELL}
        set r to field (item 1 of argv) of record (item 2 of argv)
    end tell
    if r is missing value then return (character id 30) & "missing"
    return r
end run""",
}


class EndNoteError(RuntimeError):
    """EndNote could not be reached, or refused a command."""


def parse_record_id(record_id: str) -> tuple[int, int]:
    """'<RecordID database="1" recNum="17814" />' -> (1, 17814)."""
    m = _RECORD_ID.fullmatch(record_id.strip())
    if not m:
        raise EndNoteError(f"Unexpected record ID from EndNote: {record_id!r}")
    return int(m.group(1)), int(m.group(2))


def fix_export_encoding(text: str) -> str:
    """Undo the mangling in EndNote's `export`.

    EndNote passes exported XML on as UTF-8 bytes read as Mac Roman, so
    "Scotland’s" arrives as "Scotland‚Äôs". Every byte value has a Mac Roman
    character, so the way back is lossless; text that was not mangled
    (ASCII, or characters Mac Roman lacks) comes back unchanged.
    """
    try:
        return text.encode("mac_roman").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _explain(stderr: str) -> str:
    """Turn an osascript error into advice the user can act on."""
    msg = stderr.strip()
    if "-1743" in msg:
        return (
            "macOS is not letting this app control EndNote. Open System Settings > "
            "Privacy & Security > Automation, and under Claude (or the app that runs "
            "endnote-mcp) turn on EndNote. Then try again."
        )
    if "-1712" in msg:
        return (
            "EndNote did not respond in time. If a dialog is open in EndNote, "
            "close it and try again."
        )
    if "-10814" in msg or "Can’t get application id" in msg or "Can't get application id" in msg:
        return "EndNote does not seem to be installed on this Mac."
    if "-600" in msg:
        return "EndNote is not running."
    return f"EndNote reported an error: {msg}"


def _osascript(script: str, args: list[str], timeout: float) -> str:
    try:
        r = subprocess.run(
            ["osascript", "-", *args],
            input=script,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise EndNoteError("osascript was not found; adding references needs macOS.") from None
    except subprocess.TimeoutExpired:
        raise EndNoteError(
            f"EndNote did not answer within {int(timeout)} seconds. If a dialog is "
            "open in EndNote, close it and try again."
        ) from None
    if r.returncode != 0:
        raise EndNoteError(_explain(r.stderr))
    out = r.stdout
    return out[:-1] if out.endswith("\n") else out


class EndNoteApp:
    """The running EndNote app. Every method is one AppleScript round trip."""

    def __init__(self, timeout: float = 120, runner=_osascript):
        self.timeout = timeout
        self._runner = runner

    def _call(self, name: str, *args: str) -> str:
        return self._runner(_SCRIPTS[name], list(args), self.timeout)

    def _call_list(self, name: str, *args: str) -> list[str]:
        return [x for x in self._call(name, *args).split(_SEP) if x.strip()]

    def libraries(self) -> list[str]:
        """Names of the open libraries, e.g. "My EndNote Library.enlp"."""
        return self._call_list("libraries")

    def open_library(self, path: Path, wait: float = 90) -> None:
        """Open the library at *path* unless it is open already; start EndNote if needed."""
        name = path.name
        if name in self.libraries():
            return
        r = subprocess.run(
            ["open", "-b", BUNDLE_ID, str(path)], capture_output=True, text=True
        )
        if r.returncode != 0:
            raise EndNoteError(f"Could not open {path} in EndNote: {r.stderr.strip()}")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                if name in self.libraries():
                    return
            except EndNoteError:
                pass  # still starting up
            time.sleep(1)
        raise EndNoteError(f"EndNote did not open {name} within {int(wait)} seconds.")

    def record_ids(self, library: str) -> list[str]:
        """IDs of every record in one open library."""
        return self._call_list("record_ids", library)

    def find(self, text: str, generic_field: str) -> list[str]:
        """IDs of records in ANY open library whose field contains *text*."""
        return self._call_list("find", text, generic_field)

    def import_xml(self, xml: str, library: str) -> None:
        """Import records given as EndNote XML into one open library."""
        self._call("import", xml, library)

    def export(self, record_ids: list[str]) -> str:
        """The records as EndNote XML, with export's mangled encoding undone."""
        return fix_export_encoding(self._call("export", *record_ids))

    def temporary_citation(self, record_id: str) -> str:
        """EndNote's own temporary citation, e.g. "{Scottish Government, 2025 #17814}"."""
        return self._call("citation", record_id)

    def field(self, record_id: str, label: str) -> str | None:
        """One field by the label its reference type shows; None if the type has no such label."""
        out = self._call("field", label, record_id)
        return None if out == f"{_SEP}missing" else out
