"""Rule 15 Volces operator-shape gate profile.

Minimal single-stage, live-LLM-backed profile used by
``scripts/rule15_volces_gate.py`` (default ``--profile-id=rule15_volces``).

Design:
- Exactly one stage (``rule15_probe``) that invokes the LLM gateway via the
  generic ``make_llm_capability_handler`` factory.  This guarantees a real
  outgoing request so Rule 15's ``llm_fallback_count == 0`` invariant can be
  honestly verified.
- Deterministic acceptance: the capability handler returns ``success=True``
  for any non-empty LLM response.  No content-quality assertions.
- No tree, no sub-run, no gate, no reflection — the profile exists solely to
  probe that the platform can carry a run end-to-end against live volces.

Usage::

    from hi_agent.profiles.rule15_volces import (
        build_rule15_volces_profile,
        register_rule15_probe_capability,
        RULE15_PROBE_CAPABILITY,
    )

    builder = SystemBuilder(...)
    register_rule15_probe_capability(
        builder.build_capability_registry(),
        llm_gateway=builder.build_llm_gateway(),
    )
    builder.register_profile(build_rule15_volces_profile())
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.trajectory.stage_graph import StageGraph

if TYPE_CHECKING:
    from hi_agent.capability.registry import CapabilityRegistry
    from hi_agent.llm.protocol import LLMGateway


RULE15_PROBE_CAPABILITY = "rule15_probe_capability"
"""Capability name bound to the Rule 15 probe stage."""

RULE15_PROBE_STAGE = "rule15_probe"
"""Single stage id for the Rule 15 probe profile."""

_SYSTEM_PROMPT = (
    "You are a minimal probe. Reply with the single word: OK. "
    'Output JSON: {"output": "OK", "evidence": ["probe"], "score": 1.0, "done": true}'
)


def _build_stage_graph() -> StageGraph:
    """Return a StageGraph containing exactly one stage with no outgoing edges."""
    g = StageGraph()
    g.transitions.setdefault(RULE15_PROBE_STAGE, set())
    return g


def build_rule15_volces_profile() -> ProfileSpec:
    """Return the ProfileSpec for the Rule 15 Volces operator-shape gate."""
    return ProfileSpec(
        profile_id="rule15_volces",
        display_name="Rule 15 Volces Operator-Shape Gate",
        description=(
            "Minimal live-LLM-backed single-stage profile for the Rule 15 gate. "
            "Invokes rule15_probe_capability once; deterministic acceptance "
            "(any non-empty LLM response is accepted)."
        ),
        required_capabilities=[RULE15_PROBE_CAPABILITY],
        stage_actions={RULE15_PROBE_STAGE: RULE15_PROBE_CAPABILITY},
        stage_graph_factory=_build_stage_graph,
    )


def register_rule15_probe_capability(
    registry: CapabilityRegistry,
    *,
    llm_gateway: LLMGateway | None,
) -> None:
    """Register ``rule15_probe_capability`` into *registry* if not already present.

    The handler is built via :func:`make_llm_capability_handler` so it invokes
    the real LLM gateway when one is wired.  Idempotent: silently returns if
    the capability is already registered.
    """
    from hi_agent.capability.defaults import make_llm_capability_handler
    from hi_agent.capability.registry import CapabilitySpec

    if hasattr(registry, "list_names") and RULE15_PROBE_CAPABILITY in registry.list_names():
        return

    handler = make_llm_capability_handler(
        RULE15_PROBE_CAPABILITY,
        _SYSTEM_PROMPT,
        llm_gateway,
    )
    registry.register(
        CapabilitySpec(
            name=RULE15_PROBE_CAPABILITY,
            handler=handler,
            description="Rule 15 operator-shape probe: single minimal LLM call.",
        )
    )
