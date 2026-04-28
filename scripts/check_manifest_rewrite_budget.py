#!/usr/bin/env python3
"""W17/B19: Manifest rewrite budget gate.

Counts release manifests in docs/releases/ whose `wave` field matches
`current_wave()`. Fails when the count exceeds the budget (default 3).

Why: during W17 we generated 28 manifests in 24 hours because every gate-
script bug fix forced a full regeneration cycle. The budget makes the loop
visible and forces escalation: at the 4th rewrite the captain must either
move stale manifests into archive/ OR document the cause in the recurrence
ledger and supply an override file.

Override file format (`docs/releases/.budget.json`):
    {
        "wave": 17,
        "captain_sha": "ab12cd34...",       (must equal git rev-parse HEAD)
        "ledger_entry_id": "RL-2026-04-29-X",
        "reason": "<one line>",
        "approved_at": "2026-04-29T12:00:00+00:00"
    }

Exit 0: pass (count <= budget OR override present and valid)
Exit 1: fail (count > budget and no valid override)
Exit 2: deferred (no manifests at all)

Status values: pass | fail | not_applicable | deferred
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _governance.manifest_picker import all_manifests
from _governance.wave import current_wave_number, parse_wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELEASES_DIR = ROOT / "docs" / "releases"
BUDGET_FILE = RELEASES_DIR / ".budget.json"
DEFAULT_BUDGET = 3


def _budget_file_display() -> str:
    """Return BUDGET_FILE as a path string relative to ROOT when possible.

    Falls back to absolute path on Windows when paths span different drives
    (which only happens in test fixtures using tmp_path on a different drive
    from the repo).
    """
    try:
        return BUDGET_FILE.relative_to(ROOT).as_posix()
    except ValueError:
        return str(BUDGET_FILE)


def _git_head() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _load_override() -> dict | None:
    if not BUDGET_FILE.exists():
        return None
    try:
        return json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _override_valid(override: dict, current_wave: int) -> tuple[bool, str]:
    """Validate an override file. Returns (is_valid, reason_if_invalid)."""
    required = {"wave", "captain_sha", "ledger_entry_id", "reason", "approved_at"}
    missing = required - set(override.keys())
    if missing:
        return False, f"override missing fields: {sorted(missing)}"
    try:
        ow = parse_wave(override["wave"])
    except ValueError as exc:
        return False, f"override wave unparseable: {exc}"
    if ow != current_wave:
        return False, f"override wave={ow} != current_wave={current_wave}"
    head = _git_head()
    captain_sha = str(override.get("captain_sha", "")).strip()
    if not captain_sha:
        return False, "override captain_sha empty"
    if head and not (head.startswith(captain_sha) or captain_sha.startswith(head[:len(captain_sha)])):
        return False, f"override captain_sha={captain_sha[:12]} != HEAD={head[:12]}"
    if not str(override.get("ledger_entry_id", "")).strip():
        return False, "override ledger_entry_id empty"
    return True, ""


def _count_current_wave_manifests(current_wave: int) -> tuple[int, list[str]]:
    """Count manifests whose `wave` field matches current_wave."""
    matches: list[str] = []
    for m in all_manifests(RELEASES_DIR):
        wave_label = m.get("wave", "")
        try:
            wave_n = parse_wave(wave_label)
        except ValueError:
            continue
        if wave_n == current_wave:
            matches.append(m.get("manifest_id", ""))
    return len(matches), matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manifest rewrite budget gate.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--budget",
        type=int,
        default=DEFAULT_BUDGET,
        help=f"Maximum manifest rewrites per wave (default {DEFAULT_BUDGET}).",
    )
    args = parser.parse_args(argv)

    current_wave = current_wave_number()
    if current_wave == 0:
        result = {
            "check": "manifest_rewrite_budget",
            "status": "deferred",
            "reason": "current_wave is 0 / unknown",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("DEFERRED: unknown current wave", file=sys.stderr)
        return 2

    count, matches = _count_current_wave_manifests(current_wave)
    if count == 0:
        result = {
            "check": "manifest_rewrite_budget",
            "status": "deferred",
            "reason": f"no manifests for current wave ({current_wave})",
            "current_wave": current_wave,
            "budget": args.budget,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: no manifests for Wave {current_wave}", file=sys.stderr)
        return 2

    over_budget = count > args.budget
    override = _load_override() if over_budget else None
    override_valid, override_reason = (False, "")
    if override is not None:
        override_valid, override_reason = _override_valid(override, current_wave)

    if over_budget and not override_valid:
        result = {
            "check": "manifest_rewrite_budget",
            "status": "fail",
            "current_wave": current_wave,
            "budget": args.budget,
            "manifest_count": count,
            "manifest_ids": matches,
            "override_present": override is not None,
            "override_invalid_reason": override_reason if override else "no override file",
            "remediation": (
                f"Move {count - args.budget} stale manifests into "
                f"docs/releases/archive/W{current_wave}/ OR write a valid "
                f"override at {_budget_file_display()}."
            ),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                f"FAIL: {count} manifests for Wave {current_wave} > budget {args.budget}",
                file=sys.stderr,
            )
            print(f"  remediation: {result['remediation']}", file=sys.stderr)
        return 1

    result = {
        "check": "manifest_rewrite_budget",
        "status": "pass",
        "current_wave": current_wave,
        "budget": args.budget,
        "manifest_count": count,
        "manifest_ids": matches,
        "override_used": override_valid,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if override_valid:
            print(
                f"PASS (override): {count} manifests for Wave {current_wave}; "
                f"captain ledger entry {override['ledger_entry_id']}"
            )
        else:
            print(f"PASS: {count}/{args.budget} manifests for Wave {current_wave}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
