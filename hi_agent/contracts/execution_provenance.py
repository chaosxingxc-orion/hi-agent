"""Structured execution provenance for RunResult — HI-W1-D3-001.

W1 fills: contract_version, runtime_mode, mcp_transport, fallback_used,
fallback_reasons, evidence.heuristic_stage_count.
llm_mode / kernel_mode / capability_mode are "unknown" in W1 — filled in W2.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CONTRACT_VERSION = "2026-04-17"


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
    ) -> "ExecutionProvenance":
        """Aggregate provenance from stage execution summaries.

        W1 fills minimum set. llm_mode/kernel_mode/capability_mode filled in W2.

        Args:
            stage_summaries: list of dicts each with key "type" ("heuristic" or "real").
            runtime_context: dict with keys "runtime_mode", "mcp_transport".
        """
        heuristic_count = sum(1 for s in stage_summaries if s.get("type") == "heuristic")
        fallback_reasons: list[str] = []
        if heuristic_count > 0:
            fallback_reasons.append("heuristic_stages_present")

        return cls(
            contract_version=CONTRACT_VERSION,
            runtime_mode=runtime_context.get("runtime_mode", "dev-smoke"),
            llm_mode="unknown",
            kernel_mode="unknown",
            capability_mode="unknown",
            mcp_transport=runtime_context.get("mcp_transport", "not_wired"),
            fallback_used=heuristic_count > 0,
            fallback_reasons=fallback_reasons,
            evidence={"heuristic_stage_count": heuristic_count},
        )
