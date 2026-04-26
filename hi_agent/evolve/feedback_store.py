"""FeedbackStore — collects explicit run outcome feedback from business layer."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext

_logger = logging.getLogger(__name__)


@dataclass
class RunFeedback:
    """Explicit feedback for a completed run."""

    run_id: str
    rating: float  # 0.0 (worst) - 1.0 (best)
    notes: str = ""
    submitted_at: str = ""  # ISO 8601; set automatically if empty
    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""


class FeedbackStore:
    """Persists and retrieves run feedback.

    Args:
        storage_path: Path to JSON file. Uses in-memory-only store if None.
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        """Initialize store, optionally backed by a JSON file at storage_path."""
        self._lock = threading.Lock()
        self._records: dict[str, RunFeedback] = {}
        self._storage_path = Path(storage_path) if storage_path else None
        if self._storage_path and self._storage_path.exists():
            self._load()

    def submit(self, feedback: RunFeedback, *, exec_ctx: RunExecutionContext | None = None) -> None:
        """Record feedback for a run. Overwrites prior feedback for the same run_id.

        Args:
            feedback: The RunFeedback record to persist.
            exec_ctx: Optional RunExecutionContext; when provided, spine fields
                (tenant_id, user_id, session_id, project_id) are derived from
                exec_ctx when the feedback's own fields are empty.
                Explicit feedback fields always take precedence over exec_ctx.
        """
        if exec_ctx is not None:
            if not feedback.tenant_id:
                feedback.tenant_id = exec_ctx.tenant_id
            if not feedback.user_id:
                feedback.user_id = exec_ctx.user_id
            if not feedback.session_id:
                feedback.session_id = exec_ctx.session_id
            if not feedback.project_id:
                feedback.project_id = exec_ctx.project_id
        if not feedback.submitted_at:
            feedback.submitted_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._records[feedback.run_id] = feedback
            self._persist()
        _logger.info("feedback_store: run=%s rating=%.2f", feedback.run_id, feedback.rating)

    def get(self, run_id: str) -> RunFeedback | None:
        """Return feedback for a run, or None if not found."""
        with self._lock:
            return self._records.get(run_id)

    def list_recent(self, limit: int = 50) -> list[RunFeedback]:
        """Return the most recently submitted feedback entries."""
        with self._lock:
            items = list(self._records.values())
        return sorted(items, key=lambda f: f.submitted_at, reverse=True)[:limit]

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump({k: asdict(v) for k, v in self._records.items()}, f, indent=2)
        except OSError as exc:
            _logger.warning("feedback_store: persist failed: %s", exc)

    def _load(self) -> None:
        try:
            with open(self._storage_path, encoding="utf-8") as f:
                raw = json.load(f)
            self._records = {}
            for k, v in raw.items():
                fields = {f: v[f] for f in v if f in RunFeedback.__dataclass_fields__}
                self._records[k] = RunFeedback(**fields)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            _logger.warning("feedback_store: load failed: %s", exc)
