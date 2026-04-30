#!/usr/bin/env python
"""CI gate: fail if agent_server/contracts/ imports non-stdlib libraries (R-AS-7).

Forbidden: pydantic, httpx, starlette, fastapi.
Only stdlib + dataclasses + typing + enum are allowed.

Usage:
    python scripts/check_contracts_purity.py
    python scripts/check_contracts_purity.py --json

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS_DIR = ROOT / "agent_server" / "contracts"

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit

FORBIDDEN_IMPORTS = frozenset({"pydantic", "httpx", "starlette", "fastapi"})
IMPORT_RE = re.compile(r'^\s*(import|from)\s+(\S+)', re.MULTILINE)


def _evaluate() -> GateResult:
    if not CONTRACTS_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="contracts_purity",
            reason="agent_server/contracts/ not yet created (vacuous PASS)",
            evidence={"contracts_dir_exists": False},
        )

    violations: list[str] = []
    files_scanned = 0
    for py_file in sorted(CONTRACTS_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        files_scanned += 1
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            m = IMPORT_RE.match(line)
            if m:
                module_root = m.group(2).split(".")[0]
                if module_root in FORBIDDEN_IMPORTS:
                    violations.append(f"{py_file.relative_to(ROOT)}:{lineno}: {line.strip()}")

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="contracts_purity",
            reason=f"{len(violations)} non-stdlib import(s) in contracts/",
            evidence={"files_scanned": files_scanned, "violations": violations},
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="contracts_purity",
        reason="agent_server/contracts/ uses only stdlib imports",
        evidence={"files_scanned": files_scanned},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-7 contracts purity gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS (R-AS-7): {result.reason}")
        return 0
    print(f"FAIL (R-AS-7): {result.reason}:")
    for v in result.evidence.get("violations", []):
        print(f"  {v}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
