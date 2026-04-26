"""Wave 11 seed: unified identity context for a run execution.

Carries the full tenant/project/run/stage spine so durable-write callers
can derive every persistent record's identity fields from one place.
Today only declared and unit-tested; later waves will plumb it through
RunFeedback, SkillObservation, GateContext, RunQueue, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RunExecutionContext:
    """Frozen identity bundle for a single run execution.

    Every persistent record (RunFeedback, SkillObservation, StoredEvent,
    GateContext, RunQueue row, ArtifactRecord, etc.) should be derivable
    from this context plus the record-specific business fields. Missing
    fields default to ``""`` to support gradual rollout, but callers
    constructing a RunExecutionContext for a research/prod write path
    must populate at minimum ``tenant_id`` and ``run_id`` per Rule 12.
    """

    tenant_id: str = ""
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""
    profile_id: str = ""
    run_id: str = ""
    parent_run_id: str = ""
    stage_id: str = ""
    capability_name: str = ""
    request_id: str = ""

    def with_stage(self, stage_id: str) -> RunExecutionContext:
        """Return a copy bound to a different stage_id."""
        return replace(self, stage_id=stage_id)

    def with_capability(self, capability_name: str) -> RunExecutionContext:
        """Return a copy bound to a different capability_name."""
        return replace(self, capability_name=capability_name)

    def to_spine_kwargs(self) -> dict[str, str]:
        """Return the four-field spine subset used by current durable writers.

        Existing Wave 10/10.1/10.2 store APIs accept ``tenant_id``, ``user_id``,
        ``session_id``, ``project_id`` as kwargs. Use this until callers are
        migrated to accept the full RunExecutionContext.
        """
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
        }
