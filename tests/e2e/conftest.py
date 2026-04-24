"""Shared fixtures for the PI-A..PI-E E2E suite.

Design constraints (CLAUDE.md):
  * Rule 7 — Three-Layer Testing: these are Layer-3 E2E tests.  They drive
    through the public ``RunExecutor`` interface with real subsystems.
    No internal mocking.
  * Rule 13 — Scope: every ``TaskContract`` carries a non-empty
    ``profile_id``; ``build_executor`` resolves it against the
    ``ProfileRegistry`` registered in the same builder.
  * Rule 14 — Fallback signals: tests inspect ``result.fallback_events``
    rather than asserting on internal booleans.
  * Rule 17 — Downstream Contract Alignment: the shape of these tests
    mirrors what downstream (PM2 + MaaS LLM) actually runs in production.

Two executor-build paths
------------------------

The suite uses two honest paths to build a real ``RunExecutor``:

1. ``build_systembuilder_executor`` — the full production wiring path via
   ``SystemBuilder.build_executor`` (Rule 13 required profile_id, real
   harness, real governance).  Used when the test can observe the mechanism
   through public ``RunResult`` fields alone (PI-A).

2. ``build_direct_executor`` — ``RunExecutor(...)`` with an explicit
   ``invoker``, ``stage_graph``, ``restart_policy_engine``, and
   ``delegation_manager`` parameters.  This is the same production-parity
   path used by ``tests/integration/test_journeys.py`` (journeys 3, 5, 9).
   It is required for PI-B / PI-C / PI-D / PI-E because the only honest
   way to deterministically inject a *flaky* capability or a *gate* at a
   specific stage is at the capability / executor boundary.  The runner,
   stage orchestrator, restart policy engine, delegation manager, and
   acceptance policy all run as real code — only the *capability handler*
   itself is a plain Python function (which, per Rule 7, is allowed —
   capabilities are the external boundary).

LLM mode selection
------------------

* ``HI_AGENT_LLM_MODE=real`` **plus** at least one of
  ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` / ``VOLCE_API_KEY`` →
  real-LLM mode.  Tests that *require* a real LLM run in this mode.
* Otherwise → heuristic mode.  The ``CognitionBuilder`` returns
  ``LLMGateway=None`` in dev mode and the runtime falls back to the
  deterministic heuristic path.  ``HI_AGENT_ALLOW_HEURISTIC_FALLBACK=1``
  is set at module import so prod-only code paths degrade cleanly.

The gateway-sharing regression test deliberately does NOT gate on the real
LLM — it is reproducing the 04-22 event-loop-lifetime defect which is
independent of provider identity.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from tests.helpers.live_llm_config import LiveLLMConfig, load_live_llm_config

# Allow heuristic-only capability execution when no LLM is wired.  This must
# be set before any hi_agent module imports the capability-defaults path.
os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")

from hi_agent.capability.registry import CapabilitySpec
from hi_agent.config.builder import SystemBuilder
from hi_agent.contracts.task import TaskContract
from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.trajectory.stage_graph import StageGraph

# ---------------------------------------------------------------------------
# Environment-driven mode selection
# ---------------------------------------------------------------------------


REAL_LLM_CONFIG = load_live_llm_config()
"""Module-level live config snapshot for cheap import-time checks."""

REAL_LLM_AVAILABLE = REAL_LLM_CONFIG.live_enabled
"""Module-level flag so test modules can use it in ``pytest.mark.skipif``."""


@pytest.fixture
def llm_mode() -> str:
    """Return ``"real"`` when a real LLM is wired, otherwise ``"heuristic"``."""
    return "real" if REAL_LLM_AVAILABLE else "heuristic"


@pytest.fixture
def live_llm_config() -> LiveLLMConfig:
    """Return the resolved live Volces config or skip when it is unavailable."""
    cfg = load_live_llm_config()
    if not cfg.live_enabled:
        pytest.skip("live LLM config unavailable")
    return cfg


@pytest.fixture
def volces_async_gateway(live_llm_config: LiveLLMConfig):
    """Return a real async HTTPGateway wired to the Volces endpoint."""
    from hi_agent.llm.http_gateway import HTTPGateway
    from hi_agent.runtime.sync_bridge import get_bridge

    gateway = HTTPGateway(
        base_url=live_llm_config.base_url,
        api_key=live_llm_config.api_key,
        timeout=live_llm_config.timeout_seconds,
        default_model=live_llm_config.default_model,
        max_retries=live_llm_config.max_retries,
        retry_base_seconds=1.0,
    )
    try:
        yield gateway
    finally:
        get_bridge().call_sync(gateway.aclose())


# ---------------------------------------------------------------------------
# Default capability handler — real Python function (no mocks).
# ---------------------------------------------------------------------------


def default_success_handler(payload: dict) -> dict:
    """Minimal successful capability handler used by the SystemBuilder path."""
    stage = payload.get("stage_id", "unknown")
    return {
        "success": True,
        "score": 1.0,
        "result": f"analyze:{stage}",
        "evidence_hash": f"ev_analyze_{stage}",
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def profile_id_for_test() -> str:
    """Unique profile_id per test — satisfies Rule 13 (ID uniqueness)."""
    return f"e2e_pi_{uuid.uuid4().hex[:8]}"


def _make_linear_stage_graph(stages: tuple[str, ...]) -> StageGraph:
    g = StageGraph()
    prev = None
    for s in stages:
        if prev is not None:
            g.add_edge(prev, s)
        prev = s
    return g


def make_linear_profile(
    profile_id: str,
    stages: tuple[str, ...],
    capability: str = "pi_analyze",
) -> ProfileSpec:
    """Build a ProfileSpec whose stage_graph is a linear chain of *stages*."""
    return ProfileSpec(
        profile_id=profile_id,
        display_name=f"E2E profile {profile_id}",
        description="Linear multistage profile for E2E tests",
        required_capabilities=list({capability}),
        stage_actions=dict.fromkeys(stages, capability),
        stage_graph_factory=lambda: _make_linear_stage_graph(stages),
    )


def make_contract(
    profile_id: str,
    goal: str,
    *,
    task_id: str | None = None,
    acceptance_criteria: list[str] | None = None,
) -> TaskContract:
    """Build a TaskContract with a test-scoped ``profile_id`` and ``task_id``."""
    return TaskContract(
        task_id=task_id or f"e2e-{profile_id}-{uuid.uuid4().hex[:6]}",
        goal=goal,
        profile_id=profile_id,
        task_family="quick_task",
        acceptance_criteria=list(acceptance_criteria or []),
    )


# ---------------------------------------------------------------------------
# Path A: SystemBuilder.build_executor (full production wiring)
# ---------------------------------------------------------------------------


@pytest.fixture
def builder_with_capabilities() -> Iterator[SystemBuilder]:
    """SystemBuilder with a single real ``pi_analyze`` capability handler."""
    builder = SystemBuilder()
    registry = builder.build_capability_registry()
    if "pi_analyze" not in registry.list_names():
        registry.register(
            CapabilitySpec(
                name="pi_analyze",
                handler=default_success_handler,
                description="E2E default success handler.",
            )
        )
    yield builder


# ---------------------------------------------------------------------------
# Path B: direct RunExecutor with a real in-process kernel and explicit
# invoker.  This is the production-parity path used by
# tests/integration/test_journeys.py for PI-B / PI-C / PI-D / PI-E.
# ---------------------------------------------------------------------------


def make_mock_kernel():
    """Return a ``MockKernel`` backed by the real agent-kernel LocalFSM."""
    from tests.helpers.kernel_adapter_fixture import MockKernel

    return MockKernel(strict_mode=False)


__all__ = [
    "REAL_LLM_AVAILABLE",
    "REAL_LLM_CONFIG",
    "builder_with_capabilities",
    "default_success_handler",
    "live_llm_config",
    "llm_mode",
    "make_contract",
    "make_linear_profile",
    "make_mock_kernel",
    "profile_id_for_test",
    "volces_async_gateway",
]
