#!/usr/bin/env python3
"""Add expiry_wave annotations to noqa/type:ignore suppressions.

Scans Python files under hi_agent/, scripts/, tests/ and appends
"  expiry_wave: Wave 17" to suppression lines missing expiry metadata
on the same line or immediately preceding line.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ("hi_agent", "agent_kernel", "agent_server", "scripts", "tests")
SUPPRESSION_RE = re.compile(r"#\s*(?:noqa|type:\s*ignore)", re.IGNORECASE)
EXPIRY_RE = re.compile(r"expiry_wave", re.IGNORECASE)
APPEND_TEXT = "  expiry_wave: Wave 17"


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
