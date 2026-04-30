#!/usr/bin/env python
"""CI gate: warn/fail if agent_server/contracts/ is modified after v1 release (R-AS-3).

When V1_RELEASED=True, running without flags runs enforce mode (blocking).
Use --snapshot to capture the current digest baseline.
Use --enforce to check file digests against the saved snapshot.

Usage:
    python scripts/check_contract_freeze.py            # human-readable enforce (post-release)
    python scripts/check_contract_freeze.py --json     # multistatus JSON enforce
    python scripts/check_contract_freeze.py --snapshot # capture digest snapshot
    python scripts/check_contract_freeze.py --enforce  # explicit enforce mode
    python scripts/check_contract_freeze.py --enforce --json  # enforce + JSON output

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS_DIR = ROOT / "agent_server" / "contracts"
SNAP_PATH = ROOT / "docs" / "governance" / "contract_v1_freeze.json"
VERSION_PY = ROOT / "agent_server" / "config" / "version.py"

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit

# V1_RELEASED flag: sourced from agent_server/config/version.py when Track K
# has landed its V1_RELEASED=True. Falls back to False until that merge occurs,
# ensuring this worktree remains advisory-only until the flag activates.
try:
    sys.path.insert(0, str(ROOT))
    from agent_server.config.version import V1_RELEASED as _VERSION_V1_RELEASED
except ImportError:
    _VERSION_V1_RELEASED = False


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True
    ).strip()


def _is_v1_released() -> bool:
    """Check V1_RELEASED flag from version.py."""
    try:
        sys.path.insert(0, str(ROOT / "agent_server" / "config"))
        import importlib.util
        spec = importlib.util.spec_from_file_location("version", VERSION_PY)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # expiry_wave: Wave 27
        spec.loader.exec_module(mod)  # type: ignore[union-attr]  # expiry_wave: Wave 27
        return bool(getattr(mod, "V1_RELEASED", False))
    except Exception:
        return False


def do_snapshot() -> None:
    """Capture SHA-256 digests of all contracts/*.py files and write the snapshot JSON."""
    if not CONTRACTS_DIR.exists():
        print(f"SKIP snapshot: {CONTRACTS_DIR} does not exist")
        sys.exit(0)

    head = _git_head(ROOT)
    digests: dict[str, str] = {}
    for f in sorted(CONTRACTS_DIR.rglob("*.py")):
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        digests[rel] = _file_sha256(f)

    snap = {"v1_frozen_head": head, "digests": digests}
    SNAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAP_PATH.write_text(json.dumps(snap, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Snapshot written: {SNAP_PATH} ({len(digests)} files, HEAD={head[:8]})")

    # Update V1_FROZEN_HEAD in version.py
    content = VERSION_PY.read_text(encoding="utf-8")
    if 'V1_FROZEN_HEAD = ""' in content:
        content = content.replace('V1_FROZEN_HEAD = ""', f'V1_FROZEN_HEAD = "{head}"')
        VERSION_PY.write_text(content, encoding="utf-8")
        print(f"Updated version.py V1_FROZEN_HEAD = \"{head}\"")


def do_enforce() -> GateResult:
    """Compare current contracts/*.py digests against the saved snapshot."""
    if not CONTRACTS_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="contract_freeze",
            reason="agent_server/contracts/ not yet created (vacuous PASS)",
            evidence={"contracts_dir_exists": False},
        )
    if not SNAP_PATH.exists():
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="contract_freeze",
            reason="no_snapshot_found: run --snapshot first to establish the baseline",
            evidence={"snapshot_path": str(SNAP_PATH), "snapshot_exists": False},
        )

    snap = json.loads(SNAP_PATH.read_text(encoding="utf-8"))
    violations: list[dict[str, str]] = []

    for rel_path, expected in snap["digests"].items():
        actual_path = ROOT / rel_path
        if not actual_path.exists():
            violations.append({"path": rel_path, "reason": "deleted"})
            continue
        actual = _file_sha256(actual_path)
        if actual != expected:
            violations.append({
                "path": rel_path,
                "reason": "modified",
                "expected": expected[:8],
                "actual": actual[:8],
            })

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="contract_freeze",
            reason=(
                f"v1 contract freeze violated: {len(violations)} file(s) differ from snapshot "
                f"(frozen at {snap['v1_frozen_head'][:8]})"
            ),
            evidence={
                "v1_frozen_head": snap["v1_frozen_head"],
                "violations": violations,
                "violation_count": len(violations),
            },
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="contract_freeze",
        reason=(
            f"all {len(snap['digests'])} contract files match snapshot "
            f"(frozen at {snap['v1_frozen_head'][:8]})"
        ),
        evidence={
            "v1_frozen_head": snap["v1_frozen_head"],
            "files_checked": len(snap["digests"]),
            "violations": [],
        },
    )


def _evaluate_legacy() -> GateResult:
    """Fallback path: git-porcelain check used before snapshot enforcement was available."""
    if not CONTRACTS_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="contract_freeze",
            reason="agent_server/contracts/ not yet created (vacuous PASS)",
            evidence={"contracts_dir_exists": False},
        )
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain",
             str(CONTRACTS_DIR.relative_to(ROOT))],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        changes = [ln for ln in result.stdout.splitlines() if ln.strip()]
    except Exception:
        changes = []

    if not changes:
        return GateResult(
            status=GateStatus.PASS,
            gate_name="contract_freeze",
            reason="no uncommitted changes to agent_server/contracts/",
            evidence={"v1_released": True, "changed_files": 0},
        )
    return GateResult(
        status=GateStatus.FAIL,
        gate_name="contract_freeze",
        reason=f"v1 RELEASED but {len(changes)} change(s) detected in contracts/",
        evidence={"v1_released": True, "changed_files": len(changes), "changes": changes},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-3 contract freeze gate.")
    parser.add_argument("--snapshot", action="store_true",
                        help="Capture digest snapshot of current contracts/.")
    parser.add_argument("--enforce", action="store_true",
                        help="Enforce digest snapshot (default when V1_RELEASED=True).")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    if args.snapshot:
        do_snapshot()
        return 0

    released = _is_v1_released()

    # Choose mode: explicit --enforce, or auto-enforce when V1_RELEASED=True with a snapshot.
    use_enforce = args.enforce or (released and SNAP_PATH.exists())

    result = do_enforce() if use_enforce else _evaluate_legacy()

    if args.json:
        emit(result)  # exits

    # Human-readable output.
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
    for v in result.evidence.get("violations", result.evidence.get("changes", [])):
        if isinstance(v, dict):
            print(f"  {v['path']} — {v['reason']}")
        else:
            print(f"  {v}")
    print("To evolve the contract, create agent_server/contracts/v2/ instead.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
