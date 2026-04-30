#!/usr/bin/env python
"""CI gate: fail if agent_server/contracts/ references forbidden domain types (R-AS-2).

Forbidden set: Paper, Phase, Hypothesis, Theorem, PIAgent, Survey, Analysis,
Experiment, Writing, Author, Reviewer, Editor, Backtrack, Citation, Lean, Dataset.

Usage:
    python scripts/check_no_domain_types.py
    python scripts/check_no_domain_types.py --json

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

FORBIDDEN = frozenset({
    "Paper", "Phase", "Hypothesis", "Theorem", "PIAgent",
    "Survey", "Analysis", "Experiment", "Writing", "Author",
    "Reviewer", "Editor", "Backtrack", "Citation", "Lean", "Dataset",
})


def _make_pattern(words: frozenset[str]) -> re.Pattern:
    alts = "|".join(re.escape(w) for w in sorted(words))
    return re.compile(rf'\b({alts})\b')


PATTERN = _make_pattern(FORBIDDEN)


def _evaluate() -> GateResult:
    if not CONTRACTS_DIR.exists():
        return GateResult(
            status=GateStatus.PASS,
            gate_name="no_domain_types",
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
            m = PATTERN.search(line)
            if m:
                violations.append(
                    f"{py_file.relative_to(ROOT)}:{lineno}: {line.strip()} "
                    f"[found: {m.group(1)!r}]"
                )

    if violations:
        return GateResult(
            status=GateStatus.FAIL,
            gate_name="no_domain_types",
            reason=f"{len(violations)} forbidden domain type(s) in contracts/",
            evidence={"files_scanned": files_scanned, "violations": violations},
        )
    return GateResult(
        status=GateStatus.PASS,
        gate_name="no_domain_types",
        reason="no forbidden domain types in agent_server/contracts/",
        evidence={"files_scanned": files_scanned},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="R-AS-2 domain types gate.")
    parser.add_argument("--json", action="store_true", help="Emit multistatus JSON.")
    args = parser.parse_args()

    result = _evaluate()
    if args.json:
        emit(result)

    if result.status is GateStatus.PASS:
        print(f"PASS (R-AS-2): {result.reason}")
        return 0
    print(f"FAIL (R-AS-2): {result.reason}:")
    for v in result.evidence.get("violations", []):
        print(f"  {v}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
