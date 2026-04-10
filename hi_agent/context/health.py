"""Context health monitoring and diagnostics.

Tracks context utilization over time, compression events,
section growth patterns, and cost of compression.
"""

from __future__ import annotations

import time
from typing import Any


class ContextMonitor:
    """Monitors context health across multiple LLM calls.

    Tracks: utilization over time, compression events,
    section growth patterns, cost of compression.
    """

    def __init__(self) -> None:
        """Initialize ContextMonitor."""
        self._snapshots: list[dict[str, Any]] = []
        self._compression_events: list[dict[str, Any]] = []

    def record_snapshot(self, snapshot: Any) -> None:
        """Record a context snapshot for trending.

        Parameters
        ----------
        snapshot:
            A :class:`ContextSnapshot` instance.
        """
        entry: dict[str, Any] = {
            "timestamp": time.time(),
            "total_tokens": snapshot.total_tokens,
            "budget_tokens": snapshot.budget_tokens,
            "utilization_pct": snapshot.utilization_pct,
            "health": (
                snapshot.health.value
                if hasattr(snapshot.health, "value")
                else str(snapshot.health)
            ),
            "compressions_applied": snapshot.compressions_applied,
            "purpose": snapshot.purpose,
            "section_tokens": {
                s.name: s.tokens for s in snapshot.sections
            },
        }
        self._snapshots.append(entry)

    def record_compression(
        self,
        method: str,
        tokens_before: int,
        tokens_after: int,
        cost_tokens: int = 0,
    ) -> None:
        """Record a compression event.

        Parameters
        ----------
        method:
            One of ``"snip"``, ``"compact"``, ``"trim"``.
        tokens_before:
            Token count before compression.
        tokens_after:
            Token count after compression.
        cost_tokens:
            Additional tokens consumed by the compression itself
            (e.g. LLM call for summarization).
        """
        self._compression_events.append({
            "timestamp": time.time(),
            "method": method,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": tokens_before - tokens_after,
            "cost_tokens": cost_tokens,
        })

    def get_trend(self, last_n: int = 10) -> dict[str, Any]:
        """Return utilization trend over last N snapshots.

        Returns dict with: avg_utilization, growth_rate,
        compression_frequency, and per-snapshot details.
        """
        recent = self._snapshots[-last_n:] if self._snapshots else []
        if not recent:
            return {
                "avg_utilization": 0.0,
                "growth_rate": 0.0,
                "compression_frequency": 0.0,
                "snapshot_count": 0,
            }

        utilizations = [s["utilization_pct"] for s in recent]
        avg_util = sum(utilizations) / len(utilizations)

        # Growth rate: change in utilization between first and last
        growth_rate = utilizations[-1] - utilizations[0] if len(utilizations) >= 2 else 0.0

        # Compression frequency: fraction of snapshots that had compression
        compressions = sum(
            1 for s in recent if s.get("compressions_applied", 0) > 0
        )
        compression_freq = compressions / len(recent) if recent else 0.0

        return {
            "avg_utilization": avg_util,
            "growth_rate": growth_rate,
            "compression_frequency": compression_freq,
            "snapshot_count": len(recent),
        }

    def get_recommendations(self) -> list[str]:
        """Based on trends, suggest budget adjustments.

        Analyzes recent snapshots and section token usage to produce
        actionable recommendations.
        """
        recommendations: list[str] = []
        trend = self.get_trend()

        if trend["snapshot_count"] == 0:
            return ["No snapshots recorded yet."]

        # High utilization
        if trend["avg_utilization"] > 0.85:
            recommendations.append(
                "Average utilization above 85%. Consider increasing total "
                "context window or reducing section budgets."
            )

        # Rapidly growing
        if trend["growth_rate"] > 0.15:
            recommendations.append(
                "Utilization growing rapidly. History may need more "
                "frequent compression."
            )

        # Frequent compression
        if trend["compression_frequency"] > 0.5:
            recommendations.append(
                "Compression triggered in >50% of calls. Consider "
                "reducing history budget or increasing total window."
            )

        # Section-level analysis
        if self._snapshots:
            latest = self._snapshots[-1]
            section_tokens = latest.get("section_tokens", {})
            budget_tokens = latest.get("budget_tokens", 1)

            # Find largest section
            if section_tokens:
                largest_name = max(section_tokens, key=section_tokens.get)
                largest_pct = section_tokens[largest_name] / budget_tokens
                if largest_pct > 0.4:
                    recommendations.append(
                        f"Section '{largest_name}' uses {largest_pct:.0%} of "
                        f"total budget. Consider reducing its allocation."
                    )

        if not recommendations:
            recommendations.append("Context budget is well balanced.")

        return recommendations

    def to_summary(self) -> dict[str, Any]:
        """Return full monitoring summary."""
        trend = self.get_trend()
        total_compressions = len(self._compression_events)
        tokens_saved = sum(
            e["tokens_saved"] for e in self._compression_events
        )
        compression_cost = sum(
            e["cost_tokens"] for e in self._compression_events
        )

        return {
            "total_snapshots": len(self._snapshots),
            "total_compressions": total_compressions,
            "total_tokens_saved": tokens_saved,
            "total_compression_cost": compression_cost,
            "trend": trend,
            "recommendations": self.get_recommendations(),
        }

    @property
    def snapshot_count(self) -> int:
        """Number of recorded snapshots."""
        return len(self._snapshots)

    @property
    def compression_event_count(self) -> int:
        """Number of recorded compression events."""
        return len(self._compression_events)
