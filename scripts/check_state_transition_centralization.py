#!/usr/bin/env python
"""CI gate: fail if any direct run.state = ... assignment exists outside run_state_transitions.py.

Usage:
    python scripts/check_state_transition_centralization.py
    python scripts/check_state_transition_centralization.py --json

Exit 0 = PASS; 1 = FAIL.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXEMPT_FILES = {
    ROOT / "hi_agent" / "server" / "run_state_transitions.py",
}
EXEMPT_DIRS = {
    ROOT / "tests",
    ROOT / "scripts",
}

sys.path.insert(0, str(ROOT / "scripts"))
from _governance.multistatus import GateResult, GateStatus, emit

# See header docstring of original W22-A5 gate for pattern rationale.
PATTERN = re.compile(r'^\s+\b\w*run\b\.\bstate\s+=[^=]')


def _evaluate() -> GateResult:
    violations: list[str] = []
    files_scanned = 0
    for py_file in sorted(ROOT.rglob("*.py")):
        if py_file in EXEMPT_FILES:
            continue
        parts = py_file.parts
        if ".git" in parts or "__pycache__" in parts or ".claude" in parts:
            continue
        if any(py_file.is_relative_to(d) for d in EXEMPT_DIRS):
            continue
        files_scanned += 1
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                violations.append(f"{py_file.relative_to(ROOT)}:{lineno}: {line.strip()}")

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="state_transition_centralization",
            reason=(
                f"{len(violations)} direct run.state assignment(s) outside "
                "run_state_transitions.py"
            ),
            evidence={"files_scanned": files_scanned, "violations": violations},
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="state_transition_centralization",
        reason="no direct run.state assignments outside run_state_transitions.py",
        evidence={"files_scanned": files_scanned},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="State-transition centralization gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS: {result.reason}")
        return 0
    print(f"FAIL: {result.reason}:")
    for v in result.evidence.get("violations", []):
        print(f"  {v}")
    print("\nFix: use hi_agent.server.run_state_transitions.transition() instead.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
