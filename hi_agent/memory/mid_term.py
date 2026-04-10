"""Mid-term memory: daily work consolidation.

Built by "dream" mechanism -- consolidates multiple short-term memories
from a time period (e.g., one day) into a structured daily summary.
Stored as JSON file, available for next-day context.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hi_agent.memory.short_term import ShortTermMemory, ShortTermMemoryStore


@dataclass
class DailySummary:
    """Consolidated summary of a day's work."""

    date: str  # ISO date "2026-04-07"
    sessions_count: int = 0
    tasks_completed: list[str] = field(default_factory=list)
    tasks_failed: list[str] = field(default_factory=list)
    key_learnings: list[str] = field(default_factory=list)
    patterns_observed: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    created_at: str = ""

    def to_context_string(self, max_tokens: int = 300) -> str:
        """Format as concise string for LLM context."""
        max_chars = max_tokens * 4
        parts: list[str] = []
        parts.append(f"[Daily {self.date}] {self.sessions_count} sessions")

        if self.tasks_completed:
            parts.append(f"  completed: {'; '.join(self.tasks_completed[:5])}")
        if self.tasks_failed:
            parts.append(f"  failed: {'; '.join(self.tasks_failed[:5])}")
        if self.key_learnings:
            parts.append(f"  learnings: {'; '.join(self.key_learnings[:5])}")
        if self.patterns_observed:
            parts.append(f"  patterns: {'; '.join(self.patterns_observed[:5])}")
        if self.skills_used:
            parts.append(f"  skills: {', '.join(self.skills_used)}")

        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars - 3] + "..."
        return text


