"""Task view builder with layered token-budget construction.

Loading priority:
  1. L2 run index       (navigation map)
  2. L1 current stage   (current stage summary)
  3. L1 previous stage  (previous stage summary, if budget remains)
  4. L3 episodic        (episodic memories, if budget remains)
  5. Knowledge          (knowledge records, if budget remains)
  6. System reserved    (always deducted from budget)

The builder also retains the legacy item-count helpers used by earlier spikes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from hi_agent.contracts import RunIndex, StageSummary
from hi_agent.memory.l1_compressed import CompressedStageMemory
from hi_agent.memory.l2_index import RunMemoryIndex
from hi_agent.memory.retriever import MemoryRetriever
from hi_agent.task_view.token_budget import (
    DEFAULT_BUDGET,
    LAYER_BUDGETS,
    count_tokens,
    enforce_budget,
    enforce_layer_budget,
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskViewSection:
    """One section in the assembled task view."""

    layer: str  # e.g., "l2_index", "l1_current_stage"
    content: str
    token_count: int


@dataclass
class TaskView:
    """Assembled task view with budget metadata."""

    sections: list[TaskViewSection] = field(default_factory=list)
    total_tokens: int = 0
    budget: int = DEFAULT_BUDGET
    budget_utilization: float = 0.0  # 0.0 to 1.0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_run_index(index: RunMemoryIndex) -> str:
    """Render a compact navigation map from the run index."""
    lines: list[str] = [f"[Run {index.run_id}]"]
    for sp in index.stages:
        lines.append(f"  {sp.stage_id}: {sp.outcome}")
    return "\n".join(lines)


def format_stage_summary(summary: CompressedStageMemory) -> str:
    """Render findings, decisions, and outcome for a stage."""
    lines: list[str] = [f"[Stage {summary.stage_id}] outcome={summary.outcome}"]
    if summary.findings:
        lines.append("Findings:")
        for f in summary.findings:
            lines.append(f"  - {f}")
    if summary.decisions:
        lines.append("Decisions:")
        for d in summary.decisions:
            lines.append(f"  - {d}")
    if summary.key_entities:
        lines.append(f"Entities: {', '.join(summary.key_entities)}")
    if summary.contradiction_refs:
        lines.append(f"Contradictions: {', '.join(summary.contradiction_refs)}")
    return "\n".join(lines)


def format_episodes(episodes: list[dict], max_tokens: int) -> str:
    """Render episodic memories, truncating to *max_tokens*."""
    if not episodes or max_tokens <= 0:
        return ""
    lines: list[str] = []
    used = 0
    for ep in episodes:
        line = str(ep)
        line_tokens = count_tokens(line)
        if used + line_tokens > max_tokens:
            break
        lines.append(line)
        used += line_tokens
    return "\n".join(lines)


def format_knowledge(records: list, max_tokens: int) -> str:
    """Render knowledge records, truncating to *max_tokens*."""
    if not records or max_tokens <= 0:
        return ""
    lines: list[str] = []
    used = 0
    for rec in records:
        if hasattr(rec, "content"):
            line = f"[{getattr(rec, 'key', '?')}] {rec.content}"
        else:
            line = str(rec)
        line_tokens = count_tokens(line)
        if used + line_tokens > max_tokens:
            break
        lines.append(line)
        used += line_tokens
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Layered builder (new, token-based)
# ---------------------------------------------------------------------------


def build_task_view(
    run_index: RunMemoryIndex | RunIndex | None = None,
    current_stage_summary: CompressedStageMemory | None = None,
    previous_stage_summary: CompressedStageMemory | None = None,
    episodes: list[dict] | list[str] | None = None,
    knowledge_records: list | None = None,
    budget: int = DEFAULT_BUDGET,
    *,
    memory_retriever: MemoryRetriever | None = None,
    task_family: str = "",
    stage_id: str = "",
    current_failures: list[str] | None = None,
    # Legacy kwargs — accepted so old call-sites keep working.
    stage_summaries: dict[str, StageSummary] | None = None,
    knowledge: list[str] | None = None,
) -> TaskView | dict[str, object]:
    """Build a task view using layered priority loading.

    When *stage_summaries* is passed the function falls through to the legacy
    item-count path so that existing tests remain green.

    Loading order (priority):
      1. L2 run index          (<=512t) - always loaded
      2. L1 current stage      (<=2048t) - always loaded
      3. L1 previous stage     (<=2048t) - if budget remains
      4. L3 episodic memories  (<=1024t) - if budget remains
      5. Knowledge records     (<=1024t) - if budget remains
      6. System reserved       (512t)    - always reserved
    """
    # ---- legacy path -------------------------------------------------------
    if stage_summaries is not None:
        return _legacy_build(
            run_index=run_index,  # type: ignore[arg-type]
            stage_summaries=stage_summaries,
            episodes=episodes or [],  # type: ignore[arg-type]
            knowledge=knowledge or [],
            budget=budget,
        )

    # ---- new layered path --------------------------------------------------
    if budget < 0:
        raise ValueError("budget must be non-negative")

    system_reserved = min(LAYER_BUDGETS["system_reserved"], budget)
    remaining = max(0, budget - system_reserved)

    sections: list[TaskViewSection] = []

    # 1) L2 index
    if run_index is not None and remaining > 0:
        layer_max = min(LAYER_BUDGETS["l2_index"], remaining)
        if isinstance(run_index, RunMemoryIndex):
            raw = format_run_index(run_index)
        else:
            raw = str(run_index)
        content = enforce_layer_budget(raw, layer_max)
        tokens = count_tokens(content)
        sections.append(TaskViewSection(layer="l2_index", content=content, token_count=tokens))
        remaining -= tokens

    # 2) L1 current stage
    if current_stage_summary is not None and remaining > 0:
        layer_max = min(LAYER_BUDGETS["l1_current_stage"], remaining)
        raw = format_stage_summary(current_stage_summary)
        content = enforce_layer_budget(raw, layer_max)
        tokens = count_tokens(content)
        sections.append(
            TaskViewSection(layer="l1_current_stage", content=content, token_count=tokens)
        )
        remaining -= tokens

    # 3) L1 previous stage
    if previous_stage_summary is not None and remaining > 0:
        layer_max = min(LAYER_BUDGETS["l1_previous_stage"], remaining)
        raw = format_stage_summary(previous_stage_summary)
        content = enforce_layer_budget(raw, layer_max)
        tokens = count_tokens(content)
        sections.append(
            TaskViewSection(layer="l1_previous_stage", content=content, token_count=tokens)
        )
        remaining -= tokens

    # 4) L3 episodic
    if episodes and remaining > 0:
        layer_max = min(LAYER_BUDGETS["l3_episodic"], remaining)
        raw = format_episodes(episodes, layer_max)  # type: ignore[arg-type]
        if raw:
            content = enforce_layer_budget(raw, layer_max)
            tokens = count_tokens(content)
            sections.append(
                TaskViewSection(layer="l3_episodic", content=content, token_count=tokens)
            )
            remaining -= tokens

    # 5) Knowledge
    if knowledge_records and remaining > 0:
        layer_max = min(LAYER_BUDGETS["knowledge"], remaining)
        raw = format_knowledge(knowledge_records, layer_max)
        if raw:
            content = enforce_layer_budget(raw, layer_max)
            tokens = count_tokens(content)
            sections.append(
                TaskViewSection(layer="knowledge", content=content, token_count=tokens)
            )
            remaining -= tokens

    # 6) Episodic memory from retriever (lower priority, fits in remaining)
    if memory_retriever is not None and remaining > 0:
        retriever_budget = min(remaining, LAYER_BUDGETS.get("l3_episodic", 1024))
        snippets = memory_retriever.retrieve_for_stage(
            task_family=task_family,
            stage_id=stage_id,
            current_failures=current_failures,
            budget_tokens=retriever_budget,
        )
        if snippets:
            raw = "\n".join(snippets)
            content = enforce_layer_budget(raw, retriever_budget)
            tokens = count_tokens(content)
            sections.append(
                TaskViewSection(layer="episodic", content=content, token_count=tokens)
            )
            remaining -= tokens

    total = sum(s.token_count for s in sections) + system_reserved
    utilization = total / budget if budget > 0 else 0.0

    return TaskView(
        sections=sections,
        total_tokens=total,
        budget=budget,
        budget_utilization=min(1.0, utilization),
    )


# ---------------------------------------------------------------------------
# Legacy helpers (item-count budgeting, kept for backward compat)
# ---------------------------------------------------------------------------


def build_run_index(run_id: str, stage_summaries: dict[str, StageSummary]) -> RunIndex:
    """Build compact run index from stage summaries.

    Args:
      run_id: Run identifier.
      stage_summaries: Stage summaries keyed by stage ID.

    Returns:
      A compact RunIndex object.
    """
    ordered = [stage_summaries[key] for key in sorted(stage_summaries.keys())]
    statuses = [{"stage_id": item.stage_id, "outcome": item.outcome} for item in ordered]
    decisions: list[str] = []
    for item in ordered:
        decisions.extend(item.decisions)

    return RunIndex(
        run_id=run_id,
        stages_status=statuses,
        current_stage=ordered[-1].stage_id if ordered else "",
        key_decisions=decisions[:8],
    )


def _legacy_build(
    run_index: RunIndex,
    stage_summaries: dict[str, StageSummary],
    episodes: list[str],
    knowledge: list[str],
    budget: int = 12,
) -> dict[str, object]:
    """Legacy item-count layered builder (unchanged semantics)."""
    if budget < 0:
        raise ValueError("budget must be non-negative")

    remaining = budget
    current_summary: StageSummary | None = None
    previous_summary: StageSummary | None = None
    selected_episodes: list[str] = []
    selected_knowledge: list[str] = []

    if remaining > 0:
        remaining -= 1  # run_index section

    current_stage = run_index.current_stage
    if remaining > 0 and current_stage and current_stage in stage_summaries:
        current_summary = stage_summaries[current_stage]
        remaining -= 1

    if remaining > 0 and current_stage:
        ordered_ids = sorted(stage_summaries.keys())
        if current_stage in ordered_ids:
            current_pos = ordered_ids.index(current_stage)
            if current_pos > 0:
                previous_summary = stage_summaries[ordered_ids[current_pos - 1]]
                remaining -= 1

    if remaining > 0:
        selected_episodes = enforce_budget(episodes, remaining)
        remaining -= len(selected_episodes)

    if remaining > 0:
        selected_knowledge = enforce_budget(knowledge, remaining)
        remaining -= len(selected_knowledge)

    return {
        "run_index": run_index if budget > 0 else None,
        "current_stage_summary": current_summary,
        "previous_stage_summary": previous_summary,
        "episodes": selected_episodes,
        "knowledge": selected_knowledge,
        "used_items": budget - remaining,
    }


def build_task_view_with_knowledge_query(
    *,
    run_index: RunIndex,
    stage_summaries: dict[str, StageSummary],
    episodes: list[str],
    query_text: str,
    knowledge_query_fn: Callable[..., list[object]],
    top_k: int = 3,
    budget: int = 12,
) -> dict[str, object]:
    """Build task view by querying knowledge first, then delegating to builder.

    The original `build_task_view` behavior remains unchanged. This helper only
    adds a deterministic query-integration step before calling the base
    function.
    """
    if top_k < 0:
        raise ValueError("top_k must be non-negative")

    raw_hits = knowledge_query_fn(query_text=query_text, top_k=top_k)
    knowledge_items: list[str] = []
    for hit in raw_hits:
        if isinstance(hit, str):
            knowledge_items.append(hit)
            continue
        if isinstance(hit, tuple) and hit:
            maybe_record = hit[0]
            if hasattr(maybe_record, "content"):
                knowledge_items.append(str(maybe_record.content))
                continue
        if hasattr(hit, "content"):
            knowledge_items.append(str(hit.content))
            continue
        knowledge_items.append(str(hit))

    return _legacy_build(
        run_index=run_index,
        stage_summaries=stage_summaries,
        episodes=episodes,
        knowledge=knowledge_items,
        budget=budget,
    )
