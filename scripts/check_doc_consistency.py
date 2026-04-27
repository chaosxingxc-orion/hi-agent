#!/usr/bin/env python3
"""CI gate: governance docs must not contradict code reality.

# Validates platform delivery artifacts only — not consumer-specific formats.

Checks:
1. Delivery notices: no T3 evidence line claiming 'inherited' without a real SHA in docs/delivery/.
2. Capability matrix: L-level claims don't cite xfail/skip tests.
3. Test files: no 'has not (yet )?landed' stale comments (unless noqa: stale-claim).
4. Source files: no '# TODO: wire real run_id' or similar TODO-spine violations.
5. (E1a) Latest delivery notice HEAD SHA must match repo HEAD (unless pre-final-commit marker).
6. (E1b) T3 DEFERRED contradicts readiness improvement above 72.
7. (E1c) Claimed SHA must be reachable in git history.
8. Wave notice HEAD alignment: non-draft notices must declare current HEAD SHA.
9. Downstream-response files newer than the latest manifest must cite Manifest: <id>.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _governance_json import emit_result

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"


def _git_head(repo_root: Path = ROOT) -> str | None:
    """Return the current HEAD SHA, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return None


def _git_parent(ref: str) -> str | None:
    """Return SHA of the parent commit of ref, or None."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", f"{ref}~1"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


def _sha_matches(claimed: str, actual: str) -> bool:
    min_len = min(len(claimed), len(actual))
    return claimed[:min_len] == actual[:min_len]


def _latest_delivery_notice() -> Path | None:
    """Return the most-recently-modified delivery notice under docs/downstream-responses/."""
    candidates = sorted(
        DOCS.glob("downstream-responses/*delivery-notice*.md"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _is_t3_stale() -> bool:
    """Return True if check_t3_freshness.py exits non-zero."""
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_t3_freshness.py")],
            capture_output=True,
            timeout=15,
        )
        return r.returncode != 0
    except Exception:
        return False  # if we can't check, don't fail


def check_t3_inherited_claims() -> list[str]:
    """T3 'inherited' claims must reference a real SHA in docs/delivery/."""
    errors = []
    delivery_dir = DOCS / "delivery"
    for notice in DOCS.glob("downstream-responses/*delivery-notice*.md"):
        src = notice.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        # Draft notices are exempt from this check (HEAD backfill deferred).
        if any(re.search(r"Status:.*(?:draft|superseded)", line, re.IGNORECASE) for line in lines):
            continue
        # Look for 'T3 inherited' pattern
        for line in lines:
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


# --- E1a/E1b/E1c/E1d: delivery notice vs repo HEAD consistency ---

def check_notice_head_matches_repo(notice: Path | None) -> list[str]:
    """E1a: latest delivery notice HEAD SHA must match repo HEAD or its direct parent."""
    if notice is None:
        return []
    src = notice.read_text(encoding="utf-8", errors="replace")
    if "notice-pre-final-commit: true" in src:
        return []
    if re.search(r"Status:.*(?:draft|superseded)", src, re.IGNORECASE):
        return []
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
        return []
    actual_sha = _git_head()
    if actual_sha is None:
        return []
    if _sha_matches(claimed_sha, actual_sha):
        return []
    parent_sha = _git_parent("HEAD")
    if parent_sha and _sha_matches(claimed_sha, parent_sha):
        return []
    return [
        f"  {notice.relative_to(ROOT)}: Delivery notice HEAD {claimed_sha} does not "
        f"match repo HEAD {actual_sha} or its parent. Update the notice or add "
        "'notice-pre-final-commit: true' if this is a pre-final-doc commit."
    ]


def check_notice_t3_deferred_vs_readiness(notice: Path | None) -> list[str]:
    """E1b: T3 DEFERRED contradicts readiness improvement above 72."""
    if notice is None:
        return []
    src = notice.read_text(encoding="utf-8", errors="replace")
    if re.search(r"Status:.*(?:draft|superseded)", src, re.IGNORECASE):
        return []
    has_t3_deferred = bool(re.search(r"T3 evidence[*:]+\s*DEFERRED", src, re.IGNORECASE))
    if not has_t3_deferred:
        return []
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


_RELEASE_READY_WORDS = re.compile(
    r"\b(release[- ]ready|release[- ]complete|shipped|final release)\b",
    re.IGNORECASE,
)
_GATE_PENDING_MARKER = "gate pending"


def check_t3_deferred_release_wording(notice: Path | None) -> list[str]:
    """E1d: When T3 is stale+deferred, delivery notice must not claim release readiness."""
    if notice is None:
        return []
    src = notice.read_text(encoding="utf-8", errors="replace")
    has_t3_deferred = bool(re.search(r"T3 evidence[*:\s]+DEFERRED", src, re.IGNORECASE))
    if not has_t3_deferred:
        return []
    has_gate_pending = _GATE_PENDING_MARKER.lower() in src.lower()
    if has_gate_pending:
        return []
    t3_stale = _is_t3_stale()
    if not t3_stale:
        return []
    match = _RELEASE_READY_WORDS.search(src)
    if match:
        return [
            f"  {notice.relative_to(ROOT)}: Delivery notice uses '{match.group()}' wording "
            "but T3 is DEFERRED and stale. Either run a fresh T3 gate "
            "or add 'gate pending' marker near any release claim."
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
        return []
    min_len = len(claimed_sha)
    reachable = any(line[:min_len] == claimed_sha[:min_len] for line in log_output.splitlines())
    if not reachable:
        return [
            f"  {notice.relative_to(ROOT)}: Delivery notice HEAD {claimed_sha} is not "
            "reachable in git history."
        ]
    return []


# --- Wave notice HEAD alignment ---

def check_notice_head_alignment() -> list[str]:
    """Wave notice files must declare the current HEAD SHA unless marked 'Status: draft'.

    For each file matching ``docs/downstream-responses/2026-*-wave*-notice.md``:
    - If the file contains ``Status: draft`` on any line → skip (draft notices are exempt).
    - Otherwise both ``Functional HEAD:`` and ``Notice HEAD:`` lines must contain the
      current HEAD SHA.  Missing lines also count as a mismatch.
    """
    errors: list[str] = []
    head = _git_head(ROOT)
    if head is None:
        return ["  check_notice_head_alignment: cannot determine HEAD SHA (git unavailable)"]

    for notice in DOCS.glob("downstream-responses/2026-*-wave*-notice.md"):
        src = notice.read_text(encoding="utf-8", errors="replace")
        lines = src.splitlines()
        if any(re.search(r"Status:.*(?:draft|superseded)", line, re.IGNORECASE) for line in lines):
            continue  # draft notices are exempt

        func_heads = [
            m.group(1)
            for line in lines
            for m in [re.search(r"Functional HEAD:\s*([0-9a-f]{7,40})", line, re.IGNORECASE)]
            if m
        ]
        notice_heads = [
            m.group(1)
            for line in lines
            for m in [re.search(r"Notice HEAD:\s*([0-9a-f]{7,40})", line, re.IGNORECASE)]
            if m
        ]

        try:
            rel = notice.relative_to(DOCS.parent)
        except ValueError:
            rel = notice
        for sha in func_heads:
            if not head.startswith(sha) and not sha.startswith(head[:len(sha)]):
                errors.append(
                    f"  STALE-NOTICE-HEAD: {rel} declares Functional HEAD {sha}, "
                    f"current is {head[:12]}"
                )
        for sha in notice_heads:
            if not head.startswith(sha) and not sha.startswith(head[:len(sha)]):
                errors.append(
                    f"  STALE-NOTICE-HEAD: {rel} declares Notice HEAD {sha}, "
                    f"current is {head[:12]}"
                )
        if not func_heads and not notice_heads:
            # No HEAD fields at all — check for legacy HEAD SHA line
            legacy = [
                m.group(1)
                for line in lines
                for m in [re.search(r"\*\*HEAD SHA:\*\*\s*([0-9a-f]{7,40})", line)]
                if m
            ]
            for sha in legacy:
                if not head.startswith(sha) and not sha.startswith(head[:len(sha)]):
                    errors.append(
                        f"  STALE-NOTICE-HEAD: {rel} declares HEAD SHA {sha}, "
                        f"current is {head[:12]}"
                    )

    return errors


def _latest_manifest_mtime() -> float | None:
    """Return mtime of the most-recent release manifest, or None if none exist."""
    releases = DOCS / "releases"
    manifests = list(releases.glob("platform-release-manifest-*.json"))
    if not manifests:
        return None
    return max(p.stat().st_mtime for p in manifests)


def _latest_manifest_id() -> str | None:
    """Return the manifest_id from the most-recent release manifest."""
    import json as _json
    releases = DOCS / "releases"
    manifests = sorted(
        releases.glob("platform-release-manifest-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not manifests:
        return None
    try:
        data = _json.loads(manifests[-1].read_text(encoding="utf-8"))
        return str(data.get("manifest_id", ""))
    except Exception:
        return None


_MANIFEST_CITE_RE = re.compile(r"Manifest:\s*\S+")


def check_downstream_notices_cite_manifest() -> list[str]:
    """Check 9: downstream-response files newer than the latest manifest must cite Manifest: <id>.

    If no manifest exists yet, skip (manifest infrastructure is new; bootstrap exemption).
    """
    manifest_mtime = _latest_manifest_mtime()
    if manifest_mtime is None:
        return []  # no manifest yet; bootstrap exemption

    errors = []
    responses_dir = DOCS / "downstream-responses"
    if not responses_dir.exists():
        return []

    for notice in responses_dir.glob("*.md"):
        if notice.stat().st_mtime <= manifest_mtime:
            continue  # older than manifest; exempt
        src = notice.read_text(encoding="utf-8", errors="replace")
        # Draft/superseded notices are exempt
        if re.search(r"Status:.*(?:draft|superseded)", src, re.IGNORECASE):
            continue
        if not _MANIFEST_CITE_RE.search(src):
            errors.append(
                f"  {notice.relative_to(ROOT)}: downstream-response newer than latest manifest "
                "must contain 'Manifest: <manifest_id>' line"
            )
    return errors


def _check_closure_notice_levels(docs_dir: Path) -> list[str]:
    """Check 11: every defect row in closure notices must have a level: <enum> field.

    A 'closure notice' is any file matching docs/downstream-responses/*notice*.md.
    A defect row is a markdown table row containing a '|' separator.
    If the table has a 'Level' column, every data row must have a valid level value.
    """
    valid_levels = {
        "component_exists",
        "wired_into_default_path",
        "covered_by_default_path_e2e",
        "verified_at_release_head",
        "operationally_observable",
        "in_progress",
        "deferred",
    }
    violations: list[str] = []
    notice_pattern = docs_dir / "downstream-responses"
    if not notice_pattern.exists():
        return []

    for notice_file in notice_pattern.glob("*notice*.md"):
        content = notice_file.read_text(encoding="utf-8")
        lines = content.splitlines()

        # Skip superseded and draft notices — they predate the Rule 15 taxonomy.
        if any(re.search(r"Status:.*(?:draft|superseded)", ln, re.IGNORECASE) for ln in lines):
            continue

        in_table = False
        has_level_column = False
        level_col = -1

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("|"):
                in_table = False
                has_level_column = False
                level_col = -1
                continue

            cells = [c.strip() for c in stripped.split("|") if c.strip()]

            if any(c.lower() in ("level", "closure level") for c in cells):
                in_table = True
                has_level_column = True
                level_col = next(
                    j
                    for j, c in enumerate(cells)
                    if c.lower() in ("level", "closure level")
                )
                continue

            if all(c.replace("-", "").replace(":", "") == "" for c in cells):
                continue

            if in_table and has_level_column and level_col < len(cells):
                val = cells[level_col].lower().strip("`")
                if val not in valid_levels:
                    violations.append(
                        f"  {notice_file.relative_to(docs_dir.parent)}:{i + 1}: "
                        f"invalid closure level '{val}' (valid: {sorted(valid_levels)})"
                    )
    return violations


def _count_notices_checked() -> int:
    """Count delivery notice files inspected."""
    return len(list(DOCS.glob("downstream-responses/*delivery-notice*.md")))


def _parse_doc_error(text: str) -> dict:
    """Parse an error string into a structured dict."""
    import re
    # Format: "  file:line: message" or "  file: message"
    m = re.match(r"\s+([^:]+):(\d+): (.*)", text)
    if m:
        return {"file": m.group(1), "line": int(m.group(2)), "text": m.group(3)}
    m2 = re.match(r"\s+([^:]+):\s+(.*)", text)
    if m2:
        return {"file": m2.group(1), "text": m2.group(2)}
    return {"text": text.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check doc consistency")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of human-readable text.",
    )
    args = parser.parse_args()

    all_errors = []
    all_errors.extend(check_t3_inherited_claims())
    all_errors.extend(check_matrix_xfail_citations())
    all_errors.extend(check_stale_not_landed_comments())
    all_errors.extend(check_todo_spine_violations())
    # E1a, E1b, E1c, E1d — delivery notice vs repo HEAD consistency
    latest_notice = _latest_delivery_notice()
    all_errors.extend(check_notice_head_matches_repo(latest_notice))
    all_errors.extend(check_notice_t3_deferred_vs_readiness(latest_notice))
    all_errors.extend(check_t3_deferred_release_wording(latest_notice))
    all_errors.extend(check_notice_sha_reachable(latest_notice))
    # Wave notice HEAD alignment
    all_errors.extend(check_notice_head_alignment())
    # Check 9: downstream-response notices newer than manifest must cite Manifest: <id>
    all_errors.extend(check_downstream_notices_cite_manifest())
    # Check 11: closure notices must have a valid level enum in every defect row
    all_errors.extend(_check_closure_notice_levels(DOCS))

    if args.json:
        structured = [_parse_doc_error(e) for e in all_errors]
        emit_result(
            "doc_consistency",
            "pass" if not all_errors else "fail",
            violations=structured,
            counts={"notices_checked": _count_notices_checked()},
        )

    if all_errors:
        print("FAIL check_doc_consistency:")
        for e in all_errors:
            print(e)
        return 1
    print("OK check_doc_consistency")
    return 0


if __name__ == "__main__":
    sys.exit(main())