class MidTermMemoryStore:
    """File-based store for daily summaries."""

    def __init__(self, storage_dir: str = ".hi_agent/memory/mid_term") -> None:
        """Initialize MidTermMemoryStore."""
        self._storage_dir = Path(storage_dir)

    def _ensure_dir(self) -> None:
        """Run _ensure_dir."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _summary_path(self, date: str) -> Path:
        """Run _summary_path."""
        return self._storage_dir / f"{date}.json"

    def save(self, summary: DailySummary) -> None:
        """Persist daily summary to disk as JSON (atomic write)."""
        self._ensure_dir()
        if not summary.created_at:
            summary.created_at = datetime.now(UTC).isoformat()
        data = asdict(summary)
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        dest = self._summary_path(summary.date)
        fd, tmp_path = tempfile.mkstemp(dir=str(self._storage_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_path, dest)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def load(self, date: str) -> DailySummary | None:
        """Load daily summary by date string."""
        path = self._summary_path(date)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_daily_summary(data)

    def list_recent(self, days: int = 7) -> list[DailySummary]:
        """List most recent daily summaries, newest first."""
        if not self._storage_dir.exists():
            return []
        summaries: list[DailySummary] = []
        for fpath in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                summaries.append(_dict_to_daily_summary(data))
            except (json.JSONDecodeError, KeyError):
                continue
        summaries.sort(key=lambda s: s.date, reverse=True)
        return summaries[:days]


class DreamConsolidator:
    """The "dream" mechanism: consolidate short-term into mid-term.

    Inspired by claude-code's KAIROS /dream and CrewAI's on-save consolidation.
    Runs periodically (e.g., end of day) to:
    1. Gather all short-term memories from the period
    2. Deduplicate findings across sessions
    3. Extract patterns (repeated strategies, common failures)
    4. Produce a DailySummary
    """

    def __init__(
        self,
        short_term_store: ShortTermMemoryStore,
        mid_term_store: MidTermMemoryStore,
    ) -> None:
        """Initialize DreamConsolidator."""
        self._short_term = short_term_store
        self._mid_term = mid_term_store

    def consolidate(self, date: str | None = None) -> DailySummary:
        """Consolidate all short-term memories for given date into daily summary.

        If *date* is ``None``, uses today.
        """
        if date is None:
            date = datetime.now(UTC).strftime("%Y-%m-%d")

        sessions = self._gather_sessions(date)

        # Aggregate across sessions
        tasks_completed: list[str] = []
        tasks_failed: list[str] = []
        all_findings: list[str] = []
        all_tools: set[str] = set()
        total_tokens = 0
        total_cost = 0.0

        for session in sessions:
            if session.outcome == "completed":
                tasks_completed.append(session.task_goal)
            else:
                tasks_failed.append(session.task_goal)
            all_findings.extend(session.key_findings)
            all_tools.update(session.tools_used)
            total_tokens += session.total_tokens_used
            total_cost += session.total_cost_usd

        key_learnings = self._deduplicate_findings(all_findings)
        patterns = self._extract_patterns(sessions)

        summary = DailySummary(
            date=date,
            sessions_count=len(sessions),
            tasks_completed=tasks_completed,
            tasks_failed=tasks_failed,
            key_learnings=key_learnings,
            patterns_observed=patterns,
            skills_used=sorted(all_tools),
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
        )
        self._mid_term.save(summary)
        return summary

    def _gather_sessions(self, date: str) -> list[ShortTermMemory]:
        """Find all short-term memories for the given date."""
        return self._short_term.list_by_date(date)

    def _deduplicate_findings(self, all_findings: list[str]) -> list[str]:
        """Remove duplicate/near-duplicate findings.

        Uses exact match plus simple substring containment to catch
        near-duplicates (e.g., "X found" vs "X found in Y").
        """
        if not all_findings:
            return []
        unique: list[str] = []
        normalised_seen: set[str] = set()
        for finding in all_findings:
            norm = finding.strip().lower()
            if norm in normalised_seen:
                continue
            # Check if this finding is a substring of an already-kept one
            is_dup = False
            for seen in list(normalised_seen):
                if norm in seen or seen in norm:
                    is_dup = True
                    # Keep the longer version
                    if len(norm) > len(seen):
                        normalised_seen.discard(seen)
                        normalised_seen.add(norm)
                        unique = [u for u in unique if u.strip().lower() != seen]
                        unique.append(finding)
                    break
            if not is_dup:
                normalised_seen.add(norm)
                unique.append(finding)
        return unique

    def _extract_patterns(self, sessions: list[ShortTermMemory]) -> list[str]:
        """Identify repeated strategies, common failures across sessions."""
        if len(sessions) < 2:
            return []

        patterns: list[str] = []

        # Pattern: repeated tools across sessions
        tool_counts: dict[str, int] = {}
        for session in sessions:
            for tool in session.tools_used:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
        for tool, count in tool_counts.items():
            if count >= 2:
                patterns.append(f"tool '{tool}' used in {count}/{len(sessions)} sessions")

        # Pattern: repeated error codes
        error_counts: dict[str, int] = {}
        for session in sessions:
            for err in session.errors_encountered:
                error_counts[err] = error_counts.get(err, 0) + 1
        for err, count in error_counts.items():
            if count >= 2:
                patterns.append(f"error '{err}' in {count}/{len(sessions)} sessions")

        # Pattern: repeated stages
        stage_counts: dict[str, int] = {}
        for session in sessions:
            for stage in session.stages_completed:
                stage_counts[stage] = stage_counts.get(stage, 0) + 1
        for stage, count in stage_counts.items():
            if count >= 2:
                patterns.append(
                    f"stage '{stage}' completed in {count}/{len(sessions)} sessions"
                )

        return patterns


def _dict_to_daily_summary(data: dict) -> DailySummary:
    """Reconstruct a DailySummary from a dict."""
    return DailySummary(
        date=data["date"],
        sessions_count=data.get("sessions_count", 0),
        tasks_completed=data.get("tasks_completed", []),
        tasks_failed=data.get("tasks_failed", []),
        key_learnings=data.get("key_learnings", []),
        patterns_observed=data.get("patterns_observed", []),
        skills_used=data.get("skills_used", []),
        total_tokens=data.get("total_tokens", 0),
        total_cost_usd=data.get("total_cost_usd", 0.0),
        created_at=data.get("created_at", ""),
    )
