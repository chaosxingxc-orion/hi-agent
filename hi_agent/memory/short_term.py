"""Short-term memory: session-scoped interaction summary.

Created per-session from RunSession events. Strips tool call noise,
deduplicates repeated information, keeps structured summary.
Stored as JSON file, participates in context building.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class ShortTermMemory:
    """Summary of a single session's interactions."""

    session_id: str
    run_id: str
    task_goal: str
    stages_completed: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    errors_encountered: list[str] = field(default_factory=list)
    outcome: str = "completed"
    duration_seconds: float = 0.0
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    created_at: str = ""

    def to_context_string(self, max_tokens: int = 500) -> str:
        """Format as concise string for LLM context injection.

        Truncates to fit within approximate *max_tokens* budget
        (1 token ~ 4 characters).
        """
        max_chars = max_tokens * 4
        parts: list[str] = []
        parts.append(f"[Session {self.session_id}] {self.outcome}: {self.task_goal}")

        if self.stages_completed:
            parts.append(f"  stages: {', '.join(self.stages_completed)}")
        if self.key_findings:
            parts.append(f"  findings: {'; '.join(self.key_findings[:5])}")
        if self.key_decisions:
            parts.append(f"  decisions: {'; '.join(self.key_decisions[:5])}")
        if self.tools_used:
            parts.append(f"  tools: {', '.join(self.tools_used)}")
        if self.errors_encountered:
            parts.append(f"  errors: {', '.join(self.errors_encountered)}")

        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[:max_chars - 3] + "..."
        return text


