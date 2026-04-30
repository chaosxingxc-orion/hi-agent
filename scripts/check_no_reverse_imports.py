#!/usr/bin/env python
"""CI gate: fail if hi_agent/ imports anything from agent_server (R-AS-1).

The import direction must be one-way: agent_server imports from hi_agent,
never the reverse.

Usage:
    python scripts/check_no_reverse_imports.py
    python scripts/check_no_reverse_imports.py --json

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit

IMPORT_PATTERN = re.compile(r'^\s*(import|from)\s+agent_server', re.MULTILINE)


def _evaluate() -> GateResult:
    violations: list[str] = []
    files_scanned = 0
    hi_agent_root = ROOT / "hi_agent"
    if not hi_agent_root.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="no_reverse_imports",
            reason="hi_agent/ not present (vacuous PASS)",
            evidence={"hi_agent_dir_exists": False},
        )
    for py_file in sorted(hi_agent_root.rglob("*.py")):
        parts = py_file.parts
        if ".git" in parts or "__pycache__" in parts:
            continue
        files_scanned += 1
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if IMPORT_PATTERN.match(line):
                violations.append(f"{py_file.relative_to(ROOT)}:{lineno}: {line.strip()}")

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="no_reverse_imports",
            reason=f"{len(violations)} reverse import(s) from hi_agent/ into agent_server",
            evidence={"files_scanned": files_scanned, "violations": violations},
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="no_reverse_imports",
        reason="no reverse imports from hi_agent/ into agent_server",
        evidence={"files_scanned": files_scanned},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-1 reverse-import gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS (R-AS-1): {result.reason}")
        return 0
    print(f"FAIL (R-AS-1): {result.reason}:")
    for v in result.evidence.get("violations", []):
        print(f"  {v}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
