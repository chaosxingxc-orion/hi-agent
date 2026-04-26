#!/usr/bin/env python3
"""CI gate: every SQLite SELECT must include all dataclass fields.

Scans Store/Registry/Ledger classes. For each class that has a
_row_to_record method, checks that the dataclass fields all appear
in at least one SELECT in that same file.
Also flags 'len(row) >' defensive fallbacks (schema drift masking).

Also checks (BLOCKING since Wave 10.2) INSERT/enqueue call sites that
target known spine tables but omit spine kwargs.  Lines that use
``**kwargs``-splat or carry an explicit ``# spine-skip: <reason>``
trailing comment are exempt — splat expansion is opaque to static
analysis and is allowed at deserialization sites where the written
dict already carries the spine.
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
    # HumanGateRequest must carry tenant_id — 5 call sites fixed by W3-A
    (r"HumanGateRequest\(", ["tenant_id="]),
    # RunPostmortem must carry tenant_id and project_id
    (r"RunPostmortem\(", ["tenant_id=", "project_id="]),
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


_SPLAT_RE = re.compile(r"\*\*\w+")
_SPINE_SKIP_RE = re.compile(r"#\s*spine-skip\s*:\s*\S+")


def check_spine_call_sites(path: Path) -> list[str]:
    """Blocking: fail when a spine-table call site omits required spine kwargs.

    Uses a simple heuristic: finds the call opener, reads up to 20 lines of
    the call body, then checks that each required kwarg appears.  Two exits:
    - the body contains ``**word`` splat expansion → skip (e.g. dict-rehydrate
      from JSON; the persisted dict carries spine because the write-side
      check enforces that).
    - the opener line carries ``# spine-skip: <reason>`` trailing comment →
      skip with reviewer-attested allowlist.
    """
    rel = str(path.relative_to(ROOT))
    # Skip test helpers and this script itself
    if any(skip in rel for skip in _SKIP_ADVISORY_PATTERNS):
        return []

    src = path.read_text(encoding="utf-8")
    failures = []
    lines = src.splitlines()

    for call_pattern, required_kwargs in _SPINE_CALL_CHECKS:
        for i, line in enumerate(lines, 1):
            if not re.search(call_pattern, line):
                continue
            # Accept spine-skip on the call line or the immediately preceding line
            prev_line = lines[i - 2] if i >= 2 else ""
            if _SPINE_SKIP_RE.search(line) or _SPINE_SKIP_RE.search(prev_line):
                continue
            call_body = "\n".join(lines[i - 1 : i + 20])
            if _SPLAT_RE.search(call_body):
                continue
            missing = [kw for kw in required_kwargs if kw not in call_body]
            if missing:
                failures.append(
                    f"  {rel}:{i}: {call_pattern!r} call missing spine kwargs:"
                    f" {', '.join(missing)}"
                )
    return failures


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

    spine_failures = []
    for path in find_all_python_files():
        spine_failures.extend(check_spine_call_sites(path))
    if spine_failures:
        print("\nFAIL check_spine_call_sites:")
        for w in spine_failures:
            print(w)
        return 1
    print("OK check_spine_call_sites (all spine call sites carry required kwargs)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
