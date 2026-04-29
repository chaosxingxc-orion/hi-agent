"""Episodic memory store for cross-run learning."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class EpisodeRecord:
    """Summary of a completed run, stored for cross-run learning."""

    run_id: str
    task_id: str
    task_family: str
    goal: str
    outcome: str  # "completed" | "failed" | "aborted"
    stages_completed: list[str]
    key_findings: list[str]  # extracted from L1 compressed memories
    key_decisions: list[str]
    failure_codes: list[str]
    quality_score: float | None = None
    efficiency_score: float | None = None
    duration_seconds: float = 0.0
    timestamp: str = ""
    tags: list[str] = field(default_factory=list)
    tenant_id: str = ""  # scope: process-internal — episode; backcompat for pre-spine JSON files
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""


class EpisodicMemoryStore:
    """Persistent episodic memory across runs.

    Stores episode records as JSON files in a configurable directory.
    Supports query by task_family, outcome, recency, and similarity.
    """

    def __init__(self, storage_dir: str = ".hi_agent/episodes") -> None:
        """Initialize EpisodicMemoryStore."""
        self._storage_dir = Path(storage_dir)

    def _ensure_dir(self) -> None:
        """Run _ensure_dir."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _episode_path(self, run_id: str) -> Path:
        """Run _episode_path."""
        return self._storage_dir / f"{run_id}.json"

    def store(self, episode: EpisodeRecord) -> None:
        """Persist episode to disk as JSON."""
        self._ensure_dir()
        if not episode.timestamp:
            episode.timestamp = datetime.now(UTC).isoformat()
        data = asdict(episode)
        self._episode_path(episode.run_id).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get(self, run_id: str) -> EpisodeRecord | None:
        """Retrieve episode by run_id."""
        path = self._episode_path(run_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_episode(data)

    def _load_all(self) -> list[EpisodeRecord]:
        """Load all episodes from disk, most recent first."""
        if not self._storage_dir.exists():
            return []
        episodes: list[EpisodeRecord] = []
        for fpath in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                episodes.append(_dict_to_episode(data))
            except (json.JSONDecodeError, KeyError):
                continue
        # Sort by timestamp descending (most recent first)
        episodes.sort(key=lambda e: e.timestamp, reverse=True)
        return episodes

    def query(
        self,
        task_family: str | None = None,
        outcome: str | None = None,
        limit: int = 10,
        tags: list[str] | None = None,
    ) -> list[EpisodeRecord]:
        """Query episodes with filters. Returns most recent first."""
        episodes = self._load_all()
        results: list[EpisodeRecord] = []
        for ep in episodes:
            if task_family is not None and ep.task_family != task_family:
                continue
            if outcome is not None and ep.outcome != outcome:
                continue
            if tags is not None and not set(tags).issubset(set(ep.tags)):
                continue
            results.append(ep)
            if len(results) >= limit:
                break
        return results

    def get_similar_failures(self, failure_codes: list[str], limit: int = 5) -> list[EpisodeRecord]:
        """Find past episodes with overlapping failure codes."""
        if not failure_codes:
            return []
        target = set(failure_codes)
        episodes = self._load_all()
        scored: list[tuple[int, EpisodeRecord]] = []
        for ep in episodes:
            if not ep.failure_codes:
                continue
            overlap = len(target & set(ep.failure_codes))
            if overlap > 0:
                scored.append((overlap, ep))
        # Sort by overlap count descending, then by recency (already sorted)
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [ep for _, ep in scored[:limit]]

    def get_successful_patterns(self, task_family: str, limit: int = 5) -> list[EpisodeRecord]:
        """Find successful episodes in same task family."""
        return self.query(task_family=task_family, outcome="completed", limit=limit)

    def count(self) -> int:
        """Return total number of stored episodes."""
        if not self._storage_dir.exists():
            return 0
        return len(list(self._storage_dir.glob("*.json")))

    def clear(self) -> None:
        """Remove all stored episodes."""
        if not self._storage_dir.exists():
            return
        for fpath in self._storage_dir.glob("*.json"):
            fpath.unlink()


def _dict_to_episode(data: dict) -> EpisodeRecord:
    """Reconstruct an EpisodeRecord from a dict."""
    return EpisodeRecord(
        run_id=data["run_id"],
        task_id=data["task_id"],
        task_family=data["task_family"],
        goal=data["goal"],
        outcome=data["outcome"],
        stages_completed=data.get("stages_completed", []),
        key_findings=data.get("key_findings", []),
        key_decisions=data.get("key_decisions", []),
        failure_codes=data.get("failure_codes", []),
        quality_score=data.get("quality_score"),
        efficiency_score=data.get("efficiency_score"),
        duration_seconds=data.get("duration_seconds", 0.0),
        timestamp=data.get("timestamp", ""),
        tags=data.get("tags", []),
        tenant_id=data.get("tenant_id", ""),
        user_id=data.get("user_id", ""),
        session_id=data.get("session_id", ""),
        project_id=data.get("project_id", ""),
    )
