"""Unit tests for round-3 defect fixes D-1 and D-2.

D-1: GatePendingError must carry gate_id attribute.
D-2: _decide() must inject reflection prompt before each retry when on_exhausted="reflect".
"""

from __future__ import annotations

import pytest

from hi_agent.gate_protocol import GatePendingError
from hi_agent.task_mgmt.restart_policy import RestartDecision, RestartPolicyEngine, TaskRestartPolicy


# ---------------------------------------------------------------------------
# D-1: GatePendingError carries gate_id
# ---------------------------------------------------------------------------


class TestGatePendingError:
    def test_gate_id_attribute(self) -> None:
        """Raised exception must expose gate_id matching the constructor argument."""
        with pytest.raises(GatePendingError) as exc_info:
            raise GatePendingError("my-gate")
        assert exc_info.value.gate_id == "my-gate"

    def test_gate_id_in_message(self) -> None:
        """Default message must include the gate_id string."""
        with pytest.raises(GatePendingError) as exc_info:
            raise GatePendingError("my-gate")
        assert "my-gate" in str(exc_info.value)

    def test_custom_message(self) -> None:
        """Custom message is used when provided; gate_id attribute still set."""
        with pytest.raises(GatePendingError) as exc_info:
            raise GatePendingError("g1", message="custom msg")
        assert exc_info.value.gate_id == "g1"
        assert "custom msg" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Helpers for D-2 tests
# ---------------------------------------------------------------------------


def _make_policy(on_exhausted: str, max_attempts: int = 3) -> TaskRestartPolicy:
    """Build a TaskRestartPolicy with the given on_exhausted action."""
    return TaskRestartPolicy(
        max_attempts=max_attempts,
        on_exhausted=on_exhausted,  # type: ignore[arg-type]
    )


def _make_engine() -> RestartPolicyEngine:
    """Build a minimal RestartPolicyEngine (callables unused in _decide tests)."""
    return RestartPolicyEngine(
        get_attempts=lambda _: [],
        get_policy=lambda _: None,
        update_state=lambda *_: None,
        record_attempt=lambda _: None,
    )


class _Failure:
    """Minimal failure stub accepted by _decide."""

    retryability = "unknown"

    def __init__(self, code: str = "test_error") -> None:
        self.failure_code = code


# ---------------------------------------------------------------------------
# D-2 test A: reflect policy, attempt_seq < max_attempts → action="reflect", next_attempt_seq set
# ---------------------------------------------------------------------------


class TestDecideReflectBeforeExhausted:
    def test_reflect_action_on_early_attempt(self) -> None:
        """on_exhausted='reflect' + attempt_seq=0, max_attempts=3 → action='reflect'."""
        engine = _make_engine()
        policy = _make_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())

        assert decision.action == "reflect"

    def test_next_attempt_seq_incremented(self) -> None:
        """next_attempt_seq must be attempt_seq + 1 (not None)."""
        engine = _make_engine()
        policy = _make_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())

        assert decision.next_attempt_seq == 1

    def test_reflection_prompt_contains_attempt_number(self) -> None:
        """reflection_prompt must mention the failed attempt number."""
        engine = _make_engine()
        policy = _make_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())

        assert decision.reflection_prompt is not None
        assert "Attempt 0" in decision.reflection_prompt


# ---------------------------------------------------------------------------
# D-2 test B: retry policy, attempt_seq < max_attempts → action="retry", no reflection
# ---------------------------------------------------------------------------


class TestDecideRetryPolicy:
    def test_retry_action(self) -> None:
        """on_exhausted='retry' (or any non-reflect) → action='retry'."""
        engine = _make_engine()
        policy = _make_policy("retry", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())

        assert decision.action == "retry"

    def test_no_reflection_prompt_for_retry(self) -> None:
        """reflection_prompt must be None when on_exhausted='retry'."""
        engine = _make_engine()
        policy = _make_policy("retry", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=0, failure=_Failure())

        assert decision.reflection_prompt is None


# ---------------------------------------------------------------------------
# D-2 test C: reflect policy, attempt_seq >= max_attempts → exhausted path
# ---------------------------------------------------------------------------


class TestDecideExhaustedReflect:
    def test_reflect_action_at_exhaustion(self) -> None:
        """When attempt_seq >= max_attempts with on_exhausted='reflect', action='reflect'."""
        engine = _make_engine()
        policy = _make_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=3, failure=_Failure())

        assert decision.action == "reflect"

    def test_next_attempt_seq_is_none_at_exhaustion(self) -> None:
        """next_attempt_seq must be None when the budget is exhausted."""
        engine = _make_engine()
        policy = _make_policy("reflect", max_attempts=3)
        decision = engine._decide(policy, "t1", attempt_seq=3, failure=_Failure())

        assert decision.next_attempt_seq is None


# ---------------------------------------------------------------------------
# D-2 test D: stage_id propagated into reflection prompt
# ---------------------------------------------------------------------------


class TestDecideStageIdInPrompt:
    def test_stage_id_in_reflection_prompt(self) -> None:
        """stage_id='S3_build' must appear in the reflection_prompt."""
        engine = _make_engine()
        policy = _make_policy("reflect", max_attempts=5)
        decision = engine._decide(
            policy, "t1", attempt_seq=1, failure=_Failure(), stage_id="S3_build"
        )

        assert decision.reflection_prompt is not None
        assert "S3_build" in decision.reflection_prompt

    def test_stage_id_unknown_when_omitted(self) -> None:
        """When stage_id is not supplied, prompt falls back to 'unknown'."""
        engine = _make_engine()
        policy = _make_policy("reflect", max_attempts=5)
        decision = engine._decide(policy, "t1", attempt_seq=1, failure=_Failure())

        assert decision.reflection_prompt is not None
        assert "unknown" in decision.reflection_prompt
