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
    # W34-F.2 (B-W34-1): attempt_id / phase_id are part of the run-execution
    # spine. ``attempt_id`` is the per-attempt stable identifier (each retry of
    # the same run gets a fresh UUID); ``phase_id`` is the TRACE phase tag
    # (intake/execute/finalize/...). They mirror the StoredEvent + RunRecord
    # storage spine landed in W33-F.1 so durable writers can derive every
    # persistent record's lineage from one place.
    attempt_id: str = ""
    phase_id: str = ""
    stage_id: str = ""
    capability_name: str = ""
    request_id: str = ""

    def with_stage(self, stage_id: str) -> RunExecutionContext:
        """Return a copy bound to a different stage_id."""
        return replace(self, stage_id=stage_id)

    def with_capability(self, capability_name: str) -> RunExecutionContext:
        """Return a copy bound to a different capability_name."""
        return replace(self, capability_name=capability_name)

    def with_phase(self, phase_id: str) -> RunExecutionContext:
        """Return a copy bound to a different phase_id (W34-F.2)."""
        return replace(self, phase_id=phase_id)

    def with_attempt(self, attempt_id: str, parent_run_id: str = "") -> RunExecutionContext:
        """Return a copy bound to a fresh attempt (W34-F.2).

        On run recovery / re-lease the executor calls this to mint a new
        ``attempt_id``. ``parent_run_id`` defaults to the existing
        ``run_id`` when the caller does not override, so the lineage chain
        can be reconstructed from persisted records alone.
        """
        if not parent_run_id:
            parent_run_id = self.run_id or self.parent_run_id
        return replace(self, attempt_id=attempt_id, parent_run_id=parent_run_id)

    def to_spine_kwargs(self) -> dict[str, str]:
        """Return the four-field spine subset used by current durable writers."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
        }

    def to_spine_kwargs_full(self) -> dict[str, str]:
        """Return all 12 identity fields as strings (W34-F.2 added attempt_id, phase_id)."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "attempt_id": self.attempt_id,
            "phase_id": self.phase_id,
            "stage_id": self.stage_id,
            "capability_name": self.capability_name,
            "request_id": self.request_id,
        }

    def to_lineage_kwargs(self) -> dict[str, str]:
        """Return only the lineage-spine subset (W34-F.2).

        Used when a durable writer (RunRecord upsert, StoredEvent append,
        ReasoningTrace persistence) needs ``parent_run_id`` / ``attempt_id``
        / ``phase_id`` as a contiguous block.
        """
        return {
            "parent_run_id": self.parent_run_id,
            "attempt_id": self.attempt_id,
            "phase_id": self.phase_id,
        }

    @classmethod
    def from_managed_run(cls, run: ManagedRun) -> RunExecutionContext:
        """Build a RunExecutionContext from a ManagedRun instance.

        W34-F.2: lineage fields are read from the ManagedRun spine (no longer
        hardcoded as empty strings). When ``run`` does not yet carry a value
        the field defaults remain empty — callers running under research/prod
        posture should ensure ``ManagedRun`` is constructed with non-empty
        ``attempt_id`` and ``parent_run_id`` before invoking this factory.
        """
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
            profile_id=getattr(run, "profile_id", "") or "",
            parent_run_id=getattr(run, "parent_run_id", "") or "",
            attempt_id=getattr(run, "attempt_id", "") or "",
            phase_id=getattr(run, "phase_id", "") or "",
            stage_id=getattr(run, "current_stage", "") or "",
            capability_name="",
            request_id="",
        )
