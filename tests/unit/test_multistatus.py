"""Unit tests for the multistatus gate protocol (W23-A).

Covers the dataclass round-trip, emit/parse, and the runner aggregation.
The runner-aggregation tests use a fake `subprocess.run` so they remain
hermetic (no real gate invocations).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

# Wire scripts/ onto sys.path so `from _governance.multistatus import ...` works
# the same way it does inside the gate scripts themselves.
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _governance import multistatus_runner
from _governance.multistatus import (
    GateResult,
    GateStatus,
    MultistatusParseError,
    emit,
    parse,
)

# ---------------------------------------------------------------------------
# GateStatus enum
# ---------------------------------------------------------------------------


def test_gatestatus_values_are_uppercase() -> None:
    assert GateStatus.PASS.value == "PASS"
    assert GateStatus.FAIL.value == "FAIL"
    assert GateStatus.WARN.value == "WARN"
    assert GateStatus.DEFER.value == "DEFER"


def test_gatestatus_from_str_accepts_canonical_form() -> None:
    assert GateStatus.from_str("PASS") is GateStatus.PASS
    assert GateStatus.from_str("fail") is GateStatus.FAIL
    assert GateStatus.from_str("  Warn  ") is GateStatus.WARN


def test_gatestatus_from_str_rejects_unknown() -> None:
    with pytest.raises(MultistatusParseError):
        GateStatus.from_str("MAYBE")


# ---------------------------------------------------------------------------
# GateResult dataclass round-trip
# ---------------------------------------------------------------------------


def test_gateresult_round_trip_via_dict() -> None:
    original = GateResult(
        status=GateStatus.PASS,
        gate_name="contract_freeze",
        reason="no uncommitted changes",
        evidence={"changed_files": 0, "v1_released": False},
        expiry_wave=25,
    )
    payload = original.to_dict()
    assert payload == {
        "gate": "contract_freeze",
        "status": "PASS",
        "reason": "no uncommitted changes",
        "evidence": {"changed_files": 0, "v1_released": False},
        "expiry_wave": 25,
    }
    restored = GateResult.from_dict(payload)
    assert restored == original


def test_gateresult_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    r = GateResult(status=GateStatus.PASS, gate_name="g")
    with pytest.raises(FrozenInstanceError):
        r.gate_name = "other"  # type: ignore[misc] # expiry_wave: permanent


def test_gateresult_from_dict_rejects_missing_field() -> None:
    with pytest.raises(MultistatusParseError):
        GateResult.from_dict({"status": "PASS"})  # missing gate
    with pytest.raises(MultistatusParseError):
        GateResult.from_dict({"gate": "g"})  # missing status


def test_gateresult_from_dict_rejects_bad_evidence_type() -> None:
    with pytest.raises(MultistatusParseError):
        GateResult.from_dict({"gate": "g", "status": "PASS", "evidence": "nope"})


def test_gateresult_from_dict_rejects_bad_expiry_type() -> None:
    with pytest.raises(MultistatusParseError):
        GateResult.from_dict({"gate": "g", "status": "PASS", "expiry_wave": "23"})


# ---------------------------------------------------------------------------
# emit / parse round-trip and exit codes
# ---------------------------------------------------------------------------


def test_emit_pass_writes_json_and_exits_zero() -> None:
    buf = io.StringIO()
    r = GateResult(
        status=GateStatus.PASS,
        gate_name="g",
        reason="ok",
        evidence={"k": 1},
    )
    with pytest.raises(SystemExit) as exc:
        emit(r, stream=buf)
    assert exc.value.code == 0
    payload = json.loads(buf.getvalue().strip())
    assert payload == {
        "gate": "g",
        "status": "PASS",
        "reason": "ok",
        "evidence": {"k": 1},
        "expiry_wave": None,
    }


@pytest.mark.parametrize(
    "status,expected_exit",
    [
        (GateStatus.PASS, 0),
        (GateStatus.WARN, 0),
        (GateStatus.DEFER, 0),
        (GateStatus.FAIL, 1),
    ],
)
def test_emit_exit_codes_match_protocol(status, expected_exit) -> None:
    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        emit(GateResult(status=status, gate_name="g"), stream=buf)
    assert exc.value.code == expected_exit


def test_parse_round_trip_with_legacy_preamble() -> None:
    """parse() must tolerate human-readable lines preceding the JSON line."""
    json_line = json.dumps({
        "gate": "facade_loc",
        "status": "FAIL",
        "reason": "1 facade module exceeds 200 LOC",
        "evidence": {"violations": ["agent_server/facade/big.py: 250 LOC"]},
        "expiry_wave": None,
    }, separators=(",", ":"))
    output = "FAIL (R-AS-8): some legacy text\n  big.py: 250 LOC\n" + json_line + "\n"
    result = parse(output)
    assert result.status is GateStatus.FAIL
    assert result.gate_name == "facade_loc"
    assert "200 LOC" in result.reason
    assert result.evidence["violations"][0].startswith("agent_server/facade/big.py")


def test_parse_uses_last_valid_json_line() -> None:
    first = json.dumps({"gate": "g", "status": "WARN"})
    last = json.dumps({"gate": "g", "status": "PASS"})
    out = first + "\n" + last + "\n"
    assert parse(out).status is GateStatus.PASS


def test_parse_raises_when_no_json_line() -> None:
    with pytest.raises(MultistatusParseError):
        parse("just plain text\nno json here\n")


def test_parse_rejects_non_string() -> None:
    with pytest.raises(MultistatusParseError):
        parse(b"bytes")  # type: ignore[arg-type] # expiry_wave: permanent


# ---------------------------------------------------------------------------
# multistatus_runner aggregation
# ---------------------------------------------------------------------------


def test_aggregate_counts_each_status_once() -> None:
    results = [
        GateResult(status=GateStatus.PASS,  gate_name="a"),
        GateResult(status=GateStatus.PASS,  gate_name="b"),
        GateResult(status=GateStatus.FAIL,  gate_name="c", reason="boom"),
        GateResult(status=GateStatus.WARN,  gate_name="d"),
        GateResult(status=GateStatus.DEFER, gate_name="e"),
    ]
    payload = multistatus_runner.aggregate(results)
    assert payload["pass_count"] == 2
    assert payload["fail_count"] == 1
    assert payload["warn_count"] == 1
    assert payload["defer_count"] == 1
    assert len(payload["results"]) == 5
    assert payload["results"][2]["status"] == "FAIL"


def test_run_gate_unknown_name_returns_fail() -> None:
    r = multistatus_runner.run_gate("does_not_exist")
    assert r.status is GateStatus.FAIL
    assert "unknown gate" in r.reason.lower()


def test_run_gate_handles_subprocess_with_fake(monkeypatch) -> None:
    """run_gate parses real stdout when subprocess succeeds."""
    fake_payload = {
        "gate": "contract_freeze",
        "status": "PASS",
        "reason": "ok",
        "evidence": {"changed_files": 0},
        "expiry_wave": None,
    }
    fake_stdout = json.dumps(fake_payload) + "\n"

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = fake_stdout
            self.stderr = ""
            self.returncode = 0

    def fake_run(cmd, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(multistatus_runner.subprocess, "run", fake_run)
    r = multistatus_runner.run_gate("contract_freeze")
    assert r.status is GateStatus.PASS
    assert r.gate_name == "contract_freeze"


def test_run_gate_detects_exit_code_status_disagreement(monkeypatch) -> None:
    """A gate whose stdout says PASS but exit code is non-zero must surface FAIL."""
    fake_stdout = json.dumps({"gate": "contract_freeze", "status": "PASS"}) + "\n"

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = fake_stdout
            self.stderr = ""
            self.returncode = 1  # disagrees with PASS

    monkeypatch.setattr(multistatus_runner.subprocess, "run", lambda *a, **kw: _FakeProc())
    r = multistatus_runner.run_gate("contract_freeze")
    assert r.status is GateStatus.FAIL
    assert "disagreement" in r.reason.lower()


def test_run_gate_handles_unparseable_output(monkeypatch) -> None:
    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = "no json at all"
            self.stderr = ""
            self.returncode = 0

    monkeypatch.setattr(multistatus_runner.subprocess, "run", lambda *a, **kw: _FakeProc())
    r = multistatus_runner.run_gate("contract_freeze")
    assert r.status is GateStatus.FAIL
    assert "did not emit multistatus json" in r.reason.lower()


def test_run_gate_handles_timeout(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise multistatus_runner.subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(multistatus_runner.subprocess, "run", _raise)
    r = multistatus_runner.run_gate("contract_freeze", timeout=1)
    assert r.status is GateStatus.FAIL
    assert "timed out" in r.reason.lower()


def test_runner_main_returns_zero_when_all_pass(monkeypatch, capsys) -> None:
    """End-to-end main() smoke test with a stubbed run_gate."""

    def fake_run_gate(name, *, timeout=60):
        return GateResult(
            status=GateStatus.PASS,
            gate_name=name,
            reason="stubbed",
        )

    monkeypatch.setattr(multistatus_runner, "run_gate", fake_run_gate)
    rc = multistatus_runner.main(["--all", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out.strip())
    assert payload["fail_count"] == 0
    assert payload["pass_count"] == len(multistatus_runner.GATES)


def test_runner_main_returns_one_on_any_fail(monkeypatch, capsys) -> None:
    def fake_run_gate(name, *, timeout=60):
        if name == "contract_freeze":
            return GateResult(status=GateStatus.FAIL, gate_name=name, reason="boom")
        return GateResult(status=GateStatus.PASS, gate_name=name)

    monkeypatch.setattr(multistatus_runner, "run_gate", fake_run_gate)
    rc = multistatus_runner.main(["--all", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert rc == 1
    assert payload["fail_count"] == 1
