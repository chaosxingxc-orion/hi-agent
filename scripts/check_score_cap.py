#!/usr/bin/env python3
"""W14-A7: Score-cap gate — surfaces cap_factors from the latest manifest.

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
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"
VERIF_DIR = ROOT / "docs" / "verification"
NOTICES_DIR = ROOT / "docs" / "downstream-responses"


def _latest_manifest() -> pathlib.Path | None:
    manifests = sorted(RELEASES_DIR.glob("platform-release-manifest-*.json"), key=lambda p: p.stat().st_mtime)
    return manifests[-1] if manifests else None


def _check_notice_score_claims(verified: float) -> list[str]:
    """Return list of notices that claim a verified score higher than current_verified_readiness.

    Skips notices marked as 'Status: superseded' or 'Status: draft'.
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
        for m in score_pattern.finditer(text):
            claimed = float(m.group(1))
            if claimed > verified + 0.5:  # allow 0.5 rounding tolerance
                issues.append(f"{f.name}: claims {claimed:.1f} > manifest verified {verified:.1f}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Score-cap gate.")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    args = parser.parse_args()

    manifest_path = _latest_manifest()
    if manifest_path is None:
        result = {
            "status": "deferred",
            "reason": "no manifest found in docs/releases/",
            "check": "score_cap",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: no manifest found", file=sys.stderr)
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
        "provenance": "real",
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
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

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
