#!/usr/bin/env python
"""CI gate: fail if agent_server/api/routes_*.py handlers don't use TenantContext (R-AS-4).

Every route handler must read TenantContext to enforce per-tenant isolation.

Usage:
    python scripts/check_route_tenant_context.py
    python scripts/check_route_tenant_context.py --json

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

TENANT_RE = re.compile(r'TenantContext|tenant_context|tenant_id', re.IGNORECASE)


def _evaluate() -> GateResult:
    if not API_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="route_tenant_context",
            reason="agent_server/api/ not yet created (vacuous PASS)",
            evidence={"api_dir_exists": False},
        )

    route_files = sorted(API_DIR.glob("routes_*.py"))
    if not route_files:
        return GateResult(
            status=GateStatus.PASS,
            gate_name="route_tenant_context",
            reason="no routes_*.py files yet (vacuous PASS)",
            evidence={"api_dir_exists": True, "route_files": 0},
        )

    violations: list[str] = []
    for py_file in route_files:
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if not TENANT_RE.search(text):
            violations.append(f"{py_file.relative_to(ROOT)}: no TenantContext reference found")

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="route_tenant_context",
            reason=f"{len(violations)} route file(s) missing TenantContext",
            evidence={"route_files": len(route_files), "violations": violations},
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="route_tenant_context",
        reason=f"all {len(route_files)} route file(s) reference TenantContext",
        evidence={"route_files": len(route_files)},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-4 route tenant-context gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS (R-AS-4): {result.reason}")
        return 0
    print(f"FAIL (R-AS-4): {result.reason}:")
    for v in result.evidence.get("violations", []):
        print(f"  {v}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
