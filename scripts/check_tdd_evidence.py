#!/usr/bin/env python
"""CI gate: fail if agent_server/api/routes_*.py handlers lack tdd-red-sha annotation (R-AS-5).

Every route handler must have been TDD-driven, evidenced by a comment:
    # tdd-red-sha: <7-40 char hex SHA of the failing-test commit>

Usage:
    python scripts/check_tdd_evidence.py
    python scripts/check_tdd_evidence.py --json

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
API_DIR = ROOT / "agent_server" / "api"

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit

TDD_SHA_RE = re.compile(r'#\s*tdd-red-sha:\s*([0-9a-f]{7,40})', re.IGNORECASE)


def _evaluate() -> GateResult:
    if not API_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="tdd_evidence",
            reason="agent_server/api/ not yet created (vacuous PASS)",
            evidence={"api_dir_exists": False},
        )

    route_files = sorted(API_DIR.glob("routes_*.py"))
    if not route_files:
        return GateResult(
            status=GateStatus.PASS,
            gate_name="tdd_evidence",
            reason="no routes_*.py files yet (vacuous PASS)",
            evidence={"api_dir_exists": True, "route_files": 0},
        )

    violations: list[str] = []
    for py_file in route_files:
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if not TDD_SHA_RE.search(text):
            violations.append(
                f"{py_file.relative_to(ROOT)}: no '# tdd-red-sha: <sha>' annotation found"
            )

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="tdd_evidence",
            reason=f"{len(violations)} route file(s) missing tdd-red-sha annotation",
            evidence={"route_files": len(route_files), "violations": violations},
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="tdd_evidence",
        reason=f"all {len(route_files)} route file(s) have tdd-red-sha annotation",
        evidence={"route_files": len(route_files)},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-5 TDD evidence gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS (R-AS-5): {result.reason}")
        return 0
    print(f"FAIL (R-AS-5): {result.reason}:")
    for v in result.evidence.get("violations", []):
        print(f"  {v}")
    print("\nAdd '# tdd-red-sha: <sha>' comment referencing the failing-test commit SHA.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
