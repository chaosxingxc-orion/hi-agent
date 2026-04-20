"""Cost optimization advisor for TRACE runtime operations.

This module provides rule-based recommendations that translate raw cost
telemetry into concrete optimization actions for skills, memory, and
knowledge retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CostOptimizationHint:
    """A concrete, machine-readable cost optimization recommendation."""

    code: str
    severity: str
    summary: str
    action: str


def recommend_cost_optimizations(
    *,
    run_count: int,
    avg_cost_per_run: float,
    per_model_breakdown: dict[str, float],
) -> list[CostOptimizationHint]:
    """Generate rule-based optimization hints from cost telemetry.

    Args:
        run_count: Number of runs included in the telemetry window.
        avg_cost_per_run: Average USD cost per run.
        per_model_breakdown: Model->USD spending map.

    Returns:
        A list of actionable optimization hints.
    """
    hints: list[CostOptimizationHint] = []
    if run_count <= 0:
        return hints

    heavy_models = _find_heavy_models(per_model_breakdown)
    if heavy_models:
        hints.append(
            CostOptimizationHint(
                code="model_mix_heavy",
                severity="high",
                summary=f"High-cost models dominate spend: {', '.join(heavy_models[:3])}.",
                action=(
                    "Route gather/retrieval stages to medium/light tiers first, "
                    "reserve strong tier for final synthesis and low-confidence cases."
                ),
            )
        )

    if avg_cost_per_run >= 0.50:
        hints.append(
            CostOptimizationHint(
                code="avg_run_cost_high",
                severity="high",
                summary=f"Average run cost is high (${avg_cost_per_run:.3f}/run).",
                action=(
                    "Tighten memory retrieval budget and enforce concise context packing "
                    "before high-tier calls."
                ),
            )
        )
    elif avg_cost_per_run >= 0.15:
        hints.append(
            CostOptimizationHint(
                code="avg_run_cost_moderate",
                severity="medium",
                summary=f"Average run cost is moderate (${avg_cost_per_run:.3f}/run).",
                action=(
                    "Promote successful challenger skills and prefer reusable skill paths "
                    "to reduce repeated exploratory calls."
                ),
            )
        )

    if run_count >= 20:
        hints.append(
            CostOptimizationHint(
                code="enable_continuous_evolve",
                severity="medium",
                summary="Sufficient run volume to enable continuous cost-quality optimization.",
                action=(
                    "Schedule periodic evolve cycles and track champion/challenger "
                    "wins with cost-per-success as a promotion metric."
                ),
            )
        )

    return hints


def _find_heavy_models(per_model_breakdown: dict[str, float]) -> list[str]:
    """Return model names that represent dominant cost share."""
    if not per_model_breakdown:
        return []
    total = sum(per_model_breakdown.values())
    if total <= 0:
        return []
    heavy: list[str] = []
    for model, cost in sorted(per_model_breakdown.items(), key=lambda kv: kv[1], reverse=True):
        share = cost / total
        if share >= 0.40 or cost >= 10.0:
            heavy.append(model)
    return heavy


def derive_tier_overrides(
    hints: list[CostOptimizationHint],
) -> dict[str, str]:
    """Convert high-severity cost hints to tier routing overrides.

    Returns a mapping of purpose-key -> recommended tier that callers
    can feed into ``TierRouter.apply_overrides()`` to automatically
    reduce spend without manual intervention.

    Keys use the same purpose vocabulary as ``TierRouter``:
    ``"gather"``, ``"retrieval"``, ``"synthesis"``, ``"evaluation"``.
    """
    overrides: dict[str, str] = {}
    for hint in hints:
        if hint.severity not in ("high",):
            continue
        if hint.code == "model_mix_heavy":
            # Offload cheap, broad passes to lighter tiers
            overrides.setdefault("gather", "medium")
            overrides.setdefault("retrieval", "light")
        elif hint.code == "avg_run_cost_high":
            # Aggressive downgrade for non-synthesis stages
            overrides["gather"] = "light"
            overrides.setdefault("retrieval", "light")
            overrides.setdefault("evaluation", "medium")
    return overrides


def hints_to_payload(hints: list[CostOptimizationHint]) -> list[dict[str, Any]]:
    """Convert hints to JSON-serializable dictionaries."""
    return [
        {
            "code": hint.code,
            "severity": hint.severity,
            "summary": hint.summary,
            "action": hint.action,
        }
        for hint in hints
    ]
