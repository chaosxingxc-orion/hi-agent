"""Unified identity context for a run execution.

Carries the full tenant/project/run/stage spine so durable-write callers
can derive every persistent record's identity fields from one place.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hi_agent.server.run_manager import ManagedRun


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

    tenant_id: str = ""  # scope: process-internal
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
        """Return the four-field spine subset used by current durable writers."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
        }

    def to_spine_kwargs_full(self) -> dict[str, str]:
        """Return all 10 identity fields as strings."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "stage_id": self.stage_id,
            "capability_name": self.capability_name,
            "request_id": self.request_id,
        }

    @classmethod
    def from_managed_run(cls, run: ManagedRun) -> RunExecutionContext:
        """Build a RunExecutionContext from a ManagedRun instance."""
        from hi_agent.server.run_manager import ManagedRun as _ManagedRun  # noqa: F401  expiry_wave: permanent

        project_id = (
            getattr(run, "project_id", "") or
            (getattr(run, "task_contract", {}) or {}).get("project_id", "") or
            ""
        )
        return cls(
            tenant_id=getattr(run, "tenant_id", "") or "",
            user_id=getattr(run, "user_id", "") or "",
            session_id=getattr(run, "session_id", "") or "",
            project_id=project_id,
            run_id=run.run_id,
            profile_id="",
            parent_run_id="",
            stage_id="",
            capability_name="",
            request_id="",
        )
