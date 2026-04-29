#!/usr/bin/env python
"""CI gate: fail if agent_server/contracts/ references forbidden domain types (R-AS-2).

Forbidden set: Paper, Phase, Hypothesis, Theorem, PIAgent, Survey, Analysis,
Experiment, Writing, Author, Reviewer, Editor, Backtrack, Citation, Lean, Dataset.

Usage: python scripts/check_no_domain_types.py
Exit 0 = clean; 1 = violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS_DIR = ROOT / "agent_server" / "contracts"

FORBIDDEN = frozenset({
    "Paper", "Phase", "Hypothesis", "Theorem", "PIAgent",
    "Survey", "Analysis", "Experiment", "Writing", "Author",
    "Reviewer", "Editor", "Backtrack", "Citation", "Lean", "Dataset",
})

# Match whole words only to avoid false positives (e.g., "BacktrackStrategy")
def _make_pattern(words: frozenset[str]) -> re.Pattern:
    alts = "|".join(re.escape(w) for w in sorted(words))
    return re.compile(rf'\b({alts})\b')

PATTERN = _make_pattern(FORBIDDEN)


def check() -> int:
    if not CONTRACTS_DIR.exists():
        print("PASS (R-AS-2): agent_server/contracts/ not yet created — skipping")
        return 0

    violations = []
    for py_file in sorted(CONTRACTS_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            m = PATTERN.search(line)
            if m:
                violations.append(
                    f"  {py_file.relative_to(ROOT)}:{lineno}: {line.strip()} "
                    f"[found: {m.group(1)!r}]"
                )

    if violations:
        print(f"FAIL (R-AS-2): {len(violations)} forbidden domain type(s) in contracts/:")
        for v in violations:
            print(v)
        return 1
    print("PASS (R-AS-2): no forbidden domain types in agent_server/contracts/")
    return 0


if __name__ == "__main__":
    sys.exit(check())
