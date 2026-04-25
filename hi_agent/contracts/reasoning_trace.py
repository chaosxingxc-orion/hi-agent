"""TE-5: Platform reasoning trace schema for structured run introspection.

Each entry in a ReasoningTrace captures one observable reasoning event (thought,
plan, reflection, tool call, or tool result) produced during a run.  Entries are
persisted to <HI_AGENT_DATA_DIR>/traces/<run_id>.jsonl when the data dir is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningTraceEntry:
    """One observable reasoning event within a run stage.

    Attributes:
        run_id: The run this entry belongs to.
        stage_id: The stage within the run (e.g. "reflect", "plan").
        step: Monotonically increasing step index within the run.
        kind: Event kind — one of "thought" | "plan" | "reflection" |
              "tool_call" | "tool_result".
        content: Human-readable content of the event (may be truncated for
                 large tool outputs).
        metadata: Arbitrary structured metadata (model name, token counts, etc.).
        created_at: ISO-8601 UTC timestamp of entry creation.
    """

    run_id: str
    stage_id: str
    step: int
    kind: str  # "thought" | "plan" | "reflection" | "tool_call" | "tool_result"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""  # ISO8601


@dataclass
class ReasoningTrace:
    """Ordered collection of reasoning events for a single run.

    Attributes:
        run_id: The run these entries belong to.
        entries: Ordered list of ReasoningTraceEntry instances.
    """

    run_id: str
    entries: list[ReasoningTraceEntry] = field(default_factory=list)
