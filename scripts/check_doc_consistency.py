#!/usr/bin/env python3
"""CI gate: governance docs must not contradict code reality.

Checks:
1. Delivery notices: no T3 evidence line claiming 'inherited' without a real SHA in docs/delivery/.
2. Capability matrix: L-level claims don't cite xfail/skip tests.
3. Test files: no 'has not (yet )?landed' stale comments (unless noqa: stale-claim).
4. Source files: no '# TODO: wire real run_id' or similar TODO-spine violations.
5. (E1a) Latest delivery notice HEAD SHA must match repo HEAD (unless pre-final-commit marker).
6. (E1b) T3 DEFERRED contradicts readiness improvement above 72.
7. (E1c) Claimed SHA must be reachable in git history.
"""
from __future__ import annotations

import re
import subprocess
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
        # Look for T3 evidence: inherited claims (not descriptive mentions of the concept)
        for line in src.splitlines():
            if re.search(r"T3\s+evidence[^:]*:\s*inherited", line, re.IGNORECASE):
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


def _latest_delivery_notice() -> Path | None:
    """Return the most-recently-modified delivery notice under docs/downstream-responses/."""
    candidates = sorted(
        DOCS.glob("downstream-responses/*delivery-notice*.md"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _git_head() -> str | None:
    """Return the current repo HEAD SHA, or None if git is unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


def check_notice_head_matches_repo(notice: Path | None) -> list[str]:
    """E1a: latest delivery notice HEAD SHA must match repo HEAD.

    Skipped (non-fatal) when:
    - no delivery notice exists yet (bootstrap scenario)
    - the notice contains 'notice-pre-final-commit: true'
    - git is unavailable
    """
    if notice is None:
        return []
    src = notice.read_text(encoding="utf-8", errors="replace")
    # Allow opt-out for pre-final-doc commits
    if "notice-pre-final-commit: true" in src:
        return []
    # Extract claimed HEAD SHA from lines like "**HEAD SHA:** <sha>" or "HEAD: <sha>"
    sha_pattern = re.compile(
        r"(?:HEAD SHA[:\s*]+|HEAD:\s*)([0-9a-f]{7,40})\b", re.IGNORECASE
    )
    claimed_sha: str | None = None
    for line in src.splitlines():
        m = sha_pattern.search(line)
        if m:
            claimed_sha = m.group(1)
            break
    if claimed_sha is None:
        return []  # no HEAD claim in notice — nothing to check
    actual_sha = _git_head()
    if actual_sha is None:
        return []  # git unavailable — skip
    # Compare by common prefix length (handle short vs full SHA)
    min_len = min(len(claimed_sha), len(actual_sha))
    if claimed_sha[:min_len] != actual_sha[:min_len]:
        return [
            f"  {notice.relative_to(ROOT)}: Delivery notice HEAD {claimed_sha} does not "
            f"match repo HEAD {actual_sha}. Update the notice or add "
            "'notice-pre-final-commit: true' if this is a pre-final-doc commit."
        ]
    return []


def check_notice_t3_deferred_vs_readiness(notice: Path | None) -> list[str]:
    """E1b: T3 DEFERRED contradicts readiness improvement above 72."""
    if notice is None:
        return []
    src = notice.read_text(encoding="utf-8", errors="replace")
    has_t3_deferred = bool(re.search(r"T3 evidence[*:]+\s*DEFERRED", src, re.IGNORECASE))
    if not has_t3_deferred:
        return []
    # Look for scorecard/readiness lines mentioning a score above 72
    high_score = re.search(
        r"(?:scorecard delta|readiness)[^\n]*\b(7[3-9]|[89][0-9]|100)\b",
        src,
        re.IGNORECASE,
    )
    if high_score:
        return [
            f"  {notice.relative_to(ROOT)}: Delivery notice claims readiness improvement "
            "above 72 while T3 evidence is DEFERRED. Either complete the T3 gate or "
            "remove/defer the readiness claim."
        ]
    return []


def check_notice_sha_reachable(notice: Path | None) -> list[str]:
    """E1c: claimed SHA must be reachable in git history."""
    if notice is None:
        return []
    src = notice.read_text(encoding="utf-8", errors="replace")
    sha_pattern = re.compile(
        r"(?:HEAD SHA[:\s*]+|HEAD:\s*)([0-9a-f]{7,40})\b", re.IGNORECASE
    )
    claimed_sha: str | None = None
    for line in src.splitlines():
        m = sha_pattern.search(line)
        if m:
            claimed_sha = m.group(1)
            break
    if claimed_sha is None or claimed_sha.upper() == "DEFERRED":
        return []
    try:
        log_output = subprocess.check_output(
            ["git", "log", "--all", "--pretty=%H"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
        ).decode()
    except Exception:
        return []  # git unavailable — skip
    min_len = len(claimed_sha)
    reachable = any(line[:min_len] == claimed_sha[:min_len] for line in log_output.splitlines())
    if not reachable:
        return [
            f"  {notice.relative_to(ROOT)}: Delivery notice HEAD {claimed_sha} is not "
            "reachable in git history."
        ]
    return []


def main() -> int:
    all_errors = []
    all_errors.extend(check_t3_inherited_claims())
    all_errors.extend(check_matrix_xfail_citations())
    all_errors.extend(check_stale_not_landed_comments())
    all_errors.extend(check_todo_spine_violations())
    # E1a, E1b, E1c — delivery notice vs repo HEAD consistency
    latest_notice = _latest_delivery_notice()
    all_errors.extend(check_notice_head_matches_repo(latest_notice))
    all_errors.extend(check_notice_t3_deferred_vs_readiness(latest_notice))
    all_errors.extend(check_notice_sha_reachable(latest_notice))
    if all_errors:
        print("FAIL check_doc_consistency:")
        for e in all_errors:
            print(e)
        return 1
    print("OK check_doc_consistency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
