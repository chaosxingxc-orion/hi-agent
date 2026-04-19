"""Tests for centralized configuration and formal state machines."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from hi_agent.config.trace_config import TraceConfig
from hi_agent.config.builder import SystemBuilder
from hi_agent.state_machine.machine import InvalidTransition, StateMachine
from hi_agent.state_machine.definitions import (
    action_state_machine,
    branch_state_machine,
    review_state_machine,
    run_state_machine,
    stage_state_machine,
    wait_state_machine,
)


# ======================================================================
# TraceConfig tests
# ======================================================================


class TestTraceConfigDefaults:
    """TraceConfig should expose sensible defaults for every field."""

    def test_default_values(self) -> None:
        cfg = TraceConfig()
        assert cfg.max_stages == 10
        assert cfg.max_branches_per_stage == 5
        assert cfg.max_total_branches == 20
        assert cfg.max_actions_per_run == 100
        assert cfg.default_model == "gpt-4o"
        assert cfg.llm_timeout_seconds == 120
        assert cfg.route_confidence_threshold == 0.6
        assert cfg.server_port == 8080
        assert cfg.evolve_mode == "auto"

    def test_to_dict_round_trip(self) -> None:
        cfg = TraceConfig()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert d["max_stages"] == 10
        assert d["default_model"] == "gpt-4o"


class TestTraceConfigFromFile:
    """TraceConfig.from_file / save round-trip."""

    def test_save_and_load(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "cfg.json")
        original = TraceConfig(max_stages=42, server_port=9999)
        original.save(path)

        loaded = TraceConfig.from_file(path)
        assert loaded.max_stages == 42
        assert loaded.server_port == 9999
        # Untouched defaults preserved
        assert loaded.default_model == "gpt-4o"

    def test_from_file_ignores_unknown_keys(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "cfg.json")
        with open(path, "w") as f:
            json.dump({"max_stages": 7, "unknown_key": "ignored"}, f)
        loaded = TraceConfig.from_file(path)
        assert loaded.max_stages == 7
        assert not hasattr(loaded, "unknown_key")


class TestTraceConfigFromEnv:
    """TraceConfig.from_env reads HI_AGENT_ prefixed env vars."""

    def test_int_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HI_AGENT_MAX_STAGES", "15")
        cfg = TraceConfig.from_env()
        assert cfg.max_stages == 15

    def test_float_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HI_AGENT_ROUTE_CONFIDENCE_THRESHOLD", "0.9")
        cfg = TraceConfig.from_env()
        assert cfg.route_confidence_threshold == 0.9

    def test_evolve_mode_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HI_AGENT_EVOLVE_MODE", "off")
        cfg = TraceConfig.from_env()
        assert cfg.evolve_mode == "off"

    def test_str_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HI_AGENT_DEFAULT_MODEL", "claude-3")
        cfg = TraceConfig.from_env()
        assert cfg.default_model == "claude-3"

    def test_missing_env_uses_defaults(self) -> None:
        # Ensure no HI_AGENT_ vars are set for this test
        cfg = TraceConfig.from_env()
        assert cfg.max_stages == 10


# ======================================================================
# SystemBuilder tests
# ======================================================================


class TestSystemBuilder:
    """SystemBuilder creates all subsystems from config."""

    def test_build_executor(self) -> None:
        from hi_agent.contracts import TaskContract

        cfg = TraceConfig()
        builder = SystemBuilder(cfg)
        contract = TaskContract(
            task_id="t1",
            goal="test goal",
            constraints=[],
            acceptance_criteria=[],
        )
        executor = builder.build_executor(contract)
        assert executor is not None

    def test_build_orchestrator(self) -> None:
        cfg = TraceConfig()
        builder = SystemBuilder(cfg)
        orch = builder.build_orchestrator()
        assert orch is not None

    def test_build_server(self) -> None:
        cfg = TraceConfig(server_port=7777)
        builder = SystemBuilder(cfg)
        server = builder.build_server()
        assert server is not None
        assert server.server_address[1] == 7777

    def test_build_skill_registry(self) -> None:
        cfg = TraceConfig(skill_storage_dir="/tmp/test_skills")
        builder = SystemBuilder(cfg)
        reg = builder.build_skill_registry()
        assert reg is not None

    def test_build_episodic_store(self) -> None:
        cfg = TraceConfig()
        builder = SystemBuilder(cfg)
        store = builder.build_episodic_store()
        assert store is not None

    def test_build_watchdog(self) -> None:
        cfg = TraceConfig(watchdog_window_size=20)
        builder = SystemBuilder(cfg)
        wd = builder.build_watchdog()
        assert wd is not None

    def test_kernel_singleton(self) -> None:
        cfg = TraceConfig()
        builder = SystemBuilder(cfg)
        k1 = builder.build_kernel()
        k2 = builder.build_kernel()
        assert k1 is k2


# ======================================================================
# StateMachine core tests
# ======================================================================


class TestStateMachine:
    """Core StateMachine behaviour."""

    @staticmethod
    def _simple_machine() -> StateMachine:
        return StateMachine(
            name="test",
            states={"a", "b", "c"},
            initial="a",
            transitions={"a": {"b"}, "b": {"c"}},
            terminal={"c"},
        )

    def test_initial_state(self) -> None:
        sm = self._simple_machine()
        assert sm.current == "a"
        assert not sm.is_terminal

    def test_valid_transition(self) -> None:
        sm = self._simple_machine()
        sm.transition("b")
        assert sm.current == "b"

    def test_invalid_transition_raises(self) -> None:
        sm = self._simple_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("c")  # a -> c not allowed

    def test_terminal_detection(self) -> None:
        sm = self._simple_machine()
        sm.transition("b")
        sm.transition("c")
        assert sm.is_terminal

    def test_history_tracking(self) -> None:
        sm = self._simple_machine()
        sm.transition("b")
        sm.transition("c")
        assert sm.history == [("a", "b", "test"), ("b", "c", "test")]

    def test_available_transitions(self) -> None:
        sm = self._simple_machine()
        assert sm.available_transitions() == {"b"}

    def test_can_transition(self) -> None:
        sm = self._simple_machine()
        assert sm.can_transition("b") is True
        assert sm.can_transition("c") is False

    def test_callback_on_transition(self) -> None:
        sm = self._simple_machine()
        calls: list[tuple[str, str]] = []
        sm.on_transition(lambda f, t: calls.append((f, t)))
        sm.transition("b")
        assert calls == [("a", "b")]

    def test_transition_to_unknown_state(self) -> None:
        sm = self._simple_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("z")

    def test_invalid_initial_state_raises(self) -> None:
        with pytest.raises(ValueError):
            StateMachine(
                name="bad",
                states={"a", "b"},
                initial="x",
                transitions={},
            )


# ======================================================================
# TRACE state machine definition tests
# ======================================================================


class TestRunStateMachine:
    """Run lifecycle: created->active->waiting->recovering->completed/failed/aborted."""

    def test_happy_path(self) -> None:
        sm = run_state_machine()
        assert sm.current == "created"
        sm.transition("active")
        sm.transition("completed")
        assert sm.is_terminal

    def test_waiting_and_recovery(self) -> None:
        sm = run_state_machine()
        sm.transition("active")
        sm.transition("waiting")
        sm.transition("recovering")
        sm.transition("active")
        sm.transition("completed")
        assert sm.is_terminal

    def test_abort_from_active(self) -> None:
        sm = run_state_machine()
        sm.transition("active")
        sm.transition("aborted")
        assert sm.is_terminal

    def test_invalid_created_to_completed(self) -> None:
        sm = run_state_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("completed")


class TestStageStateMachine:
    """Stage lifecycle: pending->active->blocked->completed/failed."""

    def test_happy_path(self) -> None:
        sm = stage_state_machine()
        sm.transition("active")
        sm.transition("completed")
        assert sm.is_terminal

    def test_blocked_and_resume(self) -> None:
        sm = stage_state_machine()
        sm.transition("active")
        sm.transition("blocked")
        sm.transition("active")
        sm.transition("completed")
        assert sm.is_terminal

    def test_invalid_pending_to_completed(self) -> None:
        sm = stage_state_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("completed")


class TestBranchStateMachine:
    """Branch lifecycle: proposed->active->pruned/waiting/succeeded/failed."""

    def test_happy_path(self) -> None:
        sm = branch_state_machine()
        sm.transition("active")
        sm.transition("succeeded")
        assert sm.is_terminal

    def test_waiting_and_resume(self) -> None:
        sm = branch_state_machine()
        sm.transition("active")
        sm.transition("waiting")
        sm.transition("active")
        sm.transition("succeeded")
        assert sm.is_terminal

    def test_prune_from_proposed(self) -> None:
        sm = branch_state_machine()
        sm.transition("pruned")
        assert sm.is_terminal

    def test_invalid_proposed_to_succeeded(self) -> None:
        sm = branch_state_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("succeeded")


class TestActionStateMachine:
    """Action lifecycle: prepared->dispatched->acknowledged->succeeded/effect_unknown/failed/compensated."""

    def test_happy_path(self) -> None:
        sm = action_state_machine()
        sm.transition("dispatched")
        sm.transition("acknowledged")
        sm.transition("succeeded")
        assert sm.is_terminal

    def test_dispatch_to_failed(self) -> None:
        sm = action_state_machine()
        sm.transition("dispatched")
        sm.transition("failed")
        assert sm.is_terminal

    def test_compensated(self) -> None:
        sm = action_state_machine()
        sm.transition("dispatched")
        sm.transition("acknowledged")
        sm.transition("compensated")
        assert sm.is_terminal

    def test_invalid_prepared_to_acknowledged(self) -> None:
        sm = action_state_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("acknowledged")


class TestWaitStateMachine:
    """Wait semantics: none->external_callback/human_review/scheduled_resume->none."""

    def test_external_callback_round_trip(self) -> None:
        sm = wait_state_machine()
        sm.transition("external_callback")
        sm.transition("none")
        assert sm.current == "none"

    def test_human_review_round_trip(self) -> None:
        sm = wait_state_machine()
        sm.transition("human_review")
        sm.transition("none")
        assert sm.current == "none"

    def test_scheduled_resume_round_trip(self) -> None:
        sm = wait_state_machine()
        sm.transition("scheduled_resume")
        sm.transition("none")
        assert sm.current == "none"

    def test_no_terminal_states(self) -> None:
        sm = wait_state_machine()
        assert not sm.is_terminal
        sm.transition("external_callback")
        assert not sm.is_terminal

    def test_invalid_callback_to_review(self) -> None:
        sm = wait_state_machine()
        sm.transition("external_callback")
        with pytest.raises(InvalidTransition):
            sm.transition("human_review")


class TestReviewStateMachine:
    """Review lifecycle: not_required->requested->in_review->approved/rejected."""

    def test_approved(self) -> None:
        sm = review_state_machine()
        sm.transition("requested")
        sm.transition("in_review")
        sm.transition("approved")
        assert sm.is_terminal

    def test_rejected(self) -> None:
        sm = review_state_machine()
        sm.transition("requested")
        sm.transition("in_review")
        sm.transition("rejected")
        assert sm.is_terminal

    def test_invalid_skip_to_in_review(self) -> None:
        sm = review_state_machine()
        with pytest.raises(InvalidTransition):
            sm.transition("in_review")

    def test_invalid_requested_to_approved(self) -> None:
        sm = review_state_machine()
        sm.transition("requested")
        with pytest.raises(InvalidTransition):
            sm.transition("approved")
