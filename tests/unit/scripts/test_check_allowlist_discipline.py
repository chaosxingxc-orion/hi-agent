"""Unit tests: check_allowlist_discipline.py main() logic.

Tests:
- All-valid YAML input => exit 0
- Entry missing a required field => exit 1
- Invalid risk value => exit 1
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_allowlist_discipline import main

_VALID_YAML = """\
schema_version: "1"
current_wave: 5

entries:
  - allowlist: vocab_path_allowlist
    entry: hi_agent/foo/bar.py
    owner: CO
    risk: low
    reason: Test shim entry.
    expiry_wave: 6
    replacement_test: tests/unit/test_foo.py
    added_at: "2026-01-01"
"""

_MISSING_FIELD_YAML = """\
schema_version: "1"
current_wave: 5

entries:
  - allowlist: vocab_path_allowlist
    entry: hi_agent/foo/bar.py
    owner: CO
    risk: low
    reason: Missing expiry_wave and replacement_test and added_at.
    expiry_wave: 6
"""

_INVALID_RISK_YAML = """\
schema_version: "1"
current_wave: 5

entries:
  - allowlist: vocab_path_allowlist
    entry: hi_agent/foo/bar.py
    owner: CO
    risk: extreme
    reason: Bad risk level.
    expiry_wave: 6
    replacement_test: tests/unit/test_foo.py
    added_at: "2026-01-01"
"""


def test_valid_yaml_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully valid allowlists.yaml must exit 0."""
    yaml_file = tmp_path / "allowlists.yaml"
    yaml_file.write_text(_VALID_YAML, encoding="utf-8")

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    assert main([]) == 0


def test_valid_yaml_json_flag_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--json flag on valid YAML must emit status=pass and exit 0."""
    import json

    yaml_file = tmp_path / "allowlists.yaml"
    yaml_file.write_text(_VALID_YAML, encoding="utf-8")

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    result = main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert result == 0
    assert data["status"] == "pass"


def test_missing_field_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry missing required fields must exit 1."""
    yaml_file = tmp_path / "allowlists.yaml"
    yaml_file.write_text(_MISSING_FIELD_YAML, encoding="utf-8")

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    assert main([]) == 1


def test_missing_field_json_reports_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--json on entry with missing fields must report status=fail."""
    import json

    yaml_file = tmp_path / "allowlists.yaml"
    yaml_file.write_text(_MISSING_FIELD_YAML, encoding="utf-8")

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    result = main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert result == 1
    assert data["status"] == "fail"
    assert data["missing_fields_total"] > 0


def test_invalid_risk_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry with an invalid risk value must exit 1."""
    yaml_file = tmp_path / "allowlists.yaml"
    yaml_file.write_text(_INVALID_RISK_YAML, encoding="utf-8")

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    assert main([]) == 1


def test_missing_file_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing allowlists.yaml must exit 1."""
    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", tmp_path / "nonexistent.yaml")
    assert main([]) == 1
