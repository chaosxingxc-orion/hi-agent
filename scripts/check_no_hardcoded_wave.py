#!/usr/bin/env python3
"""W14-A4: No hardcoded Wave N strings outside _current_wave.py and docs/.

W31-D D-2' extension: scope expanded from scripts/ alone to scripts/ + tests/.
W32-D D.2 extension: scan radius extended to hi_agent/ and agent_server/ so
production-code wave-string literals are also caught. File-level top-of-module
``# expiry_wave: Wave N`` markers (placed in a module docstring or as a
top-of-module comment for re-export shims with a documented removal target)
are permitted; inline quoted-string Wave-N literals in the code path are
rejected.

Wave-bound test fixtures should source the wave from _governance.wave just
like production scripts do, so a wave bump only needs the canonical file
edited.

Scans scripts/*.py, tests/*.py, hi_agent/*.py, agent_server/*.py for patterns
like "Wave 14", "Wave 13", "Wave N" (quoted-string literal form) that should
be loaded from scripts/_governance/wave.py instead.

Allowed exceptions:
- scripts/_current_wave.py (the source of truth, deprecated re-export)
- scripts/_governance/wave.py (the canonical wave reader)
- docs/ directory (documentation and governance files)
- Any line with a comment # wave-literal-ok
- Any line containing an `expiry_wave: Wave N` annotation (legitimate
  historical value; per-line marker, not enforcement). This covers both
  the per-line `# expiry_wave: Wave N` form on noqa lines (compat-shim
  pattern) and any explicit `expiry_wave="Wave N"` kwarg form.

Exit 0: pass (no hardcoded wave strings found in any scanned tree).
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
TESTS_DIR = ROOT / "tests"
HI_AGENT_DIR = ROOT / "hi_agent"
AGENT_SERVER_DIR = ROOT / "agent_server"
# W31-D D-2': directories scanned for hardcoded wave strings.
# W32-D D.2: extended to production code (hi_agent/, agent_server/) so
# inline string-literal hits in production are caught. File-level top-of-
# module markers and per-line `# expiry_wave: Wave N` annotations remain
# exempt via _EXPIRY_WAVE_PATTERN.
_SCAN_DIRS: tuple[pathlib.Path, ...] = (
    SCRIPTS_DIR,
    TESTS_DIR,
    HI_AGENT_DIR,
    AGENT_SERVER_DIR,
)

_WAVE_PATTERN = re.compile(r'"Wave\s+\d+"', re.IGNORECASE)
_EXCEPTION_COMMENT = re.compile(r"wave-literal-ok", re.IGNORECASE)
# expiry_wave data fields and pytest skip expiry_wave args are legitimate
# historical values. GS-9 fix: also exempt comment lines that mention
# expiry_wave (e.g. "# expiry_wave: Wave 30 — burndown"), and inline
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
    # W31-D D-2': test files whose explicit purpose is to test wave-string
    # parsing/formatting carry intentional wave literals (test fixtures). They
    # must use literal strings to assert the parse/format contract.
    "test_wave.py",
    "test_check_wave_consistency.py",
    "test_check_recurrence_ledger.py",
    "test_check_manifest_rewrite_budget.py",
    "test_manifest_consensus.py",
    # W32-D D.2: test for the gate itself; carries intentional wave-string
    # fixtures (`"Wave 99"`) that exercise the rejection path.
    "test_check_no_hardcoded_wave.py",
})


def main() -> int:
    parser = argparse.ArgumentParser(description="No hardcoded Wave N string gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    issues: list[dict] = []
    # W31-D D-2': walk scripts/ and tests/ recursively. Single loop with the
    # same exemption rules.
    for scan_root in _SCAN_DIRS:
        if not scan_root.is_dir():
            continue
        for src in sorted(scan_root.rglob("*.py")):
            if src.name in _EXEMPT_FILES:
                continue
            # Skip the canonical wave helper(s).
            if src.parent.name == "_governance" and src.name == "wave.py":
                continue
            try:
                lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if (_WAVE_PATTERN.search(line)
                        and not _EXCEPTION_COMMENT.search(line)
                        and not _EXPIRY_WAVE_PATTERN.search(line)):
                    rel_path = src.relative_to(ROOT).as_posix()
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
            print(f"FAIL {issue['file']}:{issue['line']}: hardcoded wave string -- use current_wave_number() from _governance.wave", file=sys.stderr)  # noqa: E501  # expiry_wave: permanent  # added: W25 baseline sweep
        if not issues:
            print("PASS: no hardcoded Wave N strings in scripts/ or tests/")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

