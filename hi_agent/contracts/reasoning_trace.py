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

    JSONL back-compat: ``tenant_id`` / ``user_id`` / ``session_id`` /
    ``project_id`` default to empty strings so files written before the
    spine was added remain round-trippable through ``asdict``. The
    posture-aware ``__post_init__`` enforces ``run_id`` / ``stage_id`` /
    ``kind`` (the entry-shape spine) under research/prod posture.
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

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness at construction.

        ``run_id`` / ``stage_id`` / ``kind`` are required identity fields
        for every entry: a JSONL row that cannot answer "which run, which
        stage, what kind of event" is unattributable. Under research/prod
        posture missing fields raise ``SpineCompletenessError``; under dev
        posture the gap is logged so local tooling and the JSONL back-compat
        path keep working.
        """
        from hi_agent.config.posture import Posture
        from hi_agent.contracts.reasoning import SpineCompletenessError

        posture = Posture.from_env()
        missing: list[str] = []
        if not self.run_id:
            missing.append("run_id")
        if not self.stage_id:
            missing.append("stage_id")
        if not self.kind:
            missing.append("kind")
        if not missing:
            return
        if posture.is_strict:
            raise SpineCompletenessError(
                "ReasoningTraceEntry constructed without required spine fields "
                f"under posture={posture.value}: missing={missing}. "
                "Populate at the construction site (Rule 12)."
            )
        import logging
        logging.getLogger("hi_agent.contracts.reasoning_trace").warning(
            "reasoning_trace_entry_spine_incomplete: missing=%s posture=%s; "
            "would fail-closed under research/prod. (W35-T1)",
            missing,
            posture.value,
        )


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
    legacy traces persisted before the spine was added. The posture-aware
    ``__post_init__`` enforces ``run_id`` under research/prod posture.
    """

    run_id: str
    entries: list[ReasoningTraceEntry] = field(default_factory=list)
    tenant_id: str = ""  # scope: process-internal — JSONL back-compat; populated from exec_ctx
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""

    def __post_init__(self) -> None:
        """W35-T1: validate Rule 12 spine completeness at construction.

        Under research/prod posture every legacy ReasoningTrace MUST carry a
        non-empty ``run_id``. Under dev posture the constraint is relaxed
        to a warning to preserve JSONL back-compat for legacy files.
        """
        from hi_agent.config.posture import Posture
        from hi_agent.contracts.reasoning import SpineCompletenessError

        posture = Posture.from_env()
        if self.run_id:
            return
        if posture.is_strict:
            raise SpineCompletenessError(
                "ReasoningTrace constructed without required spine fields "
                f"under posture={posture.value}: missing=['run_id']. "
                "Populate at the construction site (Rule 12)."
            )
        import logging
        logging.getLogger("hi_agent.contracts.reasoning_trace").warning(
            "reasoning_trace_legacy_spine_incomplete: missing=['run_id'] posture=%s; "
            "would fail-closed under research/prod. (W35-T1)",
            posture.value,
        )
