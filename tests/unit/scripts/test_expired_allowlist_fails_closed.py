"""Unit tests: expired allowlist entries fail closed.

Specifically proves that an entry with expiry_wave < current_wave
causes check_allowlist_discipline.main() to exit 1.

Also proves that expiry_wave == current_wave does NOT trigger failure
(expiring-this-wave is a warning, not yet expired).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_allowlist_discipline import main

_EXPIRED_YAML_TEMPLATE = """\
schema_version: "1"
current_wave: {current_wave}

entries:
  - allowlist: vocab_path_allowlist
    entry: hi_agent/foo/bar.py
    owner: CO
    risk: low
    reason: This entry is past its expiry.
    expiry_wave: {expiry_wave}
    replacement_test: tests/unit/test_foo.py
    added_at: "2026-01-01"
"""


def _make_yaml(tmp_path: Path, current_wave: int, expiry_wave: int) -> Path:
    yaml_file = tmp_path / "allowlists.yaml"
    yaml_file.write_text(
        _EXPIRED_YAML_TEMPLATE.format(current_wave=current_wave, expiry_wave=expiry_wave),
        encoding="utf-8",
    )
    return yaml_file


def test_expired_entry_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """expiry_wave=10 with current_wave=12 must fail closed (exit 1)."""
    yaml_file = _make_yaml(tmp_path, current_wave=12, expiry_wave=10)

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    assert main([]) == 1


def test_expired_entry_json_reports_expired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--json on expired entry must report status=fail and expired_total > 0."""
    yaml_file = _make_yaml(tmp_path, current_wave=12, expiry_wave=10)

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    result = main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert result == 1
    assert data["status"] == "fail"
    assert data["expired_total"] >= 1


def test_expiry_equal_current_wave_does_not_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """expiry_wave == current_wave must NOT fail (expiring-this-wave, not yet expired)."""
    yaml_file = _make_yaml(tmp_path, current_wave=12, expiry_wave=12)

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    assert main([]) == 0


def test_expiry_one_before_current_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """expiry_wave = current_wave - 1 must fail closed."""
    yaml_file = _make_yaml(tmp_path, current_wave=12, expiry_wave=11)

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    assert main([]) == 1


def test_future_expiry_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """expiry_wave > current_wave must pass."""
    yaml_file = _make_yaml(tmp_path, current_wave=12, expiry_wave=15)

    import check_allowlist_discipline as mod

    monkeypatch.setattr(mod, "ALLOWLISTS_FILE", yaml_file)
    assert main([]) == 0
