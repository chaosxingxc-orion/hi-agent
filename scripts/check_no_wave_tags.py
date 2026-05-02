#!/usr/bin/env python3
"""CI gate: hi_agent/**/*.py and scripts/**/*.py must not contain sprint wave labels.

Sprint-label identifiers (e.g. "Wave N.M", "Wave N", or "WN-X") belong in git commit
messages and docs, not in production source code.

Allowlist: lines with '# legacy:' annotation are skipped.
Allowed paths: docs/, docs/downstream-responses/, docs/delivery/ (dated artifacts).
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Pattern matches versioned sprint references and bare sprint labels.
# Does NOT match: WaveProcessor or other identifiers using "Wave" as a prefix.
_WAVE_PATTERN = re.compile(r"Wave\s+\d+\.\d+|W\d+-[A-Z]\b")
_LEGACY_ANNOTATION = "# legacy:"
_WAVE_LITERAL_OK = "wave-literal-ok"
_EXPIRY_WAVE = "expiry_wave"

# CI governance scripts that legitimately contain wave-number strings as data
# (allowlist entries, expiry tracking). These are not sprint-label violations.
_EXCLUDED_SCRIPTS = frozenset({
    "check_route_scope.py",
    "check_expired_waivers.py",
    "check_no_wave_tags.py",   # self-referential; contains pattern examples in comments
    "_current_wave.py",
})


def _scan_file(path: Path) -> list[str]:
    """Scan path for wave-tag *identifiers*; narrative comments and docstrings exempt.

    W31-D D-2': narrative comments documenting *why* a wave-N change was made
    (e.g. ``# W31-N (N.5): when allowlist_enabled is False ...``) are
    archaeological documentation, not enforcement strings. The pure-comment
    and docstring-interior heuristic mirrors tests/unit/test_no_wave_tags_in_source.py.
    """
    violations = []
    in_docstring = False
    docstring_quote: str | None = None
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for quote in ('"""', "'''"):
            count = line.count(quote)
            if count == 0:
                continue
            if not in_docstring and count >= 2:
                continue
            if in_docstring and docstring_quote == quote:
                in_docstring = False
                docstring_quote = None
            elif not in_docstring:
                in_docstring = True
                docstring_quote = quote

        if not _WAVE_PATTERN.search(line):
            continue
        if _LEGACY_ANNOTATION in line:
            continue
        if _WAVE_LITERAL_OK in line:
            continue
        if _EXPIRY_WAVE in line:
            continue
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if in_docstring:
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        violations.append(f"  {path.relative_to(ROOT)}:{i}: {line.strip()}")
    return violations


def _get_head_sha() -> str:
    """Return short git HEAD SHA, or empty string on failure."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    errors = []
    for py_file in (ROOT / "hi_agent").rglob("*.py"):
        errors.extend(_scan_file(py_file))
    for py_file in (ROOT / "scripts").rglob("*.py"):
        if py_file.name not in _EXCLUDED_SCRIPTS:
            errors.extend(_scan_file(py_file))

    if args.json:
        status = "fail" if errors else "pass"
        print(json.dumps({
            "check": "no_wave_tags",
            "status": status,
            "violations": errors,
            "head": _get_head_sha(),
        }))
        return 1 if errors else 0

    if errors:
        print("FAIL check_no_wave_tags:")
        for e in errors:
            print(e)
        return 1
    print("OK check_no_wave_tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())

