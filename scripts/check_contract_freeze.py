#!/usr/bin/env python
"""CI gate: warn/fail if agent_server/contracts/ is modified after v1 release (R-AS-3).

ADVISORY until the v1 RELEASED notice is published (W25). After release,
this gate becomes blocking.

Usage: python scripts/check_contract_freeze.py
Exit 0 = ok or advisory warning; 2 = blocking violation after release.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS_DIR = ROOT / "agent_server" / "contracts"
V1_RELEASE_NOTICE = ROOT / "docs" / "downstream-responses" / "w25-agent-server-v1-release-notice.md"


def is_v1_released() -> bool:
    """Return True if the v1 release notice exists and has Status: RELEASED."""
    if not V1_RELEASE_NOTICE.exists():
        return False
    text = V1_RELEASE_NOTICE.read_text(encoding="utf-8")
    return "Status: RELEASED" in text


def get_uncommitted_contracts_changes() -> list[str]:
    """Return list of uncommitted changes to agent_server/contracts/."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", str(CONTRACTS_DIR.relative_to(ROOT))],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        return [ln for ln in result.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def check() -> int:
    if not CONTRACTS_DIR.exists():
        print("PASS (R-AS-3): agent_server/contracts/ not yet created")
        return 0

    released = is_v1_released()
    changes = get_uncommitted_contracts_changes()

    if not changes:
        print("PASS (R-AS-3): no uncommitted changes to agent_server/contracts/")
        return 0

    if released:
        print(f"FAIL (R-AS-3): v1 is RELEASED but {len(changes)} change(s) detected in contracts/:")
        for c in changes:
            print(f"  {c}")
        print("To evolve the contract, create agent_server/contracts/v2/ instead.")
        return 2  # blocking

    print(f"WARN (R-AS-3, advisory): {len(changes)} change(s) in contracts/ — OK until v1 RELEASED")
    for c in changes:
        print(f"  {c}")
    return 0  # advisory, not blocking yet


if __name__ == "__main__":
    sys.exit(check())
