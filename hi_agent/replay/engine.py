"""Minimal deterministic replay engine."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import ClassVar

from hi_agent.events import EventEnvelope


@dataclass(slots=True)
class ReplayReport:
    """Summary reconstructed from a run event stream."""

    stage_states: dict[str, str] = field(default_factory=dict)
    task_view_count: int = 0
    success: bool = False


class ReplayEngine:
    """Fold event envelopes into a deterministic replay report."""

    _failure_events: ClassVar[set[str]] = {"ActionExecutionFailed", "StageFailed"}

    def replay(self, events: Iterable[EventEnvelope]) -> ReplayReport:
        """Reconstruct a replay report from an ordered event stream."""
        report = ReplayReport()
        saw_terminal_state = False

        for envelope in events:
            event_type = envelope.event_type
            payload = envelope.payload or {}

            if event_type == "StageStateChanged":
                stage_id = payload.get("stage_id")
                to_state = payload.get("to_state")
                if stage_id is None or to_state is None:
                    continue
                state_text = str(to_state)
                report.stage_states[str(stage_id)] = state_text
                if state_text == "failed":
                    saw_terminal_state = True
                    report.success = False
                continue

            if event_type == "TaskViewRecorded":
                report.task_view_count += 1
                continue

            if event_type in self._failure_events:
                report.success = False
                saw_terminal_state = True

        if report.stage_states and not saw_terminal_state:
            report.success = all(state == "completed" for state in report.stage_states.values())

        return report
