#!/usr/bin/env python
"""CI gate: fail if any agent_server/facade/*.py exceeds 200 LOC (R-AS-8).

Facade modules must be thin adapters, not business logic containers.

Usage:
    python scripts/check_facade_loc.py
    python scripts/check_facade_loc.py --json

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FACADE_DIR = ROOT / "agent_server" / "facade"
MAX_LOC = 200

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit


def count_loc(path: Path) -> int:
    """Count non-empty, non-comment lines."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0
    return sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))


def _evaluate() -> GateResult:
    if not FACADE_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="facade_loc",
            reason="agent_server/facade/ not yet created (vacuous PASS)",
            evidence={"facade_dir_exists": False, "max_loc": MAX_LOC},
        )

    violations: list[str] = []
    files_scanned = 0
    for py_file in sorted(FACADE_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts or py_file.name == "__init__.py":
            continue
        files_scanned += 1
        loc = count_loc(py_file)
        if loc > MAX_LOC:
            violations.append(f"{py_file.relative_to(ROOT)}: {loc} LOC (max {MAX_LOC})")

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="facade_loc",
            reason=f"{len(violations)} facade module(s) exceed {MAX_LOC} LOC",
            evidence={"files_scanned": files_scanned, "max_loc": MAX_LOC, "violations": violations},
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="facade_loc",
        reason=f"all facade modules within {MAX_LOC} LOC limit",
        evidence={"files_scanned": files_scanned, "max_loc": MAX_LOC},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-8 facade LOC gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS (R-AS-8): {result.reason}")
        return 0
    print(f"FAIL (R-AS-8): {result.reason}:")
    for v in result.evidence.get("violations", []):
        print(f"  {v}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
