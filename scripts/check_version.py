#!/usr/bin/env python3
"""Assert every file that carries the version agrees, optionally with a release tag.

The MCP registry rejects a server.json whose version does not exactly match a
published PyPI release, and that mismatch is invisible until the publish step
fails. Four files hold the version independently, so check them together.

Usage:
    python scripts/check_version.py           # the four files agree
    python scripts/check_version.py v1.4.10   # ...and match this release tag
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

try:  # tomllib is 3.11+; this package still supports 3.10
    import tomllib
except ImportError:
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version(text: str) -> str:
    if tomllib is not None:
        return tomllib.loads(text)["project"]["version"]
    # Fall back to reading the version out of the [project] table by hand.
    section = re.split(r"^\[", text, flags=re.MULTILINE)
    for block in section:
        if block.startswith("project]"):
            match = re.search(r'^version\s*=\s*["\'](.+?)["\']', block, re.MULTILINE)
            if match:
                return match.group(1)
    sys.exit("pyproject.toml has no [project] version")


def _cff_version(text: str) -> str:
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    if match is None:
        sys.exit("CITATION.cff has no version field")
    return match.group(1).strip("\"'")


def _readme_version(text: str) -> str:
    # The "Citing This Software" block quotes a version, and it silently went
    # five releases stale before anyone noticed.
    match = re.search(r"\(Version (\S+?)\) \[Computer software\]", text)
    if match is None:
        sys.exit("README.md citation block has no version")
    return match.group(1)


def versions() -> dict[str, str]:
    server = json.loads((ROOT / "server.json").read_text("utf-8"))

    return {
        "pyproject.toml": _pyproject_version((ROOT / "pyproject.toml").read_text("utf-8")),
        "server.json (top level)": server["version"],
        "server.json (packages[0])": server["packages"][0]["version"],
        "CITATION.cff": _cff_version((ROOT / "CITATION.cff").read_text("utf-8")),
        "README.md (citation)": _readme_version((ROOT / "README.md").read_text("utf-8")),
    }


def main() -> int:
    found = versions()
    expected = None

    if len(sys.argv) > 1:
        expected = sys.argv[1].removeprefix("refs/tags/").removeprefix("v")
        found["release tag"] = expected

    distinct = set(found.values())
    # With no tag to judge against, the majority value is the presumed-correct one.
    reference = expected or Counter(found.values()).most_common(1)[0][0]

    width = max(len(k) for k in found)
    for source, version in found.items():
        mark = "  " if version == reference else "->"
        print(f"  {mark} {source:<{width}}  {version}")

    if len(distinct) > 1:
        odd = sorted(s for s, v in found.items() if v != reference)
        sys.stdout.flush()
        print(f"\nVersion mismatch: expected {reference}, but {', '.join(odd)} "
              f"disagree. Bump every file before tagging.", file=sys.stderr)
        return 1

    print(f"\nAll sources agree on {distinct.pop()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
