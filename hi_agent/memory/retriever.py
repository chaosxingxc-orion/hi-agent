"""Unified memory retrieval for Task View assembly."""

from __future__ import annotations

from hi_agent.memory.episodic import EpisodeRecord, EpisodicMemoryStore


class MemoryRetriever:
    """Unified retrieval across working and episodic memory.

    Used by Task View builder to assemble relevant memory context.
    Prioritizes: current run L1/L2 > recent episodes > similar past failures.
    """

    def __init__(
        self,
        episodic_store: EpisodicMemoryStore | None = None,
    ) -> None:
        """Initialize MemoryRetriever."""
        self._episodic = episodic_store

    def retrieve_for_stage(
        self,
        task_family: str,
        stage_id: str,
        current_failures: list[str] | None = None,
        budget_tokens: int = 2000,
    ) -> list[str]:
        """Retrieve relevant memory snippets for the current stage.

        Returns formatted strings within an approximate token budget.
        Token estimation uses a simple character-based heuristic
        (1 token ~ 4 characters).
        """
        if self._episodic is None:
            return []

        snippets: list[str] = []
        remaining_chars = budget_tokens * 4  # rough chars budget

        # 1. Successful patterns from the same task family
        successes = self._episodic.get_successful_patterns(task_family, limit=3)
        for ep in successes:
            snippet = self._format_episode(ep, prefix="[success]")
            if len(snippet) > remaining_chars:
                break
            snippets.append(snippet)
            remaining_chars -= len(snippet)

        # 2. Similar failures if the current run has failure codes
        if current_failures:
            failures = self._episodic.get_similar_failures(current_failures, limit=3)
            for ep in failures:
                snippet = self._format_episode(ep, prefix="[past-failure]")
                if len(snippet) > remaining_chars:
                    break
                snippets.append(snippet)
                remaining_chars -= len(snippet)

        # 3. Recent episodes from same family (that weren't already included)
        seen_ids = {s.split("run=")[1].split("]")[0] for s in snippets if "run=" in s}
        recent = self._episodic.query(task_family=task_family, limit=3)
        for ep in recent:
            if ep.run_id in seen_ids:
                continue
            snippet = self._format_episode(ep, prefix="[recent]")
            if len(snippet) > remaining_chars:
                break
            snippets.append(snippet)
            remaining_chars -= len(snippet)

        return snippets

    def retrieve_similar_episodes(
        self,
        task_family: str,
        failure_codes: list[str] | None = None,
        limit: int = 3,
    ) -> list[EpisodeRecord]:
        """Retrieve similar episodes combining family match and failure overlap."""
        if self._episodic is None:
            return []

        results: list[EpisodeRecord] = []
        seen: set[str] = set()

        # Failure-based similarity
        if failure_codes:
            for ep in self._episodic.get_similar_failures(failure_codes, limit=limit):
                if ep.run_id not in seen:
                    results.append(ep)
                    seen.add(ep.run_id)

        # Family-based recent episodes
        for ep in self._episodic.query(task_family=task_family, limit=limit):
            if ep.run_id not in seen:
                results.append(ep)
                seen.add(ep.run_id)

        return results[:limit]

    @staticmethod
    def _format_episode(episode: EpisodeRecord, prefix: str = "") -> str:
        """Format an episode record into a compact readable snippet."""
        lines = [
            f"{prefix} [run={episode.run_id}] {episode.outcome}: {episode.goal}",
        ]
        if episode.key_findings:
            findings_str = "; ".join(episode.key_findings[:3])
            lines.append(f"  findings: {findings_str}")
        if episode.key_decisions:
            decisions_str = "; ".join(episode.key_decisions[:3])
            lines.append(f"  decisions: {decisions_str}")
        if episode.failure_codes:
            lines.append(f"  failures: {', '.join(episode.failure_codes)}")
        return "\n".join(lines)
