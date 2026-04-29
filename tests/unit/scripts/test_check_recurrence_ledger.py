"""Unit tests: check_recurrence_ledger.py main() logic.

Tests:
- Missing ledger file => exit 2 (deferred)
- Valid entry with all required fields => exit 0
- Entry missing required fields => exit 1
- Entry with invalid closure level => exit 1
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_recurrence_ledger as mod

_VALID_LEDGER = """\
schema_version: "1"
entries:
  - issue_id: DF-TEST-01
    defect_class: test_class
    named_instance: test instance description
    peer_instances_audited: "yes, checked 3 peers"
    root_cause: "X happens because Y at line Z"
    code_fix: "commit abc1234"
    regression_test: "tests/unit/scripts/test_check_recurrence_ledger.py"
    release_gate: "CI gate check_foo.py"
    process_change: "Added rule to CLAUDE.md"
    owner: CO
    expiry_or_followup: "Wave 20"
    evidence_artifact: "docs/verification/abc1234-foo.json"
    current_closure_level: verified_at_release_head
    metric_name: hi_agent_test_metric_total
    alert_rule: "<placeholder, expiry: Wave 22>"
    runbook_path: "<placeholder, expiry: Wave 22>"
"""

_MISSING_FIELDS_LEDGER = """\
schema_version: "1"
entries:
  - issue_id: DF-TEST-02
    defect_class: test_class
    named_instance: incomplete entry
"""

_INVALID_CLOSURE_LEDGER = """\
schema_version: "1"
entries:
  - issue_id: DF-TEST-03
    defect_class: test_class
    named_instance: bad closure level
    peer_instances_audited: "yes"
    root_cause: "some cause"
    code_fix: "commit xyz"
    regression_test: "tests/unit/test_baz.py"
    release_gate: "CI gate"
    process_change: "CLAUDE.md updated"
    owner: RO
    expiry_or_followup: "Wave 20"
    evidence_artifact: "docs/verification/xyz-baz.json"
    current_closure_level: nonexistent_level
"""


def test_missing_ledger_returns_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the ledger file does not exist, exit code must be 2 (deferred)."""
    monkeypatch.setattr(mod, "LEDGER_PATH", tmp_path / "nonexistent.yaml")
    monkeypatch.setattr(sys, "argv", ["check_recurrence_ledger"])
    result = mod.main()
    assert result == 2


def test_valid_ledger_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fully valid ledger must exit 0."""
    ledger = tmp_path / "recurrence-ledger.yaml"
    ledger.write_text(_VALID_LEDGER, encoding="utf-8")
    monkeypatch.setattr(mod, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sys, "argv", ["check_recurrence_ledger"])
    result = mod.main()
    assert result == 0


def test_missing_fields_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry with missing required fields must exit 1."""
    ledger = tmp_path / "recurrence-ledger.yaml"
    ledger.write_text(_MISSING_FIELDS_LEDGER, encoding="utf-8")
    monkeypatch.setattr(mod, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sys, "argv", ["check_recurrence_ledger"])
    result = mod.main()
    assert result == 1


def test_invalid_closure_level_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry with an unrecognised closure level must exit 1."""
    ledger = tmp_path / "recurrence-ledger.yaml"
    ledger.write_text(_INVALID_CLOSURE_LEDGER, encoding="utf-8")
    monkeypatch.setattr(mod, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sys, "argv", ["check_recurrence_ledger"])
    result = mod.main()
    assert result == 1


def test_json_flag_reports_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--json on missing-fields ledger must emit parseable JSON with status=fail."""
    ledger = tmp_path / "recurrence-ledger.yaml"
    ledger.write_text(_MISSING_FIELDS_LEDGER, encoding="utf-8")
    monkeypatch.setattr(mod, "LEDGER_PATH", ledger)
    monkeypatch.setattr(sys, "argv", ["check_recurrence_ledger", "--json"])

    result = mod.main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert result == 1
    assert data["status"] == "fail"
    assert len(data["issues"]) > 0
