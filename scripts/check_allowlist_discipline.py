#!/usr/bin/env python3
"""CI gate: validate docs/governance/allowlists.yaml entry discipline.

Checks:
- Every entry has all required fields:
  allowlist, entry, owner, risk, reason, expiry_wave, replacement_test, added_at
- No expired entries (expiry_wave < current_wave)
- risk values are in {low, medium, high}

Exit 0: all entries valid
Exit 1: validation failures

Flags:
  --json  Emit structured JSON report.
"""
# Status values: pass | fail | not_applicable | deferred
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLISTS_FILE = ROOT / "docs" / "governance" / "allowlists.yaml"


def _current_wave_number() -> int:
    """Load current wave from _current_wave.py (single source of truth)."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from _current_wave import wave_number, current_wave as _cw
        return wave_number(_cw())
    except Exception:
        return 0

REQUIRED_FIELDS = {
    "allowlist",
    "entry",
    "owner",
    "risk",
    "reason",
    "expiry_wave",
    "replacement_test",
    "added_at",
}
VALID_RISKS = {"low", "medium", "high"}


def _load_yaml_simple(path: Path) -> dict:
    """Minimal YAML loader for our schema (no external dependencies)."""
    text = path.read_text(encoding="utf-8")
    data: dict = {"entries": [], "current_wave": 0}

    # Extract current_wave
    m = re.search(r"^current_wave:\s*(\d+)", text, re.MULTILINE)
    if m:
        data["current_wave"] = int(m.group(1))

    # Extract entries as YAML blocks
    entry_blocks: list[dict] = []
    current: dict = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- allowlist:"):
            if current:
                entry_blocks.append(current)
            current = {"allowlist": stripped.split(":", 1)[1].strip()}
        elif current and ":" in stripped and not stripped.startswith("#"):
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k in ("expiry_wave",):
                try:
                    current[k] = int(v)
                except ValueError:
                    current[k] = v
            else:
                current[k] = v
    if current:
        entry_blocks.append(current)

    data["entries"] = entry_blocks
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check allowlist discipline.")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    if not ALLOWLISTS_FILE.exists():
        msg = f"allowlists.yaml not found at {ALLOWLISTS_FILE}"
        if args.json_output:
            print(json.dumps({"check": "allowlist_discipline", "status": "fail", "error": msg}))
        else:
            print(f"FAIL allowlist_discipline: {msg}")
        return 1

    try:
        data = _load_yaml_simple(ALLOWLISTS_FILE)
    except Exception as e:
        msg = f"Failed to parse allowlists.yaml: {e}"
        if args.json_output:
            print(json.dumps({"check": "allowlist_discipline", "status": "fail", "error": msg}))
        else:
            print(f"FAIL allowlist_discipline: {msg}")
        return 1

    current_wave = _current_wave_number() or data.get("current_wave", 0)
    entries = data.get("entries", [])

    missing_fields: list[dict] = []
    invalid_risk: list[dict] = []
    expired: list[dict] = []

    for i, entry in enumerate(entries):
        label = f"entry[{i}] {entry.get('entry', '?')}"
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            missing_fields.append({"label": label, "missing": sorted(missing)})
        if entry.get("risk") not in VALID_RISKS:
            invalid_risk.append({"label": label, "risk": entry.get("risk")})
        expiry = entry.get("expiry_wave")
        if isinstance(expiry, int) and current_wave > 0 and expiry < current_wave:
            expired.append(
                {"label": label, "expiry_wave": expiry, "current_wave": current_wave}
            )

    total = len(entries)
    expired_total = len(expired)
    failures = missing_fields + invalid_risk + expired

    if args.json_output:
        status = "fail" if failures else "pass"
        print(
            json.dumps(
                {
                    "check": "allowlist_discipline",
                    "status": status,
                    "total": total,
                    "expired_total": expired_total,
                    "missing_fields_total": len(missing_fields),
                    "invalid_risk_total": len(invalid_risk),
                    "failures": failures,
                },
                indent=2,
            )
        )
        return 1 if failures else 0

    if missing_fields:
        print("FAIL allowlist_discipline (missing required fields):")
        for f in missing_fields:
            print(f"  {f['label']}: missing {f['missing']}")
    if invalid_risk:
        print("FAIL allowlist_discipline (invalid risk value):")
        for f in invalid_risk:
            print(f"  {f['label']}: risk='{f['risk']}' not in {{low,medium,high}}")
    if expired:
        print("FAIL allowlist_discipline (expired entries -- fail closed):")
        for f in expired:
            print(
                f"  {f['label']}: expired at Wave {f['expiry_wave']} (current={f['current_wave']})"
            )

    if not failures:
        print(f"OK allowlist_discipline ({total} entries, {expired_total} expiring-soon)")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

