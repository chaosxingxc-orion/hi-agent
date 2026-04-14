"""Unified context manager for LLM context window orchestration.

Coordinates all context sources (session, memory, knowledge, skills)
into a single budget-managed context window for each LLM call.

Inspired by:
- claude-code: 4-level threshold system + fallback chain + circuit breaker
- agent-core: processor chain with dual hook points (on_add + on_build)

Key responsibilities:
1. Budget allocation across sections (system, tools, skills, memory, history)
2. Automatic compression when thresholds exceeded
3. Health monitoring (utilization, per-section breakdown)
4. Diminishing returns detection for long-running tasks
5. Fallback chain with circuit breaker
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hi_agent.task_view.token_budget import count_tokens

# ---------------------------------------------------------------------------
# Enums and data classes
# ---------------------------------------------------------------------------


class ContextHealth(Enum):
    """Context window health levels."""

    GREEN = "green"    # < 70% -- normal
    YELLOW = "yellow"  # 70-85% -- warning, prepare compression
    ORANGE = "orange"  # 85-95% -- auto-compress triggered
    RED = "red"        # > 95% -- blocked, must compress


@dataclass
class ContextBudget:
    """Token budget allocation across context sections."""

    total_window: int = 200_000    # Model's context window
    output_reserve: int = 8_000    # Reserved for model response
    system_prompt: int = 2_000     # System instructions
    tool_definitions: int = 3_000  # Tool schemas
    skill_prompts: int = 5_000     # Skill descriptions
    memory_context: int = 2_000    # Memory retrieval results
    knowledge_context: int = 1_500 # Knowledge retrieval results

    @property
    def effective_window(self) -> int:
        """Available tokens after output reserve."""
        return self.total_window - self.output_reserve

    @property
    def fixed_overhead(self) -> int:
        """Tokens allocated to fixed sections."""
        return (
            self.system_prompt
            + self.tool_definitions
            + self.skill_prompts
            + self.memory_context
            + self.knowledge_context
        )

    @property
    def history_budget(self) -> int:
        """Remaining tokens for conversation history."""
        return max(0, self.effective_window - self.fixed_overhead)

    @classmethod
    def from_config(cls, cfg: Any) -> "ContextBudget":
        """Build ContextBudget from a TraceConfig instance."""
        return cls(
            total_window=cfg.context_total_window,
            output_reserve=cfg.context_output_reserve,
            system_prompt=cfg.context_system_prompt_budget,
            tool_definitions=cfg.context_tool_definitions_budget,
            skill_prompts=cfg.context_skill_prompts_budget,
            memory_context=cfg.memory_retriever_default_budget,
            knowledge_context=cfg.context_knowledge_context_budget,
        )


@dataclass
class ContextSection:
    """A section of the context with content and token usage."""

    name: str
    content: str
    tokens: int = 0
    budget: int = 0
    source: str = ""  # where this content came from


@dataclass
class ContextSnapshot:
    """Complete context ready for LLM call."""

    sections: list[ContextSection] = field(default_factory=list)
    total_tokens: int = 0
    budget_tokens: int = 0
    utilization_pct: float = 0.0
    health: ContextHealth = ContextHealth.GREEN
    compressions_applied: int = 0
    purpose: str = ""  # routing, action, compression, etc

    def to_prompt_string(self) -> str:
        """Combine all sections into a single prompt string."""
        parts = []
        for section in self.sections:
            if section.content:
                parts.append(f"## {section.name}\n{section.content}")
        return "\n\n".join(parts)

    def to_sections_dict(self) -> dict[str, str]:
        """Return as dict for structured injection."""
        return {s.name: s.content for s in self.sections if s.content}

    def get_section(self, name: str) -> ContextSection | None:
        """Retrieve a section by name."""
        for s in self.sections:
            if s.name == name:
                return s
        return None


@dataclass
class ContextHealthReport:
    """Health status of the context window."""

    health: ContextHealth
    utilization_pct: float
    total_tokens: int
    budget_tokens: int
    per_section: dict[str, dict[str, int]]  # section_name -> {tokens, budget, pct}
    compressions_total: int = 0
    compression_failures: int = 0
    circuit_breaker_open: bool = False
    diminishing_returns: bool = False


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------


class ContextManager:
    """Unified context orchestrator for long-running task execution.

    Coordinates session, memory, knowledge, and skills into a single
    budget-managed context window.  Applies a 4-level threshold system
    with a compression fallback chain and circuit breaker.
    """

    def __init__(
        self,
        budget: ContextBudget | None = None,
        session: Any | None = None,          # RunSession
        memory_retriever: Any | None = None, # UnifiedMemoryRetriever or RetrievalEngine
        skill_loader: Any | None = None,     # SkillLoader
        compressor: Any | None = None,       # MemoryCompressor for LLM summarization
        # Thresholds (claude-code pattern)
        green_threshold: float = 0.70,
        yellow_threshold: float = 0.85,
        orange_threshold: float = 0.95,
        # Circuit breaker
        max_compression_failures: int = 3,
        # Diminishing returns detection
        diminishing_window: int = 3,         # consecutive low-output iterations
        diminishing_threshold: int = 100,    # minimum tokens per iteration
    ) -> None:
        """Initialize ContextManager."""
        self._budget = budget or ContextBudget()
        self._session = session
        self._memory_retriever = memory_retriever
        self._skill_loader = skill_loader
        self._compressor = compressor

        # Thresholds
        self._green_threshold = green_threshold
        self._yellow_threshold = yellow_threshold
        self._orange_threshold = orange_threshold

        # Circuit breaker
        self._max_compression_failures = max_compression_failures
        self._compression_count: int = 0
        self._compression_failures: int = 0
        self._circuit_breaker_open: bool = False

        # Diminishing returns
        self._diminishing_window = diminishing_window
        self._diminishing_threshold = diminishing_threshold
        self._iteration_tokens: list[int] = []  # per-iteration output tokens

        # History buffer (what has been sent to LLM)
        self._history_entries: list[dict[str, Any]] = []
        self._compact_offset: int = 0  # entries before this index are compressed
        self._compact_summary: str = ""  # summary of compressed entries

        # Knowledge content injected from retrieval (set via set_knowledge_context)
        self._knowledge_content: str = ""

    @classmethod
    def from_config(
        cls,
        cfg: Any,
        session: Any = None,
        memory_retriever: Any = None,
        skill_loader: Any = None,
        compressor: Any = None,
    ) -> "ContextManager":
        """Instantiate ContextManager from a TraceConfig."""
        return cls(
            budget=ContextBudget.from_config(cfg),
            session=session,
            memory_retriever=memory_retriever,
            skill_loader=skill_loader,
            compressor=compressor,
            green_threshold=cfg.context_health_green_threshold,
            yellow_threshold=cfg.context_health_yellow_threshold,
            orange_threshold=cfg.context_health_orange_threshold,
            max_compression_failures=cfg.context_max_compression_failures,
            diminishing_window=cfg.context_diminishing_window,
            diminishing_threshold=cfg.context_diminishing_threshold,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def prepare_context(
        self,
        purpose: str = "routing",
        system_prompt: str = "",
        tool_definitions: str = "",
        extra_context: dict[str, str] | None = None,
    ) -> ContextSnapshot:
        """Prepare complete context for an LLM call.

        Steps:
        1. Assemble all sections within their budgets
        2. Check total utilization against thresholds
        3. If ORANGE/RED, trigger compression fallback chain
        4. Return final snapshot with health status
        """
        sections = [
            self._assemble_system(system_prompt),
            self._assemble_tools(tool_definitions),
            self._assemble_skills(),
            self._assemble_memory(),
            self._assemble_knowledge(),
            self._assemble_history(),
        ]

        # Inject extra context sections
        if extra_context:
            for name, content in extra_context.items():
                tokens = count_tokens(content)
                sections.append(
                    ContextSection(
                        name=name,
                        content=content,
                        tokens=tokens,
                        budget=tokens,
                        source="extra",
                    )
                )

        total_tokens = sum(s.tokens for s in sections)
        health = self._check_health(total_tokens)
        compressions_applied = 0

        # Compress if needed
        if health in (ContextHealth.ORANGE, ContextHealth.RED):
            sections, total_tokens = self._compress_if_needed(
                sections, total_tokens
            )
            compressions_applied = 1
            health = self._check_health(total_tokens)

        effective = self._budget.effective_window
        utilization = total_tokens / effective if effective > 0 else 0.0

        return ContextSnapshot(
            sections=sections,
            total_tokens=total_tokens,
            budget_tokens=effective,
            utilization_pct=utilization,
            health=health,
            compressions_applied=compressions_applied,
            purpose=purpose,
        )

    # ------------------------------------------------------------------
    # Section assembly
    # ------------------------------------------------------------------

    def _assemble_system(self, system_prompt: str) -> ContextSection:
        """Assemble system prompt section."""
        budget = self._budget.system_prompt
        content = system_prompt
        tokens = count_tokens(content) if content else 0
        if tokens > budget and content:
            # Truncate to budget
            max_chars = budget * 4
            content = content[:max_chars]
            tokens = count_tokens(content)
        return ContextSection(
            name="system",
            content=content,
            tokens=tokens,
            budget=budget,
            source="system_prompt",
        )

    def _assemble_tools(self, tool_definitions: str) -> ContextSection:
        """Assemble tool definitions section."""
        budget = self._budget.tool_definitions
        content = tool_definitions
        tokens = count_tokens(content) if content else 0
        if tokens > budget and content:
            max_chars = budget * 4
            content = content[:max_chars]
            tokens = count_tokens(content)
        return ContextSection(
            name="tools",
            content=content,
            tokens=tokens,
            budget=budget,
            source="tool_definitions",
        )

    def _assemble_skills(self) -> ContextSection:
        """Use SkillLoader.build_prompt() with skill budget."""
        budget = self._budget.skill_prompts
        if self._skill_loader is None:
            return ContextSection(
                name="skills", content="", tokens=0, budget=budget, source="none"
            )

        try:
            prompt = self._skill_loader.build_prompt(budget_tokens=budget)
            content = prompt.to_prompt_string()
            tokens = prompt.total_tokens
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "ContextManager: skill_loader.build_prompt failed — skills section will be empty: %s",
                _exc,
                exc_info=True,
            )
            content = ""
            tokens = 0

        return ContextSection(
            name="skills",
            content=content,
            tokens=tokens,
            budget=budget,
            source="skill_loader",
        )

    def _assemble_memory(self) -> ContextSection:
        """Use memory retriever with memory budget."""
        budget = self._budget.memory_context
        if self._memory_retriever is None:
            return ContextSection(
                name="memory", content="", tokens=0, budget=budget, source="none"
            )

        try:
            # Support both UnifiedMemoryRetriever and RetrievalEngine
            if hasattr(self._memory_retriever, "retrieve"):
                result = self._memory_retriever.retrieve(
                    query="", budget_tokens=budget
                )
                if hasattr(result, "to_context_string"):
                    content = result.to_context_string()
                else:
                    content = str(result)
                tokens = count_tokens(content) if content else 0
            else:
                content = ""
                tokens = 0
        except Exception:
            content = ""
            tokens = 0

        if tokens > budget and content:
            max_chars = budget * 4
            content = content[:max_chars]
            tokens = count_tokens(content)

        return ContextSection(
            name="memory",
            content=content,
            tokens=tokens,
            budget=budget,
            source="memory_retriever",
        )

    def set_knowledge_context(self, content: str) -> None:
        """Inject retrieved knowledge content into the context assembly.

        Called by the stage executor after retrieval_engine.retrieve() so
        that the content appears in the 'knowledge' section of every
        subsequent prepare_context() call for this stage.

        Args:
            content: Formatted knowledge text (e.g. from
                     RetrievalResult.to_context_string()).
        """
        self._knowledge_content = content or ""

    def _assemble_knowledge(self) -> ContextSection:
        """Use knowledge retrieval with knowledge budget.

        Returns knowledge previously injected via set_knowledge_context().
        Truncates to the allocated budget if necessary.
        """
        budget = self._budget.knowledge_context
        content = self._knowledge_content
        tokens = count_tokens(content) if content else 0
        if tokens > budget and content:
            max_chars = budget * 4
            content = content[:max_chars]
            tokens = count_tokens(content)
        return ContextSection(
            name="knowledge",
            content=content,
            tokens=tokens,
            budget=budget,
            source="retrieval_engine" if content else "none",
        )

    def _assemble_history(self) -> ContextSection:
        """Assemble conversation history.

        Only includes entries AFTER compact_offset (dedup with compressed
        content).  Prepends compact summary if one exists.
        """
        budget = self._budget.history_budget
        parts: list[str] = []
        used = 0

        # Prepend compact summary of earlier entries
        if self._compact_summary:
            summary_tokens = count_tokens(self._compact_summary)
            parts.append(f"[Summary of earlier context]\n{self._compact_summary}")
            used += summary_tokens

        # Append entries after compact offset
        for entry in self._history_entries[self._compact_offset:]:
            entry_text = f"[{entry.get('role', 'unknown')}] {entry.get('content', '')}"
            entry_tokens = count_tokens(entry_text)
            if used + entry_tokens > budget:
                break
            parts.append(entry_text)
            used += entry_tokens

        content = "\n".join(parts)
        return ContextSection(
            name="history",
            content=content,
            tokens=used,
            budget=budget,
            source="session_history",
        )

    # ------------------------------------------------------------------
    # Threshold checking
    # ------------------------------------------------------------------

    def _check_health(self, total_tokens: int) -> ContextHealth:
        """Map utilization to health level."""
        effective = self._budget.effective_window
        if effective <= 0:
            return ContextHealth.RED
        pct = total_tokens / effective
        if pct >= self._orange_threshold:
            return ContextHealth.RED
        if pct >= self._yellow_threshold:
            return ContextHealth.ORANGE
        if pct >= self._green_threshold:
            return ContextHealth.YELLOW
        return ContextHealth.GREEN

    # ------------------------------------------------------------------
    # Compression fallback chain
    # ------------------------------------------------------------------

    def _compress_if_needed(
        self,
        sections: list[ContextSection],
        total_tokens: int,
    ) -> tuple[list[ContextSection], int]:
        """Apply compression fallback chain if utilization too high.

        Fallback chain (claude-code pattern):
        1. Snip: Remove old history entries (zero cost)
        2. Compact: LLM-summarize history (has cost)
        3. Trim: Truncate lowest-priority sections
        4. Block: Return error if still over budget

        Circuit breaker: skip auto-compression after N consecutive failures.
        """
        target = int(self._budget.effective_window * self._yellow_threshold)

        if self._circuit_breaker_open:
            # Skip LLM compression but still try snip + trim
            sections, total_tokens = self._apply_snip_and_trim(
                sections, total_tokens, target
            )
            return sections, total_tokens

        # Step 1: Snip history
        history_section = self._find_section(sections, "history")
        if history_section is not None and total_tokens > target:
            new_history = self._snip_history(history_section, target)
            delta = history_section.tokens - new_history.tokens
            total_tokens -= delta
            self._replace_section(sections, new_history)

        # Step 2: Compact history (LLM summarization)
        if total_tokens > target and self._compressor is not None:
            history_section = self._find_section(sections, "history")
            if history_section is not None:
                try:
                    new_history = self._compact_history(
                        history_section, target
                    )
                    delta = history_section.tokens - new_history.tokens
                    total_tokens -= delta
                    self._replace_section(sections, new_history)
                    self._compression_count += 1
                    self._compression_failures = 0  # reset on success
                except Exception:
                    self._compression_failures += 1
                    if self._compression_failures >= self._max_compression_failures:
                        self._circuit_breaker_open = True

        # Step 3: Trim low-priority sections
        if total_tokens > target:
            sections = self._trim_sections(sections, target)
            total_tokens = sum(s.tokens for s in sections)

        return sections, total_tokens

    def _apply_snip_and_trim(
        self,
        sections: list[ContextSection],
        total_tokens: int,
        target: int,
    ) -> tuple[list[ContextSection], int]:
        """Apply snip + trim only (circuit breaker mode)."""
        history_section = self._find_section(sections, "history")
        if history_section is not None and total_tokens > target:
            new_history = self._snip_history(history_section, target)
            delta = history_section.tokens - new_history.tokens
            total_tokens -= delta
            self._replace_section(sections, new_history)

        if total_tokens > target:
            sections = self._trim_sections(sections, target)
            total_tokens = sum(s.tokens for s in sections)

        return sections, total_tokens

    def _snip_history(
        self,
        history_section: ContextSection,
        target_tokens: int,
    ) -> ContextSection:
        """Remove old entries from history to fit target.

        Drops entries from the beginning (oldest) of the post-compact
        history until the section fits.
        """
        lines = history_section.content.split("\n") if history_section.content else []
        if not lines:
            return history_section

        # Calculate how many tokens we need to shed
        excess = history_section.tokens - (history_section.budget // 2)
        if excess <= 0:
            return history_section

        # Drop lines from the front (oldest entries)
        dropped_tokens = 0
        drop_count = 0
        for line in lines:
            line_tokens = count_tokens(line)
            dropped_tokens += line_tokens
            drop_count += 1
            if dropped_tokens >= excess:
                break

        remaining_lines = lines[drop_count:]
        new_content = "\n".join(remaining_lines)
        new_tokens = count_tokens(new_content) if new_content else 0

        # Advance compact offset since we snipped entries
        snipped_real = min(drop_count, len(self._history_entries) - self._compact_offset)
        self._compact_offset += max(0, snipped_real)

        return ContextSection(
            name="history",
            content=new_content,
            tokens=new_tokens,
            budget=history_section.budget,
            source=history_section.source,
        )

    def _compact_history(
        self,
        history_section: ContextSection,
        target_tokens: int,
    ) -> ContextSection:
        """LLM-summarize history entries to fit target.

        Updates compact_offset to mark compressed region.
        """
        if self._compressor is None:
            return history_section

        content = history_section.content
        if not content:
            return history_section

        # Call compressor to summarize the history
        try:
            if hasattr(self._compressor, "compress_text"):
                summary = self._compressor.compress_text(content)
            elif hasattr(self._compressor, "compress_stage"):
                from hi_agent.memory.l0_raw import RawEventRecord

                records = [
                    RawEventRecord(
                        event_type="history",
                        payload={"content": content},
                    )
                ]
                result = self._compressor.compress_stage("history", records)
                summary = "; ".join(result.findings) if result.findings else content[:200]
            else:
                # Fallback: simple truncation summary
                summary = content[:200] + "..." if len(content) > 200 else content
        except Exception:
            summary = content[:200] + "..." if len(content) > 200 else content
            raise  # re-raise for circuit breaker

        # Update compact state
        self._compact_summary = summary
        self._compact_offset = len(self._history_entries)

        new_content = f"[Summary of earlier context]\n{summary}"
        new_tokens = count_tokens(new_content)

        return ContextSection(
            name="history",
            content=new_content,
            tokens=new_tokens,
            budget=history_section.budget,
            source=history_section.source,
        )

    def _trim_sections(
        self,
        sections: list[ContextSection],
        target_tokens: int,
    ) -> list[ContextSection]:
        """Trim lowest-priority sections.

        Priority order (trim first to last):
        knowledge -> memory -> skills -> history -> tools -> system
        """
        total = sum(s.tokens for s in sections)
        if total <= target_tokens:
            return sections

        trim_order = ["knowledge", "memory", "skills", "history"]

        for section_name in trim_order:
            if total <= target_tokens:
                break
            section = self._find_section(sections, section_name)
            if section is None or section.tokens == 0:
                continue
            excess = total - target_tokens
            if section.tokens <= excess:
                # Remove entire section
                total -= section.tokens
                section.content = ""
                section.tokens = 0
            else:
                # Partial trim
                keep_tokens = section.tokens - excess
                max_chars = keep_tokens * 4
                section.content = section.content[:max_chars]
                old_tokens = section.tokens
                section.tokens = count_tokens(section.content)
                total -= old_tokens - section.tokens

        return sections

    # ------------------------------------------------------------------
    # Response tracking
    # ------------------------------------------------------------------

    def record_response(
        self,
        output_tokens: int,
        actual_input_tokens: int | None = None,
    ) -> None:
        """Record LLM response for tracking.

        Updates iteration tokens for diminishing returns detection.
        """
        self._iteration_tokens.append(output_tokens)

    # ------------------------------------------------------------------
    # Diminishing returns detection
    # ------------------------------------------------------------------

    def check_diminishing_returns(self) -> bool:
        """Check if recent iterations show diminishing output.

        True if last N iterations all produced < threshold tokens.
        """
        if len(self._iteration_tokens) < self._diminishing_window:
            return False
        recent = self._iteration_tokens[-self._diminishing_window:]
        return all(t < self._diminishing_threshold for t in recent)

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def add_history_entry(
        self,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Add an entry to conversation history."""
        entry: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
        }
        if metadata:
            entry["metadata"] = metadata
        self._history_entries.append(entry)

    def get_history_after_compact(self) -> list[dict]:
        """Get history entries after the compact offset."""
        return list(self._history_entries[self._compact_offset:])

    # ------------------------------------------------------------------
    # Health reporting
    # ------------------------------------------------------------------

    def get_health_report(self) -> ContextHealthReport:
        """Full health report of context state."""
        # Build a snapshot to get current state
        sections = [
            self._assemble_system(""),
            self._assemble_tools(""),
            self._assemble_skills(),
            self._assemble_memory(),
            self._assemble_knowledge(),
            self._assemble_history(),
        ]
        total_tokens = sum(s.tokens for s in sections)
        effective = self._budget.effective_window
        health = self._check_health(total_tokens)
        utilization = total_tokens / effective if effective > 0 else 0.0

        per_section: dict[str, dict[str, int]] = {}
        for s in sections:
            pct = int((s.tokens / s.budget * 100) if s.budget > 0 else 0)
            per_section[s.name] = {
                "tokens": s.tokens,
                "budget": s.budget,
                "pct": pct,
            }

        return ContextHealthReport(
            health=health,
            utilization_pct=utilization,
            total_tokens=total_tokens,
            budget_tokens=effective,
            per_section=per_section,
            compressions_total=self._compression_count,
            compression_failures=self._compression_failures,
            circuit_breaker_open=self._circuit_breaker_open,
            diminishing_returns=self.check_diminishing_returns(),
        )

    # ------------------------------------------------------------------
    # Budget adjustment
    # ------------------------------------------------------------------

    def adjust_budget(self, **kwargs: int) -> None:
        """Dynamically adjust section budgets.

        Accepted keyword arguments correspond to ContextBudget fields:
        total_window, output_reserve, system_prompt, tool_definitions,
        skill_prompts, memory_context, knowledge_context.
        """
        for key, value in kwargs.items():
            if hasattr(self._budget, key):
                setattr(self._budget, key, value)

    def set_model_context_window(self, total_tokens: int) -> None:
        """Update total window size (e.g., when switching models)."""
        self._budget.total_window = total_tokens

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_section(
        sections: list[ContextSection], name: str
    ) -> ContextSection | None:
        """Find a section by name."""
        for s in sections:
            if s.name == name:
                return s
        return None

    @staticmethod
    def _replace_section(
        sections: list[ContextSection], replacement: ContextSection
    ) -> None:
        """Replace a section in place by name."""
        for i, s in enumerate(sections):
            if s.name == replacement.name:
                sections[i] = replacement
                return
