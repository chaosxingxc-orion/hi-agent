#!/usr/bin/env python3
"""CI gate: governance docs must not contradict code reality.

Checks:
1. Delivery notices: no T3 evidence line claiming 'inherited' without a real SHA in docs/delivery/.
2. Capability matrix: L-level claims don't cite xfail/skip tests.
3. Test files: no 'has not (yet )?landed' stale comments (unless noqa: stale-claim).
4. Source files: no '# TODO: wire real run_id' or similar TODO-spine violations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"


def check_t3_inherited_claims() -> list[str]:
    """T3 'inherited' claims must reference a real SHA in docs/delivery/."""
    errors = []
    delivery_dir = DOCS / "delivery"
    for notice in DOCS.glob("downstream-responses/*delivery-notice*.md"):
        src = notice.read_text(encoding="utf-8", errors="replace")
        # Look for 'T3 inherited' pattern
        for line in src.splitlines():
            if re.search(r"T3.*inherited", line, re.IGNORECASE):
                # Extract SHA if present
                sha_match = re.search(r"\b([0-9a-f]{7,40})\b", line)
                if sha_match:
                    sha = sha_match.group(1)
                    # Check if sha appears in any delivery JSON
                    if delivery_dir.exists():
                        matching = list(delivery_dir.glob(f"*{sha[:7]}*"))
                    else:
                        matching = []
                    if not matching:
                        errors.append(
                            f"  {notice.relative_to(ROOT)}: T3 inherited claim references "
                            f"SHA {sha} but no matching docs/delivery/ file found"
                        )
                else:
                    errors.append(
                        f"  {notice.relative_to(ROOT)}: T3 inherited claim with no SHA — "
                        "must be changed to DEFERRED or cite real evidence"
                    )
    return errors


def check_matrix_xfail_citations() -> list[str]:
    """Capability matrix must not cite xfail/skip tests as evidence."""
    errors = []
    matrix = DOCS / "platform-capability-matrix.md"
    if not matrix.exists():
        return errors
    src = matrix.read_text(encoding="utf-8", errors="replace")
    # Find test file references
    for m in re.finditer(r"(tests/[\w/]+\.py)", src):
        test_path = ROOT / m.group(1)
        if not test_path.exists():
            continue
        test_src = test_path.read_text(encoding="utf-8", errors="replace")
        if "pytest.mark.xfail" in test_src or "pytest.mark.skip" in test_src:
            errors.append(
                f"  platform-capability-matrix.md cites {m.group(1)} "
                "which contains xfail/skip marks — not valid evidence"
            )
    return errors


def check_stale_not_landed_comments() -> list[str]:
    """Source and test files must not have 'has not (yet) landed' stale comments."""
    errors = []
    pattern = re.compile(r"has not (yet )?landed", re.IGNORECASE)
    for path in ROOT.glob("hi_agent/**/*.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(src.splitlines(), 1):
            if pattern.search(line) and "noqa: stale-claim" not in line:
                errors.append(f"  {path.relative_to(ROOT)}:{i}: stale 'not landed' comment")
    for path in ROOT.glob("tests/**/*.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(src.splitlines(), 1):
            if pattern.search(line) and "noqa: stale-claim" not in line:
                errors.append(f"  {path.relative_to(ROOT)}:{i}: stale 'not landed' comment")
    return errors


def check_todo_spine_violations() -> list[str]:
    """Source files must not have TODO: wire real run_id or similar spine TODOs."""
    errors = []
    pattern = re.compile(r"#\s*TODO:.*wire real (run_id|tenant_id|session_id)", re.IGNORECASE)
    for path in ROOT.glob("hi_agent/**/*.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(src.splitlines(), 1):
            if pattern.search(line):
                errors.append(
                    f"  {path.relative_to(ROOT)}:{i}: TODO spine violation — {line.strip()}"
                )
    return errors


def main() -> int:
    all_errors = []
    all_errors.extend(check_t3_inherited_claims())
    all_errors.extend(check_matrix_xfail_citations())
    all_errors.extend(check_stale_not_landed_comments())
    all_errors.extend(check_todo_spine_violations())
    if all_errors:
        print("FAIL check_doc_consistency:")
        for e in all_errors:
            print(e)
        return 1
    print("OK check_doc_consistency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
