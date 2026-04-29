#!/usr/bin/env python3
"""C10: Doc-freshness + response-sibling gate.

Checks:
  1. docs/platform-capability-matrix.md "Last updated: ... Wave N" is within
     2 waves of docs/governance/recurrence-ledger.yaml `current_wave`.
  2. docs/platform-gaps.md "Last updated: ... Wave N" is within 2 waves of
     `current_wave`.
  3. Every *-delivery-notice.md in docs/downstream-responses/ that is older
     than 7 days has a sibling *-response.md with the same date prefix.

Exit 0: all checks pass (prints "OK check_doc_truth")
Exit 1: one or more checks fail (prints "FAIL check_doc_truth: <reason>")
Exit 2: deferred (ledger or docs not found — non-blocking in clean environments)
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "docs" / "governance" / "recurrence-ledger.yaml"
MATRIX_PATH = ROOT / "docs" / "platform-capability-matrix.md"
GAPS_PATH = ROOT / "docs" / "platform-gaps.md"
RESPONSES_DIR = ROOT / "docs" / "downstream-responses"

_MAX_WAVE_LAG = 2
_NOTICE_STALENESS_DAYS = 7


def _load_current_wave() -> int | None:
    """Return current_wave from recurrence-ledger.yaml, or None if unavailable."""
    if not LEDGER_PATH.exists():
        return None
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(LEDGER_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            val = data.get("current_wave")
            if isinstance(val, int):
                return val
    except Exception:
        pass
    # Fallback: regex parse for `current_wave: N`
    text = LEDGER_PATH.read_text(encoding="utf-8")
    m = re.search(r"^current_wave:\s*(\d+)", text, re.MULTILINE)
    if m:
        return int(m.group(1))
    return None


def _extract_wave_from_doc(path: pathlib.Path) -> int | None:
    """Extract Wave N from 'Last updated: ... (Wave N ...)' in a doc file."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Last updated.*Wave\s+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _check_doc_freshness(
    current_wave: int, issues: list[str]
) -> None:
    """Check platform-capability-matrix.md and platform-gaps.md wave lag."""
    for label, path in [
        ("platform-capability-matrix.md", MATRIX_PATH),
        ("platform-gaps.md", GAPS_PATH),
    ]:
        if not path.exists():
            issues.append(f"{label}: file not found at {path}")
            continue
        wave = _extract_wave_from_doc(path)
        if wave is None:
            issues.append(
                f"{label}: could not extract 'Last updated: ... Wave N' line"
            )
            continue
        lag = current_wave - wave
        if lag > _MAX_WAVE_LAG:
            issues.append(
                f"{label}: last-updated wave {wave} is {lag} waves behind"
                f" current_wave {current_wave} (max allowed lag: {_MAX_WAVE_LAG})"
            )


def _check_response_siblings(issues: list[str]) -> None:
    """Check every stale delivery notice has a sibling response doc."""
    if not RESPONSES_DIR.exists():
        issues.append(f"downstream-responses/ directory not found at {RESPONSES_DIR}")
        return

    cutoff = datetime.date.today() - datetime.timedelta(days=_NOTICE_STALENESS_DAYS)
    notices = sorted(RESPONSES_DIR.glob("*-delivery-notice.md"))

    for notice in notices:
        # Extract date prefix: first 10 chars should be YYYY-MM-DD
        stem = notice.stem  # e.g. "2026-04-28-wave17-delivery-notice"
        date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", stem)
        if not date_match:
            continue
        try:
            notice_date = datetime.date.fromisoformat(date_match.group(1))
        except ValueError:
            continue

        if notice_date > cutoff:
            # Notice is recent — no response required yet
            continue

        # Look for any sibling *-response.md with same date prefix
        date_prefix = date_match.group(1)
        siblings = list(RESPONSES_DIR.glob(f"{date_prefix}*-response.md"))
        if not siblings:
            issues.append(
                f"{notice.name}: delivery notice older than {_NOTICE_STALENESS_DAYS}"
                f" days ({notice_date}) has no sibling *-response.md"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Doc freshness + response sibling gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    current_wave = _load_current_wave()
    if current_wave is None:
        result = {
            "check": "check_doc_truth",
            "status": "deferred",
            "reason": "could not determine current_wave from recurrence-ledger.yaml",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                "DEFERRED check_doc_truth: could not determine current_wave",
                file=sys.stderr,
            )
        return 2

    issues: list[str] = []
    _check_doc_freshness(current_wave, issues)
    _check_response_siblings(issues)

    status = "pass" if not issues else "fail"
    result = {
        "check": "check_doc_truth",
        "status": status,
        "current_wave": current_wave,
        "issues_total": len(issues),
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if issues:
            for issue in issues:
                print(f"FAIL check_doc_truth: {issue}", file=sys.stderr)
        else:
            print(f"OK check_doc_truth (wave={current_wave}, 0 issues)")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
