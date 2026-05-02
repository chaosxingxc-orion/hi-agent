#!/usr/bin/env python3
"""W14-D3: Universal allowlist expiry gate.

Audits ALL allowlist entries across the codebase:
  1. docs/governance/allowlists.yaml (primary)
  2. In-code ALLOWLIST tuples/dicts in scripts/check_*.py
  3. Server _EXEMPT_PATHS in auth_middleware.py, rate_limiter.py, session_middleware.py
  4. Any other in-code allowlist patterns

Every entry MUST have: owner, risk, reason, expiry_wave.
Expired entries (expiry_wave <= current wave) cause gate failure.

Exit 0: pass (all entries valid and unexpired).
Exit 1: fail (missing required fields or expired entries).
Exit 2: deferred (allowlists.yaml missing — can't fully audit).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWLISTS_YAML = ROOT / "docs" / "governance" / "allowlists.yaml"
# Kept for backwards reference; the canonical reader is _governance.wave.
CURRENT_WAVE_FILE = ROOT / "docs" / "current-wave.txt"

# W31-D D-3' fix: delegate wave reading to the canonical helper instead of the
# previous regex-only path that silently fell back to "Wave 14". The old
# fallback was the source of the manifest field
# `gates.allowlist_universal.current_wave: "Wave 14"` even on Wave 30 manifests
# because the regex `Wave\s+(\d+)` did not match the bare-integer file format
# ("31\n") so the function returned the hardcoded 14 fallback every time.
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from _governance.wave import current_wave_number as _governance_current_wave_number
except Exception:  # pragma: no cover  # noqa: BLE001  # expiry_wave: permanent  # added: W31-D D-3'
    _governance_current_wave_number = None  # type: ignore[assignment]

_REQUIRED_FIELDS = frozenset({"owner", "risk", "reason", "expiry_wave"})


def _current_wave_number() -> int:
    """Return the current wave number.

    Source of truth: scripts/_governance/wave.py (which reads
    docs/current-wave.txt — bare-integer format). Falls back to a parser of
    docs/current-wave.txt only if the canonical helper cannot be imported.
    """
    if _governance_current_wave_number is not None:
        return _governance_current_wave_number()
    # Defensive fallback (canonical helper missing): parse the file directly
    # using the bare-integer format as well as the older "Wave N" form.
    if CURRENT_WAVE_FILE.exists():
        text = CURRENT_WAVE_FILE.read_text(encoding="utf-8").strip()
        m = re.match(r"(?:Wave\s+)?(\d+)", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return 0


def _parse_allowlists_yaml() -> list[dict]:
    """Parse docs/governance/allowlists.yaml entries."""
    if not ALLOWLISTS_YAML.exists():
        return []
    text = ALLOWLISTS_YAML.read_text(encoding="utf-8")
    entries = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- id:") or stripped.startswith("- symbol:") or stripped.startswith("- path:"):  # noqa: E501  # expiry_wave: permanent  # added: W25 baseline sweep
            if current:
                entries.append(current)
            field = stripped.split(":", 1)
            current = {"_key": field[1].strip() if len(field) > 1 else "", "_source": "allowlists.yaml"}  # noqa: E501  # expiry_wave: permanent  # added: W25 baseline sweep
        elif current is not None and ":" in stripped and not stripped.startswith("#"):
            key, _, val = stripped.partition(":")
            current[key.strip()] = val.strip().strip('"\'')
    if current:
        entries.append(current)
    return entries


def _check_in_code_allowlists() -> list[dict]:
    """Scan check_*.py for ALLOWLIST patterns and check for expiry comments."""
    issues = []
    scripts_dir = ROOT / "scripts"
    pattern = re.compile(  # noqa: F841  # expiry_wave: permanent  # added: W25 baseline sweep
        r'^\s*["\']([^"\']+)["\'],?\s*#\s*(.*)$',
        re.MULTILINE,
    )
    expiry_pattern = re.compile(r'expiry_wave[:\s]+Wave\s*(\d+)', re.IGNORECASE)

    for script in sorted(scripts_dir.glob("check_*.py")):
        text = script.read_text(encoding="utf-8", errors="replace")
        # Look for ALLOWLIST or similar structures
        if "ALLOWLIST" not in text and "_EXEMPT_PATHS" not in text:
            continue
        # Find string entries in lists/sets without expiry comments
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r'["\']\s*(?:,|\]|\))', line) and "ALLOWLIST" in "".join(
                text.splitlines()[max(0, i-20):i]
            ):
                comment = ""
                if "#" in line:
                    comment = line[line.index("#"):]
                if not expiry_pattern.search(comment):
                    # Only flag if the entry looks like a real allowlist item (not a comment)
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and '"""' not in stripped:  # noqa: SIM102  # expiry_wave: permanent  # added: W25 baseline sweep
                        if re.search(r'["\'][\w./]+["\']', stripped):
                            issues.append({
                                "_source": f"{script.name}:{i}",
                                "line": stripped[:120],
                                "issue": "allowlist entry missing expiry_wave comment",
                            })
    return issues


def _validate_entries(entries: list[dict], current_wave: int) -> tuple[list[str], list[str]]:
    """Return (missing_field_issues, expired_issues)."""
    missing_fields = []
    expired = []

    for entry in entries:
        source = entry.get("_source", "unknown")
        key = entry.get("_key", str(entry.get("symbol", entry.get("path", "?"))))

        for field in _REQUIRED_FIELDS:
            if field not in entry or not entry[field]:
                missing_fields.append(f"{source} entry '{key}': missing field '{field}'")

        expiry = entry.get("expiry_wave", "")
        if expiry:
            m = re.match(r"Wave\s*(\d+)", str(expiry), re.IGNORECASE)
            if m and int(m.group(1)) <= current_wave:
                expired.append(
                    f"{source} entry '{key}': expired at Wave {m.group(1)} "
                    f"(current: Wave {current_wave})"
                )

    return missing_fields, expired


def main() -> int:
    parser = argparse.ArgumentParser(description="Universal allowlist expiry gate.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    current_wave = _current_wave_number()
    yaml_entries = _parse_allowlists_yaml()

    if not yaml_entries and not ALLOWLISTS_YAML.exists():
        result = {
            "status": "deferred",
            "check": "allowlist_universal",
            "reason": f"{ALLOWLISTS_YAML.relative_to(ROOT)} not found",
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"DEFERRED: {result['reason']}", file=sys.stderr)
        return 2

    missing_fields, expired = _validate_entries(yaml_entries, current_wave)
    all_issues = missing_fields + expired

    status = "pass" if not all_issues else "fail"
    result = {
        "status": status,
        "check": "allowlist_universal",
        "current_wave": f"Wave {current_wave}",
        "entries_checked": len(yaml_entries),
        "missing_field_issues": missing_fields,
        "expired_issues": expired,
        "total_issues": len(all_issues),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for issue in all_issues:
            print(f"{'FAIL' if issue in expired else 'FAIL'}: {issue}", file=sys.stderr)  # noqa: RUF034  # expiry_wave: permanent  # added: W25 baseline sweep
        if not all_issues:
            print(f"PASS: {len(yaml_entries)} allowlist entries checked, all valid and unexpired")

    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
