"""Tests for the failure taxonomy and structured error system."""

import pytest

from hi_agent.failures.taxonomy import (
    FailureCode,
    FailureRecord,
    FAILURE_RECOVERY_MAP,
    FAILURE_GATE_MAP,
    is_budget_exhausted_failure_code,
)
from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.watchdog import ProgressWatchdog
from hi_agent.failures.exceptions import (
    TraceFailure,
    MissingEvidenceError,
    InvalidContextError,
    HarnessDeniedError,
    ModelOutputInvalidError,
    ModelRefusalError,
    CallbackTimeoutError,
    NoProgressError,
    ContradictoryEvidenceError,
    UnsafeActionBlockedError,
    BudgetExhaustedError,
)


# ---------------------------------------------------------------------------
# FailureCode enum
# ---------------------------------------------------------------------------

class TestFailureCode:
    def test_at_least_11_values(self) -> None:
        """TraceFailureCode from agent-kernel defines 11 codes (9 original + 2 budget variants)."""
        assert len(FailureCode) >= 11

    def test_all_values_are_strings(self) -> None:
        for code in FailureCode:
            assert isinstance(code.value, str)

    def test_known_codes(self) -> None:
        expected = {
            "missing_evidence",
            "invalid_context",
            "harness_denied",
            "model_output_invalid",
            "model_refusal",
            "callback_timeout",
            "no_progress",
            "contradictory_evidence",
            "unsafe_action_blocked",
            "exploration_budget_exhausted",
            "execution_budget_exhausted",
        }
        actual = {code.value for code in FailureCode}
        assert expected.issubset(actual)

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (FailureCode.EXPLORATION_BUDGET_EXHAUSTED, True),
            (FailureCode.EXECUTION_BUDGET_EXHAUSTED, True),
            ("budget_exhausted", True),
            ("missing_evidence", False),
            ("not_a_real_code", False),
        ],
    )
    def test_is_budget_exhausted_failure_code(self, code, expected) -> None:
        assert is_budget_exhausted_failure_code(code) is expected


# ---------------------------------------------------------------------------
# Recovery and gate maps
# ---------------------------------------------------------------------------

class TestMaps:
    def test_recovery_map_covers_all_codes(self) -> None:
        for code in FailureCode:
            assert code in FAILURE_RECOVERY_MAP, f"{code} missing from FAILURE_RECOVERY_MAP"

    def test_gate_map_covers_all_codes(self) -> None:
        for code in FailureCode:
            assert code in FAILURE_GATE_MAP, f"{code} missing from FAILURE_GATE_MAP"

    def test_recovery_map_values_are_strings(self) -> None:
        for code, action in FAILURE_RECOVERY_MAP.items():
            assert isinstance(action, str)

    def test_gate_map_values_are_str_or_none(self) -> None:
        for code, gate in FAILURE_GATE_MAP.items():
            assert gate is None or isinstance(gate, str)


# ---------------------------------------------------------------------------
# FailureRecord
# ---------------------------------------------------------------------------

class TestFailureRecord:
    def test_creation_minimal(self) -> None:
        rec = FailureRecord(
            failure_code=FailureCode.MISSING_EVIDENCE,
            message="test message",
        )
        assert rec.failure_code == FailureCode.MISSING_EVIDENCE
        assert rec.message == "test message"
        assert rec.run_id == ""
        assert rec.context == {}
        assert rec.resolved is False

    def test_creation_full(self) -> None:
        rec = FailureRecord(
            failure_code=FailureCode.EXPLORATION_BUDGET_EXHAUSTED,
            message="out of tokens",
            run_id="run-1",
            stage_id="s3",
            branch_id="b1",
            action_id="a5",
            timestamp="2026-04-07T00:00:00Z",
            context={"tokens_used": 5000},
            recovery_action="cts_termination_or_gate_b",
            resolved=True,
        )
        assert rec.run_id == "run-1"
        assert rec.stage_id == "s3"
        assert rec.context["tokens_used"] == 5000
        assert rec.resolved is True

    def test_serialization_via_dataclass(self) -> None:
        """FailureRecord is a dataclass; verify __eq__ and field access."""
        rec1 = FailureRecord(failure_code=FailureCode.NO_PROGRESS, message="stuck")
        rec2 = FailureRecord(failure_code=FailureCode.NO_PROGRESS, message="stuck")
        assert rec1 == rec2


# ---------------------------------------------------------------------------
# FailureCollector
# ---------------------------------------------------------------------------

