"""Build EpisodeRecord from completed run data."""

from __future__ import annotations

from datetime import UTC, datetime

from hi_agent.contracts.memory import StageSummary
from hi_agent.contracts.task import TaskContract
from hi_agent.memory.episodic import EpisodeRecord
from hi_agent.memory.l1_compressed import CompressedStageMemory


class EpisodeBuilder:
    """Builds EpisodeRecord from a completed run's memory layers.

    Extracts key findings from L1 compressed memories,
    key decisions from stage summaries, and compiles into
    a persistent episode record.
    """

    def build(
        self,
        run_id: str,
        task_contract: TaskContract,
        stage_summaries: dict[str, StageSummary],
        l1_memories: list[CompressedStageMemory] | None = None,
        outcome: str = "completed",
        failure_codes: list[str] | None = None,
        duration_seconds: float = 0.0,
    ) -> EpisodeRecord:
        """Build episode from run artifacts.

        Parameters
        ----------
        run_id:
            Unique run identifier.
        task_contract:
            The task contract governing this run.
        stage_summaries:
            Mapping of stage_id -> StageSummary from the run.
        l1_memories:
            Optional L1 compressed stage memories for richer extraction.
        outcome:
            Run outcome: ``"completed"``, ``"failed"``, or ``"aborted"``.
        failure_codes:
            Failure codes collected during the run.
        duration_seconds:
            Total wall-clock duration of the run.

        Returns:
        -------
        EpisodeRecord
            A self-contained episode ready for persistent storage.
        """
        stages_completed = list(stage_summaries.keys())

        # Extract findings: prefer L1 memories, fall back to stage summaries
        key_findings = self._extract_findings(stage_summaries, l1_memories)

        # Extract decisions from stage summaries
        key_decisions = self._extract_decisions(stage_summaries, l1_memories)

        return EpisodeRecord(
            run_id=run_id,
            task_id=task_contract.task_id,
            task_family=task_contract.task_family,
            goal=task_contract.goal,
            outcome=outcome,
            stages_completed=stages_completed,
            key_findings=key_findings,
            key_decisions=key_decisions,
            failure_codes=failure_codes or [],
            duration_seconds=duration_seconds,
            timestamp=datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def _extract_findings(
        stage_summaries: dict[str, StageSummary],
        l1_memories: list[CompressedStageMemory] | None,
    ) -> list[str]:
        """Extract key findings, preferring L1 compressed data."""
        findings: list[str] = []

        if l1_memories:
            for mem in l1_memories:
                findings.extend(mem.findings)
        else:
            for summary in stage_summaries.values():
                findings.extend(summary.findings)

        return findings

    @staticmethod
    def _extract_decisions(
        stage_summaries: dict[str, StageSummary],
        l1_memories: list[CompressedStageMemory] | None,
    ) -> list[str]:
        """Extract key decisions from stage summaries and L1 memories."""
        decisions: list[str] = []

        # Always collect from stage summaries first
        for summary in stage_summaries.values():
            decisions.extend(summary.decisions)

        # Supplement with L1 memory decisions if available
        if l1_memories:
            summary_decision_set = set(decisions)
            for mem in l1_memories:
                for d in mem.decisions:
                    if d not in summary_decision_set:
                        decisions.append(d)
                        summary_decision_set.add(d)

        return decisions
