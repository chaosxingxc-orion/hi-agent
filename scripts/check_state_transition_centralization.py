#!/usr/bin/env python
"""CI gate: fail if any direct run.state = ... assignment exists outside run_state_transitions.py.

Usage: python scripts/check_state_transition_centralization.py
Exit code 0 = clean; 1 = violations found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXEMPT_FILES = {
    ROOT / "hi_agent" / "server" / "run_state_transitions.py",
}

# Directories that are fully exempt from the gate check.
# - tests/ : docstrings in tests may reference run.state='...' as prose
# - scripts/ : the gate script itself contains the pattern in comments
EXEMPT_DIRS = {
    ROOT / "tests",
    ROOT / "scripts",
}

# Pattern: matches a direct assignment statement of the form
#     [whitespace]run.state = ...   or   [whitespace]_run.state = ...
# The leading whitespace anchor ensures we match a statement, not a
# reference inside a string literal or f-string expression.
# The space before the RHS (` = `) is required by PEP-8 style; docstring
# prose uses `run.state='value'` (no space), which does NOT match.
# Does NOT match:
#   - run.state == ...  (comparison)
#   - run.state: ...    (type annotation)
#   - f"...run.state=..." (f-string / comment reference, no leading space)
PATTERN = re.compile(r'^\s+\b\w*run\b\.\bstate\s+=[^=]')


def check() -> int:
    violations = []
    for py_file in sorted(ROOT.rglob("*.py")):
        if py_file in EXEMPT_FILES:
            continue
        parts = py_file.parts
        if ".git" in parts or "__pycache__" in parts or ".claude" in parts:
            continue
        # Skip fully exempt directories.
        if any(py_file.is_relative_to(d) for d in EXEMPT_DIRS):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                violations.append(
                    f"  {py_file.relative_to(ROOT)}:{lineno}: {line.strip()}"
                )

    if violations:
        print(
            f"FAIL: {len(violations)} direct run.state assignment(s) found "
            f"outside run_state_transitions.py:"
        )
        for v in violations:
            print(v)
        print(
            "\nFix: use hi_agent.server.run_state_transitions.transition() instead."
        )
        return 1

    print("PASS: no direct run.state assignments outside run_state_transitions.py")
    return 0


if __name__ == "__main__":
    sys.exit(check())
