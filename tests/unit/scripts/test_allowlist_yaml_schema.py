"""Unit tests: docs/governance/allowlists.yaml schema conformance.

Validates that the YAML file:
- Exists and is parseable by the simple loader in check_allowlist_discipline.py
- Has schema_version and current_wave fields
- All entries carry all required fields
- No entries are expired (expiry_wave < current_wave)
- All risk values are valid
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make scripts/ importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_allowlist_discipline import (
    ALLOWLISTS_FILE,
    REQUIRED_FIELDS,
    VALID_RISKS,
    _load_yaml_simple,
)


def test_allowlists_yaml_exists() -> None:
    """docs/governance/allowlists.yaml must exist."""
    assert ALLOWLISTS_FILE.exists(), f"allowlists.yaml not found at {ALLOWLISTS_FILE}"


def test_allowlists_yaml_parseable() -> None:
    """The simple loader must not raise on the real file."""
    data = _load_yaml_simple(ALLOWLISTS_FILE)
    assert isinstance(data, dict)
    assert "entries" in data
    assert "current_wave" in data


def test_current_wave_positive() -> None:
    """current_wave must be a positive integer."""
    data = _load_yaml_simple(ALLOWLISTS_FILE)
    assert isinstance(data["current_wave"], int)
    assert data["current_wave"] > 0


def test_all_entries_have_required_fields() -> None:
    """Every entry must carry all required fields."""
    data = _load_yaml_simple(ALLOWLISTS_FILE)
    missing_report: list[str] = []
    for i, entry in enumerate(data["entries"]):
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            label = entry.get("entry", f"entry[{i}]")
            missing_report.append(f"{label}: missing {sorted(missing)}")
    assert not missing_report, "Entries missing required fields:\n" + "\n".join(missing_report)


def test_all_risk_values_valid() -> None:
    """Every entry risk must be in {low, medium, high}."""
    data = _load_yaml_simple(ALLOWLISTS_FILE)
    bad: list[str] = []
    for entry in data["entries"]:
        if entry.get("risk") not in VALID_RISKS:
            bad.append(f"{entry.get('entry', '?')}: risk={entry.get('risk')!r}")
    assert not bad, "Invalid risk values:\n" + "\n".join(bad)


def test_no_expired_entries() -> None:
    """No entry may have expiry_wave < current_wave (fail closed)."""
    data = _load_yaml_simple(ALLOWLISTS_FILE)
    current_wave = data["current_wave"]
    expired: list[str] = []
    for entry in data["entries"]:
        expiry = entry.get("expiry_wave")
        if isinstance(expiry, int) and expiry < current_wave:
            expired.append(
                f"{entry.get('entry', '?')}: expiry_wave={expiry} < current_wave={current_wave}"
            )
    assert not expired, "Expired allowlist entries (must be removed or wave bumped):\n" + "\n".join(
        expired
    )
