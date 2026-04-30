#!/usr/bin/env python
"""CI gate: warn/fail if agent_server/contracts/ is modified after v1 release (R-AS-3).

ADVISORY until the v1 RELEASED notice is published (W25). After release,
this gate becomes blocking.

Usage:
    python scripts/check_contract_freeze.py            # human-readable
    python scripts/check_contract_freeze.py --json     # multistatus JSON

Exit 0 = PASS / WARN; 1 = FAIL (post-release violation).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS_DIR = ROOT / "agent_server" / "contracts"
V1_RELEASE_NOTICE = ROOT / "docs" / "downstream-responses" / "w25-agent-server-v1-release-notice.md"

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit


def is_v1_released() -> bool:
    if not V1_RELEASE_NOTICE.exists():
        return False
    text = V1_RELEASE_NOTICE.read_text(encoding="utf-8")
    return "Status: RELEASED" in text


def get_uncommitted_contracts_changes() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", str(CONTRACTS_DIR.relative_to(ROOT))],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        return [ln for ln in result.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def _evaluate() -> GateResult:
    if not CONTRACTS_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="contract_freeze",
            reason="agent_server/contracts/ not yet created (vacuous PASS)",
            evidence={"contracts_dir_exists": False},
        )
    released = is_v1_released()
    changes = get_uncommitted_contracts_changes()
    if not changes:
        return GateResult(
            status=GateStatus.PASS,
            gate_name="contract_freeze",
            reason="no uncommitted changes to agent_server/contracts/",
            evidence={"v1_released": released, "changed_files": 0},
        )
    if released:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="contract_freeze",
            reason=f"v1 RELEASED but {len(changes)} change(s) detected in contracts/",
            evidence={"v1_released": True, "changed_files": len(changes), "changes": changes},
        )
    return GateResult(
        status=GateStatus.WARN,
        gate_name="contract_freeze",
        reason=f"{len(changes)} change(s) in contracts/ — advisory until v1 RELEASED",
        evidence={"v1_released": False, "changed_files": len(changes), "changes": changes},
        expiry_wave=25,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-3 contract freeze gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)  # exits

    # Human-readable backward-compat path.
    if result.status is GateStatus.PASS:
        print(f"PASS (R-AS-3): {result.reason}")
        return 0
    if result.status is GateStatus.WARN:
        print(f"WARN (R-AS-3, advisory): {result.reason}")
        for c in result.evidence.get("changes", []):
            print(f"  {c}")
        return 0
    # FAIL
    print(f"FAIL (R-AS-3): {result.reason}")
    for c in result.evidence.get("changes", []):
        print(f"  {c}")
    print("To evolve the contract, create agent_server/contracts/v2/ instead.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