class ShortTermMemoryStore:
    """File-based store for short-term memories.

    Eviction
    --------
    When *max_sessions* is set (default 500), saving a new session evicts the
    oldest entries so the store never exceeds that ceiling.  This prevents
    unbounded disk growth during long-running deployments.
    """

    def __init__(
        self,
        storage_dir: str = ".hi_agent/memory/short_term",
        max_sessions: int = 500,
    ) -> None:
        """Initialize ShortTermMemoryStore.

        Args:
            storage_dir: Directory for JSON files.
            max_sessions: Maximum number of sessions to retain.  Oldest
                sessions (by ``created_at``) are deleted when the limit is
                exceeded.  Set to 0 to disable eviction.
        """
        self._storage_dir = Path(storage_dir)
        self._max_sessions = max_sessions

    def _ensure_dir(self) -> None:
        """Run _ensure_dir."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _memory_path(self, session_id: str) -> Path:
        """Run _memory_path."""
        return self._storage_dir / f"{session_id}.json"

    def save(self, memory: ShortTermMemory) -> None:
        """Save to JSON file named by session_id (atomic write).

        After a successful write, evicts the oldest sessions if
        ``max_sessions`` would be exceeded.
        """
        self._ensure_dir()
        if not memory.created_at:
            memory.created_at = datetime.now(UTC).isoformat()
        data = asdict(memory)
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        dest = self._memory_path(memory.session_id)
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
        if self._max_sessions > 0:
            self._evict_oldest(keep=self._max_sessions)

    def _evict_oldest(self, keep: int) -> int:
        """Delete oldest sessions so at most *keep* remain.

        Returns the number of sessions deleted.
        """
        if not self._storage_dir.exists():
            return 0
        entries: list[tuple[str, Path]] = []
        for fpath in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                entries.append((data.get("created_at", ""), fpath))
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        if len(entries) <= keep:
            return 0
        # Sort ascending (oldest first) and delete the excess
        entries.sort(key=lambda t: t[0])
        to_delete = entries[: len(entries) - keep]
        deleted = 0
        for _, fpath in to_delete:
            try:
                fpath.unlink(missing_ok=True)
                deleted += 1
            except OSError:
                pass
        return deleted

    def load(self, session_id: str) -> ShortTermMemory | None:
        """Load a short-term memory by session_id."""
        path = self._memory_path(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_short_term(data)

    def list_recent(self, limit: int = 10) -> list[ShortTermMemory]:
        """List most recent sessions, newest first."""
        if not self._storage_dir.exists():
            return []
        memories: list[ShortTermMemory] = []
        for fpath in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                memories.append(_dict_to_short_term(data))
            except (json.JSONDecodeError, KeyError):
                continue
        memories.sort(key=lambda m: m.created_at, reverse=True)
        return memories[:limit]

    def list_by_date(self, date: str) -> list[ShortTermMemory]:
        """List all short-term memories whose created_at starts with *date* (ISO date prefix)."""
        if not self._storage_dir.exists():
            return []
        results: list[ShortTermMemory] = []
        for fpath in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                mem = _dict_to_short_term(data)
                if mem.created_at.startswith(date):
                    results.append(mem)
            except (json.JSONDecodeError, KeyError):
                continue
        results.sort(key=lambda m: m.created_at)
        return results

    def build_from_session(self, session: Any) -> ShortTermMemory:
        """Build ShortTermMemory from RunSession data.

        Strips tool call noise, deduplicates, summarizes.
        Expects *session* to be a ``RunSession`` instance.
        """
        run_id: str = getattr(session, "run_id", "unknown")
        task_goal: str = ""
        tc = getattr(session, "task_contract", None)
        if tc is not None:
            task_goal = getattr(tc, "goal", str(tc))

        # Stages completed
        stage_states: dict[str, str] = getattr(session, "stage_states", {})
        stages_completed = [
            sid for sid, state in stage_states.items() if state == "completed"
        ]

        # Key findings and decisions from L1 summaries
        key_findings: list[str] = []
        key_decisions: list[str] = []
        l1_summaries: dict[str, dict] = getattr(session, "l1_summaries", {})
        for summary in l1_summaries.values():
            key_findings.extend(summary.get("findings", []))
            key_decisions.extend(summary.get("decisions", []))

        # Unique tool names from L0 records
        tools_set: set[str] = set()
        l0_records: list[dict] = getattr(session, "l0_records", [])
        for rec in l0_records:
            evt = rec.get("event_type", "")
            if evt in ("tool_call", "action_executed"):
                tool_name = rec.get("payload", {}).get("tool", "")
                if tool_name:
                    tools_set.add(tool_name)

        # Error codes from L0 records
        errors_set: set[str] = set()
        for rec in l0_records:
            payload = rec.get("payload", {})
            code = payload.get("failure_code", "") or payload.get("error_code", "")
            if code:
                errors_set.add(code)

        # Determine outcome
        outcome = "completed"
        if any(s == "failed" for s in stage_states.values()):
            outcome = "failed"

        return ShortTermMemory(
            session_id=f"{run_id}_session",
            run_id=run_id,
            task_goal=task_goal,
            stages_completed=stages_completed,
            key_findings=_deduplicate(key_findings),
            key_decisions=_deduplicate(key_decisions),
            tools_used=sorted(tools_set),
            errors_encountered=sorted(errors_set),
            outcome=outcome,
            total_tokens_used=getattr(session, "total_input_tokens", 0)
            + getattr(session, "total_output_tokens", 0),
            total_cost_usd=getattr(session, "total_cost_usd", 0.0),
        )


def _deduplicate(items: list[str]) -> list[str]:
    """Remove exact duplicates while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _dict_to_short_term(data: dict) -> ShortTermMemory:
    """Reconstruct a ShortTermMemory from a dict."""
    return ShortTermMemory(
        session_id=data["session_id"],
        run_id=data["run_id"],
        task_goal=data.get("task_goal", ""),
        stages_completed=data.get("stages_completed", []),
        key_findings=data.get("key_findings", []),
        key_decisions=data.get("key_decisions", []),
        tools_used=data.get("tools_used", []),
        errors_encountered=data.get("errors_encountered", []),
        outcome=data.get("outcome", "completed"),
        duration_seconds=data.get("duration_seconds", 0.0),
        total_tokens_used=data.get("total_tokens_used", 0),
        total_cost_usd=data.get("total_cost_usd", 0.0),
        created_at=data.get("created_at", ""),
    )
