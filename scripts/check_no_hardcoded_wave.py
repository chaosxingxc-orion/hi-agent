#!/usr/bin/env python3
"""W14-A4: No hardcoded Wave N strings outside _current_wave.py and docs/.

Scans scripts/*.py for patterns like "Wave 14", "Wave 13", "Wave N" that
should be loaded from scripts/_current_wave.py instead.

Allowed exceptions:
- scripts/_current_wave.py (the source of truth)
- docs/ directory (documentation and governance files)
- Any line with a comment # wave-literal-ok

Exit 0: pass (no hardcoded wave strings found in scripts/).
Exit 1: fail (hardcoded wave strings found).
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"

_WAVE_PATTERN = re.compile(r'"Wave\s+\d+"', re.IGNORECASE)
_EXCEPTION_COMMENT = re.compile(r"wave-literal-ok", re.IGNORECASE)
# expiry_wave data fields and pytest skip expiry_wave args are legitimate
# historical values. GS-9 fix: also exempt comment lines that mention
# expiry_wave (e.g. "# expiry_wave: Wave 17 — burndown"), and inline
# expiry_wave references inside docstrings or test fixtures (no quotes around
# the value). Match any of:
#   expiry_wave: "Wave N"     YAML/dict literal
#   expiry_wave="Wave N"      kwarg
#   expiry_wave Wave N        comment / prose form
_EXPIRY_WAVE_PATTERN = re.compile(
    r"expiry_wave"        # the field name
    r"[\"\':\s=]+"        # punctuation between name and value (=, :, quotes, whitespace)
    r"\"?Wave\s+\d+\"?",  # the value, optionally quoted
    re.IGNORECASE,
)
_EXEMPT_FILES = frozenset({
    "_current_wave.py",
    "check_no_hardcoded_wave.py",
    # _governance/wave.py is the new canonical wave helper — exempt for the
    # same reason _current_wave.py is.
})


def main() -> int:
    parser = argparse.ArgumentParser(description="No hardcoded Wave N string gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    issues: list[dict] = []
    # Walk scripts/ recursively so the scan covers _governance/ too.
    for script in sorted(SCRIPTS_DIR.rglob("*.py")):
        if script.name in _EXEMPT_FILES:
            continue
        # Skip the canonical wave helper(s).
        if script.parent.name == "_governance" and script.name == "wave.py":
            continue
        try:
            lines = script.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if (_WAVE_PATTERN.search(line)
                    and not _EXCEPTION_COMMENT.search(line)
                    and not _EXPIRY_WAVE_PATTERN.search(line)):
                rel_path = script.relative_to(ROOT).as_posix()
                issues.append({
                    "file": rel_path,
                    "line": i,
                    "content": line.strip()[:120],
                })

    status = "pass" if not issues else "fail"
    result = {
        "status": status,
        "check": "no_hardcoded_wave",
        "issues_found": len(issues),
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in issues:
            print(f"FAIL {issue['file']}:{issue['line']}: hardcoded wave string 鈥?use current_wave() from _current_wave.py", file=sys.stderr)  # noqa: E501  # expiry_wave: Wave 26  # added: W25 baseline sweep
        if not issues:
            print("PASS: no hardcoded Wave N strings in scripts/")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

