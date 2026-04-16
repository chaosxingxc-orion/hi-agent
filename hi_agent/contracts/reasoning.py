"""Reasoning trace storage contract — allows business layer to persist structured reasoning."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReasoningStep:
    """A single step in a structured reasoning trace.

    Business-layer stage handlers populate these; the platform stores them.
    """

    step_id: str
    stage_id: str
    action: str    # "route" | "evaluate" | "decide" | "reflect" | custom
    thought: str
    timestamp: str = ""


@dataclass
class ReasoningTrace:
    """A collection of reasoning steps for a single stage execution."""

    trace_id: str
    run_id: str
    stage_id: str
    steps: list[ReasoningStep] = field(default_factory=list)