class TestFailureCollector:
    def _make_record(
        self,
        code: FailureCode = FailureCode.MISSING_EVIDENCE,
        message: str = "test",
        stage_id: str = "",
    ) -> FailureRecord:
        return FailureRecord(failure_code=code, message=message, stage_id=stage_id)

    def test_record_and_get_all(self) -> None:
        c = FailureCollector()
        r = self._make_record()
        c.record(r)
        assert len(c.get_all()) == 1
        assert c.get_all() is not c._records  # returns a copy of the list

    def test_get_by_code(self) -> None:
        c = FailureCollector()
        c.record(self._make_record(FailureCode.MISSING_EVIDENCE))
        c.record(self._make_record(FailureCode.NO_PROGRESS))
        c.record(self._make_record(FailureCode.MISSING_EVIDENCE))
        assert len(c.get_by_code(FailureCode.MISSING_EVIDENCE)) == 2
        assert len(c.get_by_code(FailureCode.NO_PROGRESS)) == 1
        assert len(c.get_by_code(FailureCode.EXPLORATION_BUDGET_EXHAUSTED)) == 0

    def test_get_by_stage(self) -> None:
        c = FailureCollector()
        c.record(self._make_record(stage_id="s1"))
        c.record(self._make_record(stage_id="s2"))
        c.record(self._make_record(stage_id="s1"))
        assert len(c.get_by_stage("s1")) == 2
        assert len(c.get_by_stage("s3")) == 0

    def test_mark_resolved(self) -> None:
        c = FailureCollector()
        c.record(self._make_record())
        c.record(self._make_record())
        assert len(c.get_unresolved()) == 2
        c.mark_resolved(0)
        assert len(c.get_unresolved()) == 1
        assert c.get_all()[0].resolved is True

    def test_mark_resolved_out_of_range(self) -> None:
        c = FailureCollector()
        c.record(self._make_record())
        c.mark_resolved(99)  # should not raise
        assert len(c.get_unresolved()) == 1

    def test_get_failure_codes_unique_ordered(self) -> None:
        c = FailureCollector()
        c.record(self._make_record(FailureCode.NO_PROGRESS))
        c.record(self._make_record(FailureCode.MISSING_EVIDENCE))
        c.record(self._make_record(FailureCode.NO_PROGRESS))
        codes = c.get_failure_codes()
        assert codes == ["no_progress", "missing_evidence"]

    def test_get_summary(self) -> None:
        c = FailureCollector()
        c.record(self._make_record(FailureCode.NO_PROGRESS, stage_id="s1"))
        c.record(self._make_record(FailureCode.NO_PROGRESS, stage_id="s2"))
        c.record(self._make_record(FailureCode.EXPLORATION_BUDGET_EXHAUSTED, stage_id="s2"))
        c.mark_resolved(0)

        summary = c.get_summary()
        assert summary["total"] == 3
        assert summary["resolved"] == 1
        assert summary["unresolved"] == 2
        assert summary["resolution_rate"] == pytest.approx(1 / 3)
        assert summary["counts_by_code"]["no_progress"] == 2
        assert summary["counts_by_code"]["exploration_budget_exhausted"] == 1
        assert summary["stage_distribution"]["s1"] == 1
        assert summary["stage_distribution"]["s2"] == 2

    def test_get_summary_empty(self) -> None:
        c = FailureCollector()
        summary = c.get_summary()
        assert summary["total"] == 0
        assert summary["resolution_rate"] == 0.0

    def test_suggests_gate_returns_gate(self) -> None:
        c = FailureCollector()
        c.record(self._make_record(FailureCode.MISSING_EVIDENCE))  # no gate
        assert c.suggests_gate() is None
        c.record(self._make_record(FailureCode.HARNESS_DENIED))  # gate_d
        assert c.suggests_gate() == "gate_d"

    def test_suggests_gate_resolved_ignored(self) -> None:
        c = FailureCollector()
        c.record(self._make_record(FailureCode.UNSAFE_ACTION_BLOCKED))
        c.mark_resolved(0)
        assert c.suggests_gate() is None

    def test_suggests_gate_none_when_empty(self) -> None:
        c = FailureCollector()
        assert c.suggests_gate() is None


# ---------------------------------------------------------------------------
# ProgressWatchdog
# ---------------------------------------------------------------------------

