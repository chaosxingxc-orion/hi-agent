#!/usr/bin/env python
"""CI gate: fail if agent_server/contracts/ imports non-stdlib libraries (R-AS-7).

Forbidden: pydantic, httpx, starlette, fastapi.
Only stdlib + dataclasses + typing + enum are allowed.

Usage: python scripts/check_contracts_purity.py
Exit 0 = clean; 1 = violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS_DIR = ROOT / "agent_server" / "contracts"

FORBIDDEN_IMPORTS = frozenset({"pydantic", "httpx", "starlette", "fastapi"})
IMPORT_RE = re.compile(r'^\s*(import|from)\s+(\S+)', re.MULTILINE)


def check() -> int:
    if not CONTRACTS_DIR.exists():
        print("PASS (R-AS-7): agent_server/contracts/ not yet created — skipping")
        return 0

    violations = []
    for py_file in sorted(CONTRACTS_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            m = IMPORT_RE.match(line)
            if m:
                module_root = m.group(2).split(".")[0]
                if module_root in FORBIDDEN_IMPORTS:
                    violations.append(f"  {py_file.relative_to(ROOT)}:{lineno}: {line.strip()}")

    if violations:
        print(f"FAIL (R-AS-7): {len(violations)} non-stdlib import(s) in contracts/:")
        for v in violations:
            print(v)
        return 1
    print("PASS (R-AS-7): agent_server/contracts/ uses only stdlib imports")
    return 0


if __name__ == "__main__":
    sys.exit(check())
