"""PI-A E2E — Multistage TRACE (3-stage linear plan).

Pattern:
  * ProfileSpec declares a 3-stage linear graph ``s1 -> s2 -> s3``.
  * ``SystemBuilder.build_executor`` wires the full production path.
  * A single real capability handler satisfies all three stages.
  * Assertions are on observable outputs only (Rule 7): final status,
    per-stage records, fallback_events.
"""

from __future__ import annotations

import os

import pytest

from tests.e2e.conftest import REAL_LLM_AVAILABLE, make_contract, make_linear_profile

# Heuristic mode is allowed for this shape — pi_analyze is deterministic.
# We set the env var at import time so any test that ends up in the prod
# capability path can fall back cleanly.
os.environ.setdefault("HI_AGENT_ALLOW_HEURISTIC_FALLBACK", "1")


@pytest.mark.integration
def test_pi_a_three_stage_linear(
    builder_with_capabilities,
    profile_id_for_test: str,
) -> None:
    """PI-A: a 3-stage linear plan runs to completion with all stages executed."""
    stages = ("pi_a_s1", "pi_a_s2", "pi_a_s3")
    builder = builder_with_capabilities
    builder.register_profile(
        make_linear_profile(profile_id_for_test, stages, capability="pi_analyze")
    )

    contract = make_contract(profile_id_for_test, goal="PI-A multistage linear run")
    executor = builder.build_executor(contract)
    result = executor.execute()

    # Rule 7 — assert on observable outputs, not internal flags.
    assert result.status == "completed", (
        f"PI-A expected completed, got {result.status!r}: error={result.error!r}"
    )

    executed = [s.get("stage_id") for s in result.stages]
    for stage in stages:
        assert stage in executed, f"stage {stage!r} missing from result.stages={executed!r}"
    assert executed.index(stages[0]) < executed.index(stages[1]) < executed.index(stages[2]), (
        f"stages ran out of order: {executed!r}"
    )

    # Rule 14 — real-LLM mode must produce zero heuristic fallbacks.
    if REAL_LLM_AVAILABLE:
        assert result.fallback_events == [], (
            f"real-mode PI-A must not emit fallback events; got {result.fallback_events!r}"
        )
