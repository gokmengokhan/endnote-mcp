#!/usr/bin/env python3
"""Check reftypes.py against a real EndNote, in a scratch library.

For each reference type add_reference supports, imports one record with every
field set to its own marker, then checks that (1) EndNote's export returns
exactly what was sent and (2) each label EndNote shows for the type reads
back its own marker. That proves the label -> XML map for every field.

    python scripts/verify_reftypes_live.py "Scratch.enl"

It writes records, so it refuses to run unless the named library is the only
library open in EndNote. Never point it at a real library. macOS only.
"""

from __future__ import annotations

import datetime as dt
import sys
import xml.etree.ElementTree as ET

from endnote_mcp.endnote_app import EndNoteApp
from endnote_mcp.reftypes import GENERIC_XML, LIST_FIELDS, NAME_FIELDS, REF_TYPES
from endnote_mcp.writer import (
    LABEL,
    differences,
    draft_record,
    endnote_name,
    record_fields,
    record_xml,
)

SKIP = {"Author", "Title", "Year", "URL", "Label"}  # set through parameters


def markers(ref_type: str) -> dict:
    fields = {}
    for label, generic in REF_TYPES[ref_type][1].items():
        if generic in SKIP:
            continue
        if generic in NAME_FIELDS:
            fields[label] = [f"Marker, {label}"]
        elif generic in LIST_FIELDS:
            fields[label] = [f"M-{label}-1", f"M-{label}-2"]
        else:
            fields[label] = f"M-{label}"
    return fields


def main(library: str) -> int:
    app = EndNoteApp()
    open_now = app.libraries()
    if open_now != [library]:
        print(f"Refusing: {library!r} must be the only open library (open: {open_now}).")
        return 2

    failures = 0
    for ref_type in REF_TYPES:
        fields = markers(ref_type)
        draft = draft_record(
            ref_type, f"Marker record: {ref_type}", ["Marker, Author"], "2026",
            f"https://example.org/{ref_type.replace(' ', '-').lower()}", fields,
            today=dt.date(2026, 11, 11),
        )
        xml = record_xml(draft)
        before = set(app.record_ids(library))
        app.import_xml(xml, library)
        new = [r for r in app.record_ids(library) if r not in before]
        if len(new) != 1:
            print(f"{ref_type}: expected one new record, got {new}")
            failures += 1
            continue
        rid = new[0]

        sent = record_fields(ET.fromstring(xml.encode()).find("records/record"))
        back = record_fields(ET.fromstring(app.export([rid]).encode()).find("records/record"))
        diffs = differences(sent, back)

        wrong = []
        expected = {
            "Author": "Marker, Author", "Title": f"Marker record: {ref_type}",
            "Year": "2026", "URL": draft.first("URL"), "Label": LABEL,
        }
        for label, generic in REF_TYPES[ref_type][1].items():
            want = expected.get(generic)
            if want is None:
                value = fields[label]
                if generic in NAME_FIELDS:
                    want = "\n".join(endnote_name(v) for v in value)
                elif generic in LIST_FIELDS:
                    want = "\n".join(value)
                else:
                    want = value
            got = app.field(rid, label)
            got = None if got is None else got.replace("\r\n", "\n").replace("\r", "\n").strip()
            if got != want:
                wrong.append(f"{label} ({GENERIC_XML[generic]}): want {want!r}, got {got!r}")

        n = len(REF_TYPES[ref_type][1])
        status = "OK" if not diffs and not wrong else "FAIL"
        print(f"{status:4} {ref_type:24} export {'identical' if not diffs else f'{len(diffs)} differences'}; "
              f"labels {n - len(wrong)}/{n} read back their own value  ({rid})")
        for d in diffs:
            print(f"       export: {d}")
        for w in wrong:
            print(f"       label:  {w}")
        failures += status == "FAIL"
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
