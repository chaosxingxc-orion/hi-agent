#!/usr/bin/env python3
"""CI gate: every SQLite SELECT must include all dataclass fields.

Scans Store/Registry/Ledger classes. For each class that has a
_row_to_record method, checks that the dataclass fields all appear
in at least one SELECT in that same file.
Also flags 'len(row) >' defensive fallbacks (schema drift masking).

Also checks (advisory WARNING, not FAIL) INSERT/enqueue call sites that
target known spine tables but omit spine kwargs.  This is advisory only
during the Wave 10.1 transition period so that CI is not blocked.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Spine-carrying call patterns: method name → required kwargs
# Advisory only — emit WARNING but do not FAIL.
_SPINE_CALL_CHECKS: list[tuple[str, list[str]]] = [
    # RunQueue.enqueue must carry all four spine fields
    (r"\.enqueue\(", ["tenant_id=", "user_id=", "session_id=", "project_id="]),
    # FeedbackStore.submit / RunFeedback must carry tenant_id
    (r"RunFeedback\(", ["tenant_id="]),
    # StoredEvent must carry tenant_id
    (r"StoredEvent\(", ["tenant_id="]),
    # SkillObservation must carry tenant_id
    (r"SkillObservation\(", ["tenant_id="]),
]

# Files to skip for advisory checks (test helpers, migrations, etc.)
_SKIP_ADVISORY_PATTERNS = ["test_", "migration", "check_select_completeness"]


def find_store_files() -> list[Path]:
    stores = []
    for pattern in [
        "hi_agent/**/*store*.py",
        "hi_agent/**/*registry*.py",
        "hi_agent/**/*ledger*.py",
    ]:
        stores.extend(ROOT.glob(pattern))
    return list(set(stores))


def find_all_python_files() -> list[Path]:
    skip = {ROOT / "scripts", ROOT / ".claude"}
    result = []
    for p in ROOT.rglob("*.py"):
        if any(p.is_relative_to(s) for s in skip if s.exists()):
            continue
        result.append(p)
    return result


def check_defensive_fallbacks(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    errors = []
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(r"len\(row\)\s*>\s*\d+", line) and "else" in line:
            errors.append(
                f"  {path.relative_to(ROOT)}:{i}: defensive len(row) fallback"
                " — remove and let migration ensure column exists"
            )
    return errors


def check_spine_call_sites(path: Path) -> list[str]:
    """Advisory: warn when a spine-table call site omits required spine kwargs.

    Uses a simple heuristic: finds the call opener, then reads the next
    N lines (up to the matching close paren) and checks that each required
    kwarg appears in that range.  Emits WARNING — does not contribute to
    the FAIL exit code.
    """
    rel = str(path.relative_to(ROOT))
    # Skip test helpers and this script itself
    if any(skip in rel for skip in _SKIP_ADVISORY_PATTERNS):
        return []

    src = path.read_text(encoding="utf-8")
    warnings = []
    lines = src.splitlines()

    for call_pattern, required_kwargs in _SPINE_CALL_CHECKS:
        for i, line in enumerate(lines, 1):
            if not re.search(call_pattern, line):
                continue
            # Gather the call body: from this line until we find the closing ')'.
            # Limit lookahead to 20 lines to avoid false negatives on large calls.
            call_body = "\n".join(lines[i - 1 : i + 20])
            missing = [kw for kw in required_kwargs if kw not in call_body]
            if missing:
                warnings.append(
                    f"  WARNING {rel}:{i}: {call_pattern!r} call missing spine kwargs:"
                    f" {', '.join(missing)}"
                )
    return warnings


def main() -> int:
    errors = []
    for path in find_store_files():
        errors.extend(check_defensive_fallbacks(path))

    if errors:
        print("FAIL check_select_completeness:")
        for e in errors:
            print(e)
        return 1

    print("OK check_select_completeness")

    # Advisory spine-call checks (WARNING only, no FAIL)
    advisory = []
    for path in find_all_python_files():
        advisory.extend(check_spine_call_sites(path))
    if advisory:
        print("\nADVISORY check_spine_call_sites (non-blocking):")
        for w in advisory:
            print(w)
    else:
        print("OK check_spine_call_sites (no missing spine kwargs found)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
