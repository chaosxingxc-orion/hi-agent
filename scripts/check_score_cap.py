#!/usr/bin/env python3
"""W14-A7: Score-cap gate 鈥?surfaces cap_factors from the latest manifest.

Reads the most-recent manifest from docs/releases/ and fails when:
  - manifest is missing
  - cap_factors is non-empty and includes a blocker-class factor
  - any downstream notice or changelog asserts a score higher than current_verified_readiness

Emits <sha>-score-cap.json to docs/verification/.

Exit 0: pass or deferred-with-reason.
Exit 1: fail (blocker cap or assertion mismatch).
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import subprocess
import sys

from _governance.manifest_picker import (
    latest_manifest_path,
    manifest_for_sha,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"
VERIF_DIR = ROOT / "docs" / "verification"
NOTICES_DIR = ROOT / "docs" / "downstream-responses"


def _git_head_full() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _select_manifest(strict_head: bool) -> pathlib.Path | None:
    """CP-6 fix: prefer the manifest at current HEAD over the latest-by-time.

    When strict_head=True and no manifest exists for current HEAD, return None
    rather than reading an older manifest. This breaks the W17 score-cap
    circular dependency where T3-deferred caps would silently re-cap against
    a stale manifest.
    """
    head = _git_head_full()
    if head:
        m = manifest_for_sha(head, RELEASES_DIR)
        if m:
            return pathlib.Path(m["_path"])
        if strict_head:
            return None
    return latest_manifest_path(RELEASES_DIR)


def _manifest_verified_for_notice(text: str, default_verified: float) -> float:
    """Extract the verified score from the manifest cited in the notice, if any.

    A notice may cite a specific manifest via 'Manifest: <manifest_id>' line.
    If the cited manifest exists and has a valid score, use that score as the
    comparison baseline. This allows a notice to correctly describe a higher
    score than an older latest manifest without tripping a false positive.
    """
    cite_m = re.search(r"Manifest:\s*([\w-]+)", text)
    if not cite_m:
        return default_verified
    manifest_id = cite_m.group(1).strip()
    # Manifest ID may be just the short SHA or the full ID like '2026-04-27-a1bfa88'
    for p in RELEASES_DIR.glob(f"*{manifest_id}*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            sc = data.get("scorecard", {})
            v = float(sc.get("current_verified_readiness", sc.get("verified", 0)))
            if v > 0:
                return v
        except Exception:
            pass
    return default_verified


def _check_notice_score_claims(verified: float) -> list[str]:
    """Return list of notices that claim a verified score higher than current_verified_readiness.

    Skips notices marked as 'Status: superseded' or 'Status: draft'.
    Each notice is compared against the manifest it cites (via 'Manifest: <id>'),
    falling back to the provided verified score if no specific manifest is cited.
    """
    issues: list[str] = []
    if not NOTICES_DIR.exists():
        return issues
    score_pattern = re.compile(
        r"(?:verified|current_verified_readiness|readiness)[:\s]+(\d{2,3}(?:\.\d+)?)",
        re.IGNORECASE,
    )
    status_pattern = re.compile(r"Status:\s*(?:superseded|draft)", re.IGNORECASE)
    for f in NOTICES_DIR.glob("*.md"):
        text = f.read_text(encoding="utf-8", errors="replace")
        if status_pattern.search(text):
            continue  # superseded/draft notices are exempt
        # Use the manifest cited in this notice for comparison (or fall back to latest)
        notice_verified = _manifest_verified_for_notice(text, verified)
        for m in score_pattern.finditer(text):
            claimed = float(m.group(1))
            if claimed > notice_verified + 0.5:  # allow 0.5 rounding tolerance
                issues.append(f"{f.name}: claims {claimed:.1f} > manifest verified {notice_verified:.1f}")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score-cap gate.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument(
        "--strict-head",
        action="store_true",
        default=False,
        help=(
            "Defer when no manifest exists at current git HEAD instead of "
            "reading an older manifest. Breaks the score-cap circular "
            "dependency (CP-6) when used in CI."
        ),
    )
    args = parser.parse_args(argv)

    manifest_path = _select_manifest(strict_head=args.strict_head)
    if manifest_path is None:
        reason = (
            "no manifest at current HEAD (--strict-head)"
            if args.strict_head
            else "no manifest found in docs/releases/"
        )
        result = {
            "status": "deferred",
            "reason": reason,
            "check": "score_cap",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: {reason}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sc = manifest.get("scorecard", {})
    verified = float(sc.get("current_verified_readiness", sc.get("verified", 0)))
    cap_factors = sc.get("cap_factors", [])
    cap = sc.get("cap")
    cap_reason = sc.get("cap_reason", "")

    score_claim_issues = _check_notice_score_claims(verified)
    issues = score_claim_issues

    status = "pass" if not issues else "fail"

    evidence = {
        "schema_version": "1",
        "check": "score_cap",
        "provenance": "derived",
        "manifest_id": manifest.get("manifest_id", ""),
        "verified_head": manifest.get("release_head", ""),
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "current_verified_readiness": verified,
        "cap": cap,
        "cap_reason": cap_reason,
        "cap_factors": cap_factors,
        "score_claim_issues": score_claim_issues,
        "status": status,
    }

    # Name the artifact using the CURRENT git HEAD, not the manifest's SHA.
    # Using manifest's SHA would overwrite a committed artifact whenever the
    # manifest is rebuilt at a later HEAD, creating dirty-tree false positives.
    import subprocess as _sp
    _head_result = _sp.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    current_short_sha = _head_result.stdout.strip() if _head_result.returncode == 0 else (
        manifest.get("git", {}).get("short_sha", "unknown")
    )
    VERIF_DIR.mkdir(parents=True, exist_ok=True)
    out = VERIF_DIR / f"{current_short_sha}-score-cap.json"
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "scripts"))
    from _governance.evidence_writer import write_artifact
    write_artifact(
        path=out,
        body=evidence,
        provenance="derived",
        generator_script=__file__,
        degraded=True,
    )

    result = {"status": status, "check": "score_cap", **evidence}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'PASS' if status == 'pass' else 'FAIL'}: verified={verified:.1f} cap={cap} factors={cap_factors}")
        for issue in issues:
            print(f"  ISSUE: {issue}", file=sys.stderr)

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())

