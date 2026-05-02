"""RunEventEmitter: 12 typed run lifecycle events (C8).

Provides typed record_* methods for run lifecycle events. Each method satisfies
Rule 7's four-prong contract:
  1. Countable   — named counter on /metrics
  2. Attributable — INFO/WARNING log carrying run_id + tenant_id
  3. Inspectable  — event appended to per-run events list (drained by RunResult)
  4. Gate-asserted — metrics_cardinality gate asserts all 12 names present

The 12 events:
  run_submitted, run_started, run_completed, run_failed, run_cancelled,
  stage_started, stage_completed, stage_failed,
  artifact_created, experiment_posted, feedback_submitted, run_resumed.

Usage::

    emitter = RunEventEmitter(run_id=run_id, tenant_id=tenant_id)
    emitter.record_run_submitted()
    emitter.record_stage_started(stage_id="gather")
    emitter.record_run_completed(duration_ms=1250.0)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from hi_agent.observability.metric_counter import Counter

_logger = logging.getLogger(__name__)

# --- 12 named counters (C8) ---
_c_submitted = Counter("hi_agent_run_submitted_total")
_c_started = Counter("hi_agent_run_started_total")
_c_completed = Counter("hi_agent_run_completed_total")
_c_failed = Counter("hi_agent_run_failed_total")
_c_cancelled = Counter("hi_agent_run_cancelled_total")
_c_stage_started = Counter("hi_agent_stage_started_total")
_c_stage_completed = Counter("hi_agent_stage_completed_total")
_c_stage_failed = Counter("hi_agent_stage_failed_total")
_c_artifact_created = Counter("hi_agent_artifact_created_total")
_c_experiment_posted = Counter("hi_agent_experiment_posted_total")
_c_feedback_submitted = Counter("hi_agent_feedback_submitted_total")
_c_run_resumed = Counter("hi_agent_run_resumed_total")

# All 12 metric names for gate assertion
RUN_EVENT_METRIC_NAMES: frozenset[str] = frozenset({
    "hi_agent_run_submitted_total",
    "hi_agent_run_started_total",
    "hi_agent_run_completed_total",
    "hi_agent_run_failed_total",
    "hi_agent_run_cancelled_total",
    "hi_agent_stage_started_total",
    "hi_agent_stage_completed_total",
    "hi_agent_stage_failed_total",
    "hi_agent_artifact_created_total",
    "hi_agent_experiment_posted_total",
    "hi_agent_feedback_submitted_total",
    "hi_agent_run_resumed_total",
})

# Per-run event store (thread-safe)
_EVENTS_LOCK = threading.Lock()
_RUN_EVENTS: dict[str, list[dict[str, Any]]] = {}


def _append(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    entry = {"type": event_type, "ts": time.time(), **payload}
    with _EVENTS_LOCK:
        _RUN_EVENTS.setdefault(run_id, []).append(entry)


def get_run_events(run_id: str) -> list[dict[str, Any]]:
    """Return a copy of lifecycle events recorded for run_id."""
    with _EVENTS_LOCK:
        return [dict(e) for e in _RUN_EVENTS.get(run_id, [])]


def clear_run_events(run_id: str) -> None:
    """Drop lifecycle events for run_id (test isolation)."""
    with _EVENTS_LOCK:
        _RUN_EVENTS.pop(run_id, None)


class RunEventEmitter:
    """Typed run lifecycle event emitter satisfying Rule 7 (C8).

    Args:
        run_id: Identifier for the run being tracked.
        tenant_id: Tenant identifier for log attribution.
    """

    def __init__(self, run_id: str, tenant_id: str = "") -> None:
        self._run_id = run_id
        self._tenant_id = tenant_id

    # ------------------------------------------------------------------ #
    # Run-level events
    # ------------------------------------------------------------------ #

    def record_run_submitted(self) -> None:
        """Emit when a run is accepted into the queue."""
        _c_submitted.labels().inc()
        _logger.info(
            "run_event run_id=%s event=run_submitted tenant=%s",
            self._run_id, self._tenant_id,
        )
        _append(self._run_id, "run_submitted", {"tenant_id": self._tenant_id})

    def record_run_started(self) -> None:
        """Emit when a run transitions from queued/pending to running."""
        _c_started.labels().inc()
        _logger.info(
            "run_event run_id=%s event=run_started tenant=%s",
            self._run_id, self._tenant_id,
        )
        _append(self._run_id, "run_started", {"tenant_id": self._tenant_id})

    def record_run_completed(self, duration_ms: float = 0.0) -> None:
        """Emit when a run reaches the succeeded terminal state.

        Args:
            duration_ms: Wall-clock duration of the run in milliseconds.
        """
        _c_completed.labels().inc()
        _logger.info(
            "run_event run_id=%s event=run_completed duration_ms=%.1f tenant=%s",
            self._run_id, duration_ms, self._tenant_id,
        )
        _append(self._run_id, "run_completed", {
            "tenant_id": self._tenant_id,
            "duration_ms": duration_ms,
        })

    def record_run_failed(self, reason: str = "") -> None:
        """Emit when a run reaches the failed terminal state.

        Args:
            reason: Short descriptor of the failure cause.
        """
        _c_failed.labels(reason=reason or "unknown").inc()
        _logger.warning(
            "run_event run_id=%s event=run_failed reason=%s tenant=%s",
            self._run_id, reason, self._tenant_id,
        )
        _append(self._run_id, "run_failed", {
            "tenant_id": self._tenant_id,
            "reason": reason,
        })

    def record_run_cancelled(self, reason: str = "") -> None:
        """Emit when a run is cancelled (client request or system timeout).

        Args:
            reason: Short descriptor of the cancellation trigger.
        """
        _c_cancelled.labels(reason=reason or "unknown").inc()
        _logger.warning(
            "run_event run_id=%s event=run_cancelled reason=%s tenant=%s",
            self._run_id, reason, self._tenant_id,
        )
        _append(self._run_id, "run_cancelled", {
            "tenant_id": self._tenant_id,
            "reason": reason,
        })

    def record_run_resumed(self, from_stage: str = "") -> None:
        """Emit when a paused run is resumed.

        Args:
            from_stage: Stage ID at which the run is resuming.
        """
        _c_run_resumed.labels(from_stage=from_stage or "unknown").inc()
        _logger.info(
            "run_event run_id=%s event=run_resumed from_stage=%s tenant=%s",
            self._run_id, from_stage, self._tenant_id,
        )
        _append(self._run_id, "run_resumed", {
            "tenant_id": self._tenant_id,
            "from_stage": from_stage,
        })

    # ------------------------------------------------------------------ #
    # Stage-level events
    # ------------------------------------------------------------------ #

    def record_stage_started(self, stage_id: str = "") -> None:
        """Emit at the entry of each stage.

        Args:
            stage_id: Identifier of the stage starting.
        """
        _c_stage_started.labels(stage=stage_id or "unknown").inc()
        _logger.info(
            "run_event run_id=%s event=stage_started stage=%s tenant=%s",
            self._run_id, stage_id, self._tenant_id,
        )
        _append(self._run_id, "stage_started", {
            "tenant_id": self._tenant_id,
            "stage_id": stage_id,
        })

    def record_stage_completed(self, stage_id: str = "", duration_ms: float = 0.0) -> None:
        """Emit when a stage finishes successfully.

        Args:
            stage_id: Identifier of the stage that completed.
            duration_ms: Wall-clock duration of the stage in milliseconds.
        """
        _c_stage_completed.labels(stage=stage_id or "unknown").inc()
        _logger.info(
            "run_event run_id=%s event=stage_completed stage=%s duration_ms=%.1f tenant=%s",
            self._run_id, stage_id, duration_ms, self._tenant_id,
        )
        _append(self._run_id, "stage_completed", {
            "tenant_id": self._tenant_id,
            "stage_id": stage_id,
            "duration_ms": duration_ms,
        })

    def record_stage_failed(self, stage_id: str = "", reason: str = "") -> None:
        """Emit when a stage fails.

        Args:
            stage_id: Identifier of the failed stage.
            reason: Short descriptor of the failure cause.
        """
        _c_stage_failed.labels(stage=stage_id or "unknown", reason=reason or "unknown").inc()
        _logger.warning(
            "run_event run_id=%s event=stage_failed stage=%s reason=%s tenant=%s",
            self._run_id, stage_id, reason, self._tenant_id,
        )
        _append(self._run_id, "stage_failed", {
            "tenant_id": self._tenant_id,
            "stage_id": stage_id,
            "reason": reason,
        })

    # ------------------------------------------------------------------ #
    # Artifact / evolution events
    # ------------------------------------------------------------------ #

    def record_artifact_created(self, artifact_type: str = "") -> None:
        """Emit when an artifact is registered in the ledger.

        Args:
            artifact_type: Type tag of the artifact (e.g. 'code', 'report').
        """
        _c_artifact_created.labels(artifact_type=artifact_type or "unknown").inc()
        _logger.info(
            "run_event run_id=%s event=artifact_created type=%s tenant=%s",
            self._run_id, artifact_type, self._tenant_id,
        )
        _append(self._run_id, "artifact_created", {
            "tenant_id": self._tenant_id,
            "artifact_type": artifact_type,
        })

    def record_experiment_posted(self, experiment_id: str = "") -> None:
        """Emit when an experiment result is posted (OpPoller → RunManager).

        Args:
            experiment_id: The op_id / external_id of the experiment.
        """
        _c_experiment_posted.labels().inc()
        _logger.info(
            "run_event run_id=%s event=experiment_posted experiment_id=%s tenant=%s",
            self._run_id, experiment_id, self._tenant_id,
        )
        _append(self._run_id, "experiment_posted", {
            "tenant_id": self._tenant_id,
            "experiment_id": experiment_id,
        })

    def record_feedback_submitted(self) -> None:
        """Emit when human feedback is submitted for this run."""
        _c_feedback_submitted.labels().inc()
        _logger.info(
            "run_event run_id=%s event=feedback_submitted tenant=%s",
            self._run_id, self._tenant_id,
        )
        _append(self._run_id, "feedback_submitted", {"tenant_id": self._tenant_id})


__all__ = [
    "RUN_EVENT_METRIC_NAMES",
    "RunEventEmitter",
    "clear_run_events",
    "get_run_events",
]