class TestProgressWatchdog:
    def test_initial_state(self) -> None:
        w = ProgressWatchdog()
        assert w.consecutive_failures == 0
        assert w.success_rate == 1.0
        assert w.check() is None

    def test_record_successes_no_trigger(self) -> None:
        w = ProgressWatchdog(window_size=5)
        for _ in range(10):
            w.record_action(True)
        assert w.check() is None
        assert w.success_rate == 1.0

    def test_consecutive_failure_detection(self) -> None:
        w = ProgressWatchdog(max_consecutive_failures=3, window_size=20)
        w.record_action(True)
        w.record_action(False)
        w.record_action(False)
        assert w.check() is None  # only 2 consecutive
        w.record_action(False)
        result = w.check()
        assert result is not None
        assert result.failure_code == FailureCode.NO_PROGRESS
        assert result.context["trigger"] == "consecutive_failures"

    def test_consecutive_failures_reset_on_success(self) -> None:
        w = ProgressWatchdog(max_consecutive_failures=3, window_size=20)
        w.record_action(False)
        w.record_action(False)
        w.record_action(True)  # reset
        w.record_action(False)
        assert w.consecutive_failures == 1
        assert w.check() is None

    def test_low_success_rate_detection(self) -> None:
        w = ProgressWatchdog(window_size=5, min_success_rate=0.4, max_consecutive_failures=100)
        # 1 success, 4 failures -> rate 0.2 < 0.4
        w.record_action(True)
        w.record_action(False)
        w.record_action(False)
        w.record_action(False)
        w.record_action(False)
        result = w.check()
        assert result is not None
        assert result.failure_code == FailureCode.NO_PROGRESS
        assert result.context["trigger"] == "low_success_rate"

    def test_window_not_full_no_rate_trigger(self) -> None:
        w = ProgressWatchdog(window_size=10, min_success_rate=0.5, max_consecutive_failures=100)
        # Only 3 actions, all failures, but window not full
        w.record_action(False)
        w.record_action(False)
        w.record_action(False)
        assert w.check() is None

    def test_reset(self) -> None:
        w = ProgressWatchdog()
        w.record_action(False)
        w.record_action(False)
        w.reset()
        assert w.consecutive_failures == 0
        assert w.success_rate == 1.0

    def test_success_rate_calculation(self) -> None:
        w = ProgressWatchdog(window_size=4)
        w.record_action(True)
        w.record_action(False)
        w.record_action(True)
        w.record_action(False)
        assert w.success_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_trace_failure_base(self) -> None:
        err = TraceFailure(FailureCode.MISSING_EVIDENCE, "not found", source="db")
        assert err.code == FailureCode.MISSING_EVIDENCE
        assert err.message == "not found"
        assert err.context == {"source": "db"}
        assert "[missing_evidence]" in str(err)

    def test_trace_failure_to_record(self) -> None:
        err = TraceFailure(FailureCode.EXPLORATION_BUDGET_EXHAUSTED, "over limit", tokens=999)
        rec = err.to_record(run_id="r1", stage_id="s2")
        assert rec.failure_code == FailureCode.EXPLORATION_BUDGET_EXHAUSTED
        assert rec.message == "over limit"
        assert rec.run_id == "r1"
        assert rec.stage_id == "s2"
        assert rec.context == {"tokens": 999}
        assert rec.recovery_action == "cts_termination_or_gate_b"

    def test_to_record_default_ids(self) -> None:
        err = TraceFailure(FailureCode.NO_PROGRESS, "stuck")
        rec = err.to_record()
        assert rec.run_id == ""
        assert rec.stage_id == ""

    def test_subclass_missing_evidence(self) -> None:
        err = MissingEvidenceError()
        assert err.code == FailureCode.MISSING_EVIDENCE
        assert isinstance(err, TraceFailure)

    def test_subclass_invalid_context(self) -> None:
        err = InvalidContextError("bad context")
        assert err.code == FailureCode.INVALID_CONTEXT
        assert err.message == "bad context"

    def test_subclass_harness_denied(self) -> None:
        err = HarnessDeniedError(action="file_write")
        assert err.code == FailureCode.HARNESS_DENIED
        assert err.context["action"] == "file_write"

    def test_subclass_model_output_invalid(self) -> None:
        assert ModelOutputInvalidError().code == FailureCode.MODEL_OUTPUT_INVALID

    def test_subclass_model_refusal(self) -> None:
        assert ModelRefusalError().code == FailureCode.MODEL_REFUSAL

    def test_subclass_callback_timeout(self) -> None:
        assert CallbackTimeoutError().code == FailureCode.CALLBACK_TIMEOUT

    def test_subclass_no_progress(self) -> None:
        assert NoProgressError().code == FailureCode.NO_PROGRESS

    def test_subclass_contradictory_evidence(self) -> None:
        assert ContradictoryEvidenceError().code == FailureCode.CONTRADICTORY_EVIDENCE

    def test_subclass_unsafe_action_blocked(self) -> None:
        assert UnsafeActionBlockedError().code == FailureCode.UNSAFE_ACTION_BLOCKED

    def test_subclass_budget_exhausted(self) -> None:
        assert BudgetExhaustedError().code == FailureCode.EXPLORATION_BUDGET_EXHAUSTED

    def test_all_subclass_trace_failure(self) -> None:
        """All specific exceptions must subclass TraceFailure."""
        subclasses = [
            MissingEvidenceError,
            InvalidContextError,
            HarnessDeniedError,
            ModelOutputInvalidError,
            ModelRefusalError,
            CallbackTimeoutError,
            NoProgressError,
            ContradictoryEvidenceError,
            UnsafeActionBlockedError,
            BudgetExhaustedError,
        ]
        for cls in subclasses:
            assert issubclass(cls, TraceFailure), f"{cls.__name__} not subclass of TraceFailure"
            assert issubclass(cls, Exception)

    def test_exception_is_catchable(self) -> None:
        with pytest.raises(TraceFailure):
            raise MissingEvidenceError("test")

        with pytest.raises(MissingEvidenceError):
            raise MissingEvidenceError("test")

    def test_subclass_to_record(self) -> None:
        err = HarnessDeniedError("denied", tool="bash")
        rec = err.to_record(run_id="r1")
        assert rec.failure_code == FailureCode.HARNESS_DENIED
        assert rec.recovery_action == "approval_escalation"
        assert rec.context == {"tool": "bash"}
