#!/usr/bin/env python3
"""CI gate: hi_agent/**/*.py and scripts/**/*.py must not contain sprint wave labels.

Sprint-label identifiers (e.g. "Wave N.M" or "WN-X") belong in git commit
messages and docs, not in production source code.

Allowlist: lines with '# legacy:' annotation are skipped.
Allowed paths: docs/, docs/downstream-responses/, docs/delivery/ (dated artifacts).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

_WAVE_PATTERN = re.compile(r"Wave\s+\d+\.\d+|W\d+-[A-Z]\b")
_LEGACY_ANNOTATION = "# legacy:"


def _scan_file(path: Path) -> list[str]:
    violations = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if _WAVE_PATTERN.search(line) and _LEGACY_ANNOTATION not in line:
            violations.append(f"  {path.relative_to(ROOT)}:{i}: {line.strip()}")
    return violations


def main() -> int:
    errors = []
    for py_file in (ROOT / "hi_agent").rglob("*.py"):
        errors.extend(_scan_file(py_file))
    for py_file in (ROOT / "scripts").rglob("*.py"):
        errors.extend(_scan_file(py_file))
    if errors:
        print("FAIL check_no_wave_tags:")
        for e in errors:
            print(e)
        return 1
    print("OK check_no_wave_tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
