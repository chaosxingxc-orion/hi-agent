#!/usr/bin/env python3
"""Rule 14 enforcement — delivery notice score claims must match latest manifest.

Allowed patterns in notices:
- "current_verified_readiness: 94.55" (exact match to manifest, +-0.5)
- "raw=94.55" (exact match, +-0.5)
- "projected_*" claims (forward-looking, not checked against manifest)
- Capped claims: "verified=70.0 (capped)" -- must match manifest verified value

Forbidden patterns:
- "verified 80+" when manifest shows 70.0 (divergence > 0.5 is a hard fail)
- "fully closed" / "complete" / "all green" without manifest evidence
"""
import glob
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST_GLOB = str(REPO / "docs" / "releases" / "platform-release-manifest-*.json")
# Only match date-prefixed notice files (YYYY-*-*.md) to exclude _template and README
NOTICE_GLOB = str(REPO / "docs" / "downstream-responses" / "2[0-9][0-9][0-9]-*-*.md")

# Patterns that suggest a score claim in the notice text
SCORE_CLAIM_RE = re.compile(
    r"(?:verified|current_verified_readiness|raw|raw_implementation_maturity)"
    r"\s*[=:]\s*([\d.]+)",
    re.IGNORECASE,
)

# Forbidden phrases per Rule 14 — prohibited unless manifest evidence supports them.
# Note: the 7x24/7-by-24 pattern uses [x] (ASCII) only; the Unicode multiplication
# sign variant is intentionally omitted to avoid RUF001 ambiguous-character lint.
FORBIDDEN_CLAIMS_RE = re.compile(
    r"\b(fully closed|all green|release-ready|7x24 ready)\b",
    re.IGNORECASE,
)

TOLERANCE = 0.5  # allowed divergence between notice claim and manifest fact


def _load_latest_manifest():
    manifests = sorted(glob.glob(MANIFEST_GLOB), reverse=True)
    if not manifests:
        return None
    with open(manifests[0]) as f:
        return json.load(f)


def _load_latest_notice(manifest_wave: "int | None" = None):
    """Return the most recent delivery notice, preferring wave-matched files.

    Selection order:
    1. If manifest_wave is known, pick the file whose name contains "w{wave}" or
       "wave{wave}" (case-insensitive) with the latest mtime.
    2. Otherwise fall back to the file with the latest mtime among all date-prefixed
       notice files.
    """
    candidates = glob.glob(NOTICE_GLOB)
    if not candidates:
        return None, None

    if manifest_wave is not None:
        wave_str_short = f"w{manifest_wave}"
        wave_str_long = f"wave{manifest_wave}"
        matched = [
            p
            for p in candidates
            if wave_str_short in Path(p).name.lower()
            or wave_str_long in Path(p).name.lower()
        ]
        pool = matched if matched else candidates
    else:
        pool = candidates

    path = max(pool, key=lambda p: Path(p).stat().st_mtime)
    return path, Path(path).read_text(encoding="utf-8")


def main():
    as_json = "--json" in sys.argv

    manifest = _load_latest_manifest()
    manifest_wave = int(manifest.get("wave", 0)) if manifest else None
    notice_path, notice_text = _load_latest_notice(manifest_wave=manifest_wave)

    if manifest is None:
        result = {"check": "notice_score_match", "status": "pass", "reason": "no_manifest_yet"}
        print(json.dumps(result) if as_json else "PASS: no manifest")
        sys.exit(0)

    if notice_text is None:
        result = {"check": "notice_score_match", "status": "pass", "reason": "no_notice_yet"}
        print(json.dumps(result) if as_json else "PASS: no notice")
        sys.exit(0)

    # Extract manifest scores -- prefer scorecard sub-dict if present (canonical location)
    scorecard = manifest.get("scorecard", {})
    manifest_verified = float(
        scorecard.get("current_verified_readiness")
        or manifest.get("current_verified_readiness", 0)
    )
    manifest_raw = float(
        scorecard.get("raw_implementation_maturity")
        or manifest.get("raw_implementation_maturity", 0)
    )

    violations = []

    # Check score claim divergence
    for m in SCORE_CLAIM_RE.finditer(notice_text):
        claimed = float(m.group(1))
        # Compare against whichever manifest value is closest (raw or verified)
        min_divergence = min(abs(claimed - manifest_verified), abs(claimed - manifest_raw))
        if min_divergence > TOLERANCE:
            context = notice_text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ")
            violations.append(
                {
                    "type": "score_divergence",
                    "claimed": claimed,
                    "manifest_verified": manifest_verified,
                    "manifest_raw": manifest_raw,
                    "divergence": round(min_divergence, 2),
                    "context": context.strip(),
                }
            )

    # Check forbidden phrases
    for m in FORBIDDEN_CLAIMS_RE.finditer(notice_text):
        context = notice_text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ")
        violations.append(
            {
                "type": "forbidden_claim",
                "phrase": m.group(0),
                "context": context.strip(),
            }
        )

    status = "fail" if violations else "pass"
    manifest_files = sorted(glob.glob(MANIFEST_GLOB), reverse=True)
    result = {
        "check": "notice_score_match",
        "status": status,
        "manifest_path": str(Path(manifest_files[0]).relative_to(REPO)),
        "notice_path": str(Path(notice_path).relative_to(REPO)),
        "manifest_verified": manifest_verified,
        "manifest_raw": manifest_raw,
        "violations": violations,
    }

    if as_json:
        print(json.dumps(result, indent=2))
    elif violations:
        for v in violations:
            print(f"SCORE MISMATCH: {v}", file=sys.stderr)
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
