"""Structured execution provenance for RunResult — HI-W1-D3-001.

W1 fills: contract_version, runtime_mode, mcp_transport, fallback_used,
fallback_reasons, evidence.heuristic_stage_count.
llm_mode / kernel_mode / capability_mode are "unknown" in W1 — filled in W2.

W2-001 adds StageProvenance per stage; build_from_stages aggregates from those.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

CONTRACT_VERSION = "2026-04-17"

_logger = logging.getLogger(__name__)


# scope: process-internal — per-stage provenance value object
@dataclass(frozen=True)
class StageProvenance:
    """Per-stage provenance snapshot — HI-W2-001."""

    stage_id: str
    llm_mode: Literal["heuristic", "real", "disabled", "unknown"]
    capability_mode: Literal["sample", "profile", "mcp", "external", "unknown"]
    fallback_used: bool
    fallback_reasons: list[str]
    duration_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "fallback_reasons", sorted(set(self.fallback_reasons)))

    def to_dict(self) -> dict:
        return {
            "stage_id": self.stage_id,
            "llm_mode": self.llm_mode,
            "capability_mode": self.capability_mode,
            "fallback_used": self.fallback_used,
            "fallback_reasons": list(self.fallback_reasons),
            "duration_ms": self.duration_ms,
        }


# scope: process-internal — provenance value object aggregated into RunResult (which carries spine)
@dataclass(frozen=True)
class ExecutionProvenance:
    contract_version: str
    runtime_mode: Literal["dev-smoke", "local-real", "prod-real"]
    llm_mode: Literal["heuristic", "real", "disabled", "unknown"]
    kernel_mode: Literal["local-fsm", "http", "unknown"]
    capability_mode: Literal["sample", "profile", "mcp", "external", "mixed", "unknown"]
    mcp_transport: Literal["not_wired", "stdio", "sse", "http"]
    fallback_used: bool
    fallback_reasons: list[str]
    evidence: dict[str, int]
    experiment_artifacts: list[dict] = field(default_factory=list)
    # Each entry: {"uri": str, "sha256": str, "size": int, "mime": str}

    def __post_init__(self) -> None:
        # Deduplicate and sort fallback_reasons for stable comparison.
        object.__setattr__(self, "fallback_reasons", sorted(set(self.fallback_reasons)))

    def to_dict(self) -> dict:
        return {
            "contract_version": self.contract_version,
            "runtime_mode": self.runtime_mode,
            "llm_mode": self.llm_mode,
            "kernel_mode": self.kernel_mode,
            "capability_mode": self.capability_mode,
            "mcp_transport": self.mcp_transport,
            "fallback_used": self.fallback_used,
            "fallback_reasons": list(self.fallback_reasons),
            "evidence": dict(self.evidence),
        }

    @classmethod
    def build_from_stages(
        cls,
        stage_summaries: list[dict],
        runtime_context: dict,
    ) -> ExecutionProvenance:
        """Aggregate run-level provenance from per-stage StageProvenance objects.

        If stage has "provenance" key (StageProvenance), use it.
        If stage has "type" key only (W1 compat), treat type=="heuristic" as fallback.

        Args:
            stage_summaries: list of dicts; each may have "provenance" (StageProvenance)
                or legacy "type" key.
            runtime_context: dict with keys "runtime_mode", "mcp_transport".
        """
        stage_provs: list[StageProvenance] = []
        for s in stage_summaries:
            if "provenance" in s and isinstance(s["provenance"], StageProvenance):
                stage_provs.append(s["provenance"])
            elif s.get("type") == "heuristic":
                # W1 backward compat: synthesize a StageProvenance
                stage_provs.append(
                    StageProvenance(
                        stage_id=s.get("stage_id", "unknown"),
                        llm_mode="heuristic",
                        capability_mode="sample",
                        fallback_used=True,
                        fallback_reasons=["heuristic_stage"],
                        duration_ms=0,
                    )
                )
            else:
                if s:
                    _logger.warning("build_from_stages: unexpected stage shape %r — skipped", s)

        if not stage_provs:
            # No stage data — keep old W1 behavior
            heuristic_count = sum(1 for s in stage_summaries if s.get("type") == "heuristic")
            return cls(
                contract_version=CONTRACT_VERSION,
                runtime_mode=runtime_context.get("runtime_mode", "dev-smoke"),
                llm_mode="unknown",
                kernel_mode=runtime_context.get("kernel_mode", "unknown"),
                capability_mode="unknown",
                mcp_transport=runtime_context.get("mcp_transport", "not_wired"),
                fallback_used=heuristic_count > 0,
                fallback_reasons=["heuristic_stages_present"] if heuristic_count > 0 else [],
                evidence={"heuristic_stage_count": heuristic_count},
            )

        # Aggregate llm_mode
        llm_modes = {sp.llm_mode for sp in stage_provs}
        if llm_modes == {"real"}:
            agg_llm_mode: Literal["heuristic", "real", "disabled", "unknown"] = "real"
        elif llm_modes == {"heuristic"}:
            agg_llm_mode = "heuristic"
        elif llm_modes == {"disabled"}:
            agg_llm_mode = "disabled"
        elif llm_modes == {"unknown"} or llm_modes <= {"unknown", "disabled"}:
            # All stages are unknown (no capability provenance recorded) or disabled.
            # Do not assert "heuristic" — report truthfully as "unknown".
            agg_llm_mode = "unknown"
        elif "heuristic" in llm_modes:
            agg_llm_mode = "heuristic"  # at least one confirmed heuristic stage
        else:
            agg_llm_mode = "unknown"  # mixed real/unknown — cannot classify

        # Aggregate capability_mode
        cap_modes = {sp.capability_mode for sp in stage_provs}
        agg_cap_mode: Literal["sample", "profile", "mcp", "external", "mixed", "unknown"]
        if len(cap_modes) == 1:
            agg_cap_mode = cap_modes.pop()
        elif "mcp" in cap_modes:
            agg_cap_mode = "mcp"
        elif "external" in cap_modes:
            agg_cap_mode = "external"
        else:
            agg_cap_mode = "sample"  # default fallback

        fallback_used = any(sp.fallback_used for sp in stage_provs)
        all_reasons: list[str] = []
        for sp in stage_provs:
            all_reasons.extend(sp.fallback_reasons)

        heuristic_count = sum(1 for sp in stage_provs if sp.llm_mode == "heuristic")

        return cls(
            contract_version=CONTRACT_VERSION,
            runtime_mode=runtime_context.get("runtime_mode", "dev-smoke"),
            llm_mode=agg_llm_mode,
            kernel_mode=runtime_context.get("kernel_mode", "unknown"),
            capability_mode=agg_cap_mode,
            mcp_transport=runtime_context.get("mcp_transport", "not_wired"),
            fallback_used=fallback_used,
            fallback_reasons=all_reasons,
            evidence={"heuristic_stage_count": heuristic_count},
        )
