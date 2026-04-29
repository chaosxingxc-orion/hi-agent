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
        tenant_id: Spine — the tenant this entry was produced under.
        user_id: Spine — the user this entry was produced for.
        session_id: Spine — the session this entry belongs to.
        project_id: Spine — the project this entry was produced for.

    Spine fields default to empty strings so JSONL files written before
    the spine was added remain round-trippable through ``asdict``.
    """

    run_id: str
    stage_id: str
    step: int
    kind: str  # "thought" | "plan" | "reflection" | "tool_call" | "tool_result"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""  # ISO8601
    tenant_id: str = ""  # scope: process-internal — JSONL back-compat; populated from exec_ctx
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""


@dataclass
class ReasoningTrace:
    """Ordered collection of reasoning events for a single run.

    Attributes:
        run_id: The run these entries belong to.
        entries: Ordered list of ReasoningTraceEntry instances.
        tenant_id: Spine — the tenant this trace was produced under.
        user_id: Spine — the user this trace was produced for.
        session_id: Spine — the session this trace belongs to.
        project_id: Spine — the project this trace was produced for.

    Spine fields default to empty strings to preserve back-compat with
    legacy traces persisted before the spine was added.
    """

    run_id: str
    entries: list[ReasoningTraceEntry] = field(default_factory=list)
    tenant_id: str = ""  # scope: process-internal — JSONL back-compat; populated from exec_ctx
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""
