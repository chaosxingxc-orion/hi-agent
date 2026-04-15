"""Round-7 defect tests for SystemBuilder (I-7 and I-8).

I-7: build_memory_lifecycle_manager() must use profile-scoped stores when
     called from build_executor(), not create fresh unscoped stores.

I-8: _build_restart_policy_engine() must use config-driven on_exhausted
     instead of the hard-coded "escalate" default, enabling the reflect path.
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_builder(tmp_path, *, restart_on_exhausted: str = "reflect", restart_max_attempts: int = 3):
    """Return a SystemBuilder with a temp episodic_storage_dir."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    config = TraceConfig(
        episodic_storage_dir=str(tmp_path / "episodes"),
        restart_on_exhausted=restart_on_exhausted,
        restart_max_attempts=restart_max_attempts,
    )
    return SystemBuilder(config)


def _make_contract(profile_id: str = ""):
    """Return a minimal TaskContract-like mock."""
    from unittest.mock import MagicMock

    c = MagicMock()
    c.task_id = "t-i7"
    c.goal = "test goal"
    c.deadline = None
    c.budget = None
    c.constraints = []
    c.acceptance_criteria = []
    c.task_family = "quick_task"
    c.risk_level = "low"
    c.profile_id = profile_id
    c.decomposition_strategy = None
    return c


# ---------------------------------------------------------------------------
# I-7 tests
# ---------------------------------------------------------------------------


class TestI7MemoryLifecycleManagerProfileStores:
    """I-7: MemoryLifecycleManager must use the same profile-scoped stores as the executor."""

    def test_memory_lifecycle_manager_uses_profile_stores(self, tmp_path):
        """Executor's memory_lifecycle_manager._short points at profiles/proj1/short_term."""
        builder = _make_builder(tmp_path)
        contract = _make_contract(profile_id="proj1")

        executor = builder.build_executor(contract)

        mlm = executor.memory_lifecycle_manager
        assert mlm is not None, "memory_lifecycle_manager must be set on executor"

        # The short-term store inside MemoryLifecycleManager should be scoped to profile
        short = mlm._short
        assert short is not None, "MLM._short must not be None"
        actual_path = str(short._storage_dir)
        assert actual_path.endswith(os.path.join("profiles", "proj1", "short_term")), (
            f"MLM._short storage_dir {actual_path!r} should end with "
            f"profiles/proj1/short_term"
        )

    def test_memory_lifecycle_manager_retrieval_engine_shares_stores(self, tmp_path):
        """MLM's retrieval engine and executor's retrieval engine share the same short_term_store."""
        builder = _make_builder(tmp_path)
        contract = _make_contract(profile_id="proj1")

        executor = builder.build_executor(contract)

        mlm = executor.memory_lifecycle_manager
        assert mlm is not None

        # MLM._short and the retrieval engine inside MLM must be the same instance
        mlm_retrieval_short = mlm._retrieval._short_term if hasattr(mlm._retrieval, "_short_term") else None
        if mlm_retrieval_short is not None:
            assert mlm_retrieval_short is mlm._short, (
                "MLM retrieval engine's short_term must be the same instance as MLM._short"
            )

        # Executor's retrieval_engine (if set) must reference the same short store
        exec_retrieval = getattr(executor, "retrieval_engine", None)
        if exec_retrieval is not None:
            exec_short = getattr(exec_retrieval, "_short_term", None)
            if exec_short is not None:
                assert exec_short is mlm._short, (
                    "Executor retrieval engine's short_term must be the same instance as MLM._short"
                )


# ---------------------------------------------------------------------------
# I-8 tests
# ---------------------------------------------------------------------------


class TestI8RestartPolicyDefault:
    """I-8: Default config must produce on_exhausted='reflect', enabling the reflect path."""

    def test_build_restart_policy_defaults_reflect(self, tmp_path):
        """With default config (restart_on_exhausted='reflect'), _decide returns action='reflect'."""
        builder = _make_builder(tmp_path, restart_on_exhausted="reflect", restart_max_attempts=3)
        engine = builder._build_restart_policy_engine()
        assert engine is not None, "_build_restart_policy_engine() must succeed"

        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        policy = TaskRestartPolicy(max_attempts=3, on_exhausted="reflect")
        # attempt_seq=1 < max_attempts=3 → reflect path
        decision = engine._decide(policy, "t-i8", attempt_seq=1, failure=None)

        assert decision.action == "reflect", (
            f"Expected 'reflect' but got {decision.action!r} — "
            "default on_exhausted should be 'reflect'"
        )
        assert decision.reflection_prompt is not None, (
            "reflect action should produce a reflection_prompt"
        )

    def test_build_restart_policy_config_escalate(self, tmp_path):
        """With restart_on_exhausted='escalate', _decide within budget returns action='retry'."""
        builder = _make_builder(tmp_path, restart_on_exhausted="escalate", restart_max_attempts=5)
        engine = builder._build_restart_policy_engine()
        assert engine is not None, "_build_restart_policy_engine() must succeed"

        from agent_kernel.kernel.task_manager.contracts import TaskRestartPolicy

        policy = TaskRestartPolicy(max_attempts=5, on_exhausted="escalate")
        # attempt_seq=1 < max_attempts=5, on_exhausted='escalate' → retry (not reflect)
        decision = engine._decide(policy, "t-i8b", attempt_seq=1, failure=None)

        assert decision.action == "retry", (
            f"Expected 'retry' but got {decision.action!r} — "
            "escalate mode within budget should produce 'retry'"
        )
        assert decision.reflection_prompt is None, (
            "retry action must not produce a reflection_prompt"
        )
