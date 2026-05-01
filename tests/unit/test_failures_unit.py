"""Unit tests for hi_agent.failures — Layer 1 (unit).

Covers:
  - FailureCode (taxonomy): enum values, is_budget_exhausted_failure_code
  - FailureRecord: construction, field defaults, resolved flag
  - FailureCollector: record, get_all, get_by_code, get_by_stage, mark_resolved
  - ProgressWatchdog: consecutive failure detection, success rate trigger

No network, no real LLM, no external mocks.
Profile validated: default-offline
"""

from __future__ import annotations

from hi_agent.failures.collector import FailureCollector
from hi_agent.failures.taxonomy import (
    FAILURE_GATE_MAP,
    FAILURE_RECOVERY_MAP,
    FailureCode,
    FailureRecord,
    is_budget_exhausted_failure_code,
)
from hi_agent.failures.watchdog import ProgressWatchdog

# ---------------------------------------------------------------------------
# FailureCode enum
# ---------------------------------------------------------------------------


class TestFailureCode:
    def test_known_code_values_present(self) -> None:
        codes = {fc.value for fc in FailureCode}
        assert "missing_evidence" in codes
        assert "model_output_invalid" in codes
        assert "no_progress" in codes

    def test_budget_codes_detected(self) -> None:
        assert is_budget_exhausted_failure_code(FailureCode.EXPLORATION_BUDGET_EXHAUSTED) is True
        assert is_budget_exhausted_failure_code(FailureCode.EXECUTION_BUDGET_EXHAUSTED) is True

    def test_non_budget_code_not_detected(self) -> None:
        assert is_budget_exhausted_failure_code(FailureCode.MISSING_EVIDENCE) is False

    def test_legacy_string_budget_exhausted(self) -> None:
        assert is_budget_exhausted_failure_code("budget_exhausted") is True

    def test_unknown_string_returns_false(self) -> None:
        assert is_budget_exhausted_failure_code("not_a_code") is False


# ---------------------------------------------------------------------------
# FailureRecord construction
# ---------------------------------------------------------------------------


class TestFailureRecord:
    def test_minimal_creation(self) -> None:
        rec = FailureRecord(failure_code=FailureCode.MISSING_EVIDENCE, message="missing context")
        assert rec.failure_code == FailureCode.MISSING_EVIDENCE
        assert rec.message == "missing context"
        assert rec.resolved is False

    def test_default_empty_ids(self) -> None:
        rec = FailureRecord(failure_code=FailureCode.NO_PROGRESS, message="stuck")
        assert rec.run_id == ""
        assert rec.stage_id == ""
        assert rec.branch_id == ""

    def test_full_fields(self) -> None:
        rec = FailureRecord(
            failure_code=FailureCode.INVALID_CONTEXT,
            message="bad context",
            run_id="r1",
            stage_id="S3",
            branch_id="b0",
            context={"key": "val"},
        )
        assert rec.run_id == "r1"
        assert rec.stage_id == "S3"
        assert rec.context["key"] == "val"


# ---------------------------------------------------------------------------
# FailureCollector
# ---------------------------------------------------------------------------


class TestFailureCollector:
    def _rec(
        self, code: FailureCode = FailureCode.MISSING_EVIDENCE, stage: str = "S1"
    ) -> FailureRecord:
        return FailureRecord(failure_code=code, message="test", stage_id=stage)

    def test_empty_collector(self) -> None:
        fc = FailureCollector()
        assert fc.get_all() == []

    def test_record_and_get_all(self) -> None:
        fc = FailureCollector()
        fc.record(self._rec())
        fc.record(self._rec())
        assert len(fc.get_all()) == 2

    def test_get_by_code_filters_correctly(self) -> None:
        fc = FailureCollector()
        fc.record(self._rec(FailureCode.MISSING_EVIDENCE))
        fc.record(self._rec(FailureCode.NO_PROGRESS))
        result = fc.get_by_code(FailureCode.NO_PROGRESS)
        assert len(result) == 1
        assert result[0].failure_code == FailureCode.NO_PROGRESS

    def test_get_by_stage_filters_correctly(self) -> None:
        fc = FailureCollector()
        fc.record(self._rec(stage="S1"))
        fc.record(self._rec(stage="S2"))
        fc.record(self._rec(stage="S1"))
        s1 = fc.get_by_stage("S1")
        assert len(s1) == 2

    def test_mark_resolved_clears_entry(self) -> None:
        fc = FailureCollector()
        fc.record(self._rec())
        fc.mark_resolved(0)
        assert fc.get_all()[0].resolved is True

    def test_get_unresolved_excludes_resolved(self) -> None:
        fc = FailureCollector()
        fc.record(self._rec())
        fc.record(self._rec())
        fc.mark_resolved(0)
        unresolved = fc.get_unresolved()
        assert len(unresolved) == 1


# ---------------------------------------------------------------------------
# ProgressWatchdog
# ---------------------------------------------------------------------------


class TestProgressWatchdog:
    def test_fresh_watchdog_no_trigger(self) -> None:
        wd = ProgressWatchdog()
        assert wd.check() is None

    def test_consecutive_failures_trigger(self) -> None:
        wd = ProgressWatchdog(max_consecutive_failures=3)
        for _ in range(3):
            wd.record_action(success=False)
        result = wd.check()
        assert result is not None
        assert result.failure_code == FailureCode.NO_PROGRESS

    def test_success_resets_consecutive_failures(self) -> None:
        wd = ProgressWatchdog(max_consecutive_failures=3)
        wd.record_action(success=False)
        wd.record_action(success=False)
        wd.record_action(success=True)  # reset
        assert wd.check() is None

    def test_low_success_rate_triggers_over_full_window(self) -> None:
        wd = ProgressWatchdog(window_size=5, min_success_rate=0.5, max_consecutive_failures=100)
        for _ in range(5):
            wd.record_action(success=False)
        result = wd.check()
        assert result is not None

    def test_reset_clears_watchdog(self) -> None:
        wd = ProgressWatchdog(max_consecutive_failures=2)
        wd.record_action(success=False)
        wd.record_action(success=False)
        wd.reset()
        assert wd.check() is None


# ---------------------------------------------------------------------------
# Maps completeness sanity
# ---------------------------------------------------------------------------


class TestMaps:
    def test_recovery_map_covers_all_failure_codes(self) -> None:
        for code in FailureCode:
            assert code in FAILURE_RECOVERY_MAP, f"{code} missing from FAILURE_RECOVERY_MAP"

    def test_gate_map_covers_all_failure_codes(self) -> None:
        for code in FailureCode:
            assert code in FAILURE_GATE_MAP, f"{code} missing from FAILURE_GATE_MAP"
