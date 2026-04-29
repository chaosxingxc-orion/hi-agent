#!/usr/bin/env python
"""CI gate: fail if hi_agent/ imports anything from agent_server (R-AS-1).

The import direction must be one-way: agent_server imports from hi_agent,
never the reverse.

Usage: python scripts/check_no_reverse_imports.py
Exit 0 = clean; 1 = violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Pattern: import agent_server or from agent_server
IMPORT_PATTERN = re.compile(r'^\s*(import|from)\s+agent_server', re.MULTILINE)


def check() -> int:
    violations = []
    for py_file in sorted(ROOT.rglob("*.py")):
        parts = py_file.parts
        if "hi_agent" not in parts:
            continue
        if ".git" in parts or "__pycache__" in parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if IMPORT_PATTERN.match(line):
                violations.append(f"  {py_file.relative_to(ROOT)}:{lineno}: {line.strip()}")

    if violations:
        count = len(violations)
        print(f"FAIL (R-AS-1): {count} reverse import(s) from hi_agent/ into agent_server:")
        for v in violations:
            print(v)
        return 1
    print("PASS (R-AS-1): no reverse imports from hi_agent/ into agent_server")
    return 0


if __name__ == "__main__":
    sys.exit(check())
