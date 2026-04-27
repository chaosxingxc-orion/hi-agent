#!/usr/bin/env python3
"""CI gate: hi_agent/**/*.py and scripts/**/*.py must not contain sprint wave labels.

Sprint-label identifiers (e.g. "Wave N.M", "Wave N", or "WN-X") belong in git commit
messages and docs, not in production source code.

Allowlist: lines with '# legacy:' annotation are skipped.
Allowed paths: docs/, docs/downstream-responses/, docs/delivery/ (dated artifacts).
"""
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

# CI governance scripts that legitimately contain wave-number strings as data
# (allowlist entries, expiry tracking). These are not sprint-label violations.
_EXCLUDED_SCRIPTS = frozenset({
    "check_route_scope.py",
    "check_expired_waivers.py",
    "check_no_wave_tags.py",   # self-referential; contains pattern examples in comments
    "_current_wave.py",
})


def _scan_file(path: Path) -> list[str]:
    violations = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if _WAVE_PATTERN.search(line) and _LEGACY_ANNOTATION not in line:
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
