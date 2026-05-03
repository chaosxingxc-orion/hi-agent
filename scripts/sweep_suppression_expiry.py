#!/usr/bin/env python3
"""Add expiry_wave annotations to noqa/type:ignore suppressions.

Scans Python files under hi_agent/, scripts/, tests/ and appends
"  expiry_wave: Wave <current+1>" to suppression lines missing expiry metadata
on the same line or immediately preceding line.

W31-D D-2': APPEND_TEXT now resolves the current wave dynamically from the   wave-literal-ok
canonical helper instead of being hardcoded.  Previously this script wrote a  wave-literal-ok
literal Wave-30 marker which became expired the moment the wave moved past 30 wave-literal-ok
-- so re-running this helper would silently add already-stale markers.        wave-literal-ok
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ("hi_agent", "agent_kernel", "agent_server", "scripts", "tests")
SUPPRESSION_RE = re.compile(r"#\s*(?:noqa|type:\s*ignore)", re.IGNORECASE)
EXPIRY_RE = re.compile(r"expiry_wave", re.IGNORECASE)


def _resolve_append_text() -> str:
    """Resolve the wave to write into new expiry markers.

    Uses scripts/_governance/wave.py::current_wave_number() and writes
    `Wave <N+1>` so that newly-added markers are NOT stale on the wave they
    are added.  Falls back to a permanent marker if the helper cannot be
    imported (defensive; should not trigger in normal use).
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from _governance.wave import (
            current_wave_number,  # expiry_wave: permanent  # added: W31-D D-2'
        )
    except Exception:  # pragma: no cover  # expiry_wave: permanent  # added: W31-D D-2'
        return "  expiry_wave: permanent"
    n = current_wave_number()
    if n <= 0:
        return "  expiry_wave: permanent"
    return f"  expiry_wave: Wave {n + 1}"


APPEND_TEXT = _resolve_append_text()


def process_file(path: pathlib.Path) -> tuple[bool, int]:
    changed = False
    changed_lines = 0
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    for i, raw_line in enumerate(lines):
        line_no_newline = raw_line.rstrip("\r\n")
        newline = raw_line[len(line_no_newline) :]

        if not SUPPRESSION_RE.search(line_no_newline):
            continue
        if EXPIRY_RE.search(line_no_newline):
            continue
        if i > 0 and EXPIRY_RE.search(lines[i - 1].rstrip("\r\n")):
            continue

        lines[i] = f"{line_no_newline}{APPEND_TEXT}{newline}"
        changed = True
        changed_lines += 1

    if changed:
        path.write_text("".join(lines), encoding="utf-8")

    return changed, changed_lines


def iter_python_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for rel_dir in SCAN_DIRS:
        base = ROOT / rel_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def main() -> int:
    files_modified = 0
    lines_modified = 0
    files_skipped = 0

    for path in iter_python_files():
        try:
            file_changed, line_changes = process_file(path)
        except PermissionError:
            files_skipped += 1
            continue

        if file_changed:
            files_modified += 1
            lines_modified += line_changes

    print(f"files_modified={files_modified}")
    print(f"lines_modified={lines_modified}")
    print(f"files_skipped={files_skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
