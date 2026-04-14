"""Skill evolution: optimize prompts and create new skills from experience.

Two evolution modes:
1. OPTIMIZE: Improve existing skill's prompt based on failure analysis
   (agent-core textual gradient pattern)
2. CREATE: Generate new skills from patterns in execution history
   (ECC instinct -> evolve pattern)

The evolution loop:
  observations -> metrics -> evaluate -> optimize/create -> version -> A/B test
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from hi_agent.skill.definition import SkillDefinition
from hi_agent.skill.observer import SkillObserver
from hi_agent.skill.version import SkillVersionManager, SkillVersionRecord
from hi_agent.failures.taxonomy import is_budget_exhausted_failure_code

if TYPE_CHECKING:
    from hi_agent.llm.protocol import LLMGateway


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SkillAnalysis:
    """Result of analyzing a skill's performance."""

    skill_id: str
    total_executions: int
    success_rate: float
    avg_quality: float
    top_failures: list[str]
    optimization_needed: bool
    suggestions: list[str]


@dataclass
class SkillPattern:
    """A recurring pattern discovered from observation history."""

    pattern_id: str
    description: str
    occurrences: int
    task_families: list[str]
    stages: list[str]
    tool_sequence: list[str]
    confidence: float
    source_sessions: list[str]


@dataclass
class EvolutionReport:
    """Report from a full evolution cycle."""

    skills_analyzed: int
    skills_optimized: int
    patterns_discovered: int
    skills_created: int
    challenger_deployed: int
    details: list[str]


# ---------------------------------------------------------------------------
# Heuristic prompt improvement templates
# ---------------------------------------------------------------------------

_FAILURE_FIXES: dict[str, str] = {
    "missing_evidence": (
        "Add explicit instructions to gather all required evidence before proceeding."
    ),
    "invalid_context": (
        "Add context validation step at the start of the prompt."
    ),
    "model_output_invalid": (
        "Add output format constraints and examples to the prompt."
    ),
    "model_refusal": (
        "Rephrase instructions to avoid triggering safety refusals."
    ),
    "no_progress": (
        "Add a fallback strategy section for when the primary approach stalls."
    ),
}

_BUDGET_FAILURE_FIX = (
    "Add token-efficiency instructions: be concise, avoid repetition."
)

# ---------------------------------------------------------------------------
# SkillEvolver
# ---------------------------------------------------------------------------


class SkillEvolver:
    """Evolves skills through observation-driven optimization."""

    def __init__(
        self,
        observer: SkillObserver | None = None,
        version_manager: SkillVersionManager | None = None,
        llm_gateway: Any | None = None,
        champion_challenger: Any | None = None,
        success_threshold: float = 0.70,
        min_pattern_occurrences: int = 3,
    ) -> None:
        """Initialize SkillEvolver.

        Args:
            observer: Skill observation telemetry source.
            version_manager: Manages skill version records.
            llm_gateway: Optional LLM gateway for deeper optimization.
            champion_challenger: Optional ChampionChallenger instance to
                register newly deployed challengers for A/B comparison.
            success_threshold: Success rate below which optimization is triggered.
            min_pattern_occurrences: Minimum occurrences for a pattern to be reported.
        """
        self._observer = observer
        self._version_manager = version_manager
        self._llm: LLMGateway | None = llm_gateway
        self._champion_challenger = champion_challenger
        self._success_threshold = success_threshold
        self._min_pattern_occurrences = min_pattern_occurrences

    @classmethod
    def from_config(
        cls,
        cfg: Any,
        llm_gateway: Any | None = None,
        observer: Any | None = None,
        version_manager: Any | None = None,
    ) -> "SkillEvolver":
        """Create a SkillEvolver from a TraceConfig."""
        return cls(
            observer=observer,
            version_manager=version_manager,
            llm_gateway=llm_gateway,
            success_threshold=cfg.skill_evolver_success_threshold,
            min_pattern_occurrences=cfg.skill_evolver_min_pattern_occurrences,
        )

    # --- Analyze ---

    def analyze_skill(self, skill_id: str) -> SkillAnalysis:
        """Analyze a skill's performance from observations."""
        metrics = self._observer.get_metrics(skill_id)
        top_failures = list(metrics.failure_patterns[:5])

        suggestions: list[str] = []
        for code in top_failures:
            fix = self._suggestion_for_failure_code(code)
            if fix and fix not in suggestions:
                suggestions.append(fix)

        if metrics.avg_quality > 0 and metrics.avg_quality < 0.5:
            suggestions.append(
                "Quality score is low — consider adding more detailed instructions."
            )

        optimization_needed = metrics.success_rate < self._success_threshold

        return SkillAnalysis(
            skill_id=skill_id,
            total_executions=metrics.total_executions,
            success_rate=metrics.success_rate,
            avg_quality=metrics.avg_quality,
            top_failures=top_failures,
            optimization_needed=optimization_needed,
            suggestions=suggestions,
        )

    # --- Optimize existing skills ---

    def optimize_prompt(self, skill_id: str) -> str | None:
        """Generate optimized prompt using textual gradient pattern.

        With LLM: full textual gradient analysis.
        Without LLM: heuristic template-based fixes.
        Returns new prompt text, or None if no improvement needed.
        """
        analysis = self.analyze_skill(skill_id)
        if not analysis.optimization_needed:
            return None

        champion = self._version_manager.get_champion(skill_id)
        current_prompt = champion.prompt_content if champion else ""

        # Try LLM-based optimization
        if self._llm is not None:
            try:
                return self._llm_optimize(skill_id, current_prompt, analysis)
            except Exception:
                pass  # fall through to heuristic

        # Heuristic optimization
        return self._heuristic_optimize(current_prompt, analysis)

    def _llm_optimize(
        self,
        skill_id: str,
        current_prompt: str,
        analysis: SkillAnalysis,
    ) -> str:
        """Use LLM for textual gradient optimization."""
        from hi_agent.llm.protocol import LLMRequest

        # Get failed observations for context
        observations = self._observer.get_observations(skill_id, limit=20)
        failed_obs = [o for o in observations if not o.success]
        failure_examples = "\n".join(
            f"- [{o.failure_code}] input={o.input_summary[:100]}, "
            f"output={o.output_summary[:100]}"
            for o in failed_obs[:5]
        )

        prompt = (
            "You are optimizing a skill prompt. Here is the current prompt:\n\n"
            f"```\n{current_prompt}\n```\n\n"
            f"Success rate: {analysis.success_rate:.1%}\n"
            f"Top failure codes: {', '.join(analysis.top_failures)}\n"
            f"Recent failures:\n{failure_examples}\n\n"
            "Rewrite the prompt to address these failures while preserving "
            "the core functionality. Return ONLY the improved prompt text."
        )

        assert self._llm is not None
        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert prompt engineer.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        response = self._llm.complete(request)
        content = response.content
        if not content or not content.strip():
            logger.warning(
                "SkillEvolver._llm_optimize: LLM returned empty prompt for skill %r, "
                "discarding result",
                getattr(analysis, "skill_id", "unknown"),
            )
            return None
        return content

    def _heuristic_optimize(
        self,
        current_prompt: str,
        analysis: SkillAnalysis,
    ) -> str:
        """Apply heuristic fixes based on failure patterns."""
        additions: list[str] = []
        for code in analysis.top_failures:
            fix = self._suggestion_for_failure_code(code)
            if fix:
                additions.append(f"- {fix}")

        for suggestion in analysis.suggestions:
            if suggestion not in additions:
                additions.append(f"- {suggestion}")

        if not additions:
            additions.append(
                "- Review the task requirements carefully before proceeding."
            )

        improvement_block = (
            "\n\n## Improvement Notes\n"
            + "\n".join(additions)
        )
        return current_prompt + improvement_block

    @staticmethod
    def _suggestion_for_failure_code(code: str) -> str | None:
        """Map a failure code to a prompt improvement suggestion."""
        if is_budget_exhausted_failure_code(code):
            return _BUDGET_FAILURE_FIX
        return _FAILURE_FIXES.get(code)

    def deploy_optimization(
        self, skill_id: str, new_prompt: str
    ) -> SkillVersionRecord:
        """Deploy optimized prompt as challenger version for A/B testing."""
        record = self._version_manager.create_version(
            skill_id=skill_id,
            prompt_content=new_prompt,
        )
        self._version_manager.set_challenger(skill_id, record.version)

        # Register the new challenger (and current champion) with
        # ChampionChallenger so the evolve engine can track A/B metrics.
        if self._champion_challenger is not None:
            try:
                champion = self._version_manager.get_champion(skill_id)
                if champion is not None:
                    self._champion_challenger.register_champion(
                        scope=skill_id,
                        version=champion.version,
                        metrics={},
                    )
                self._champion_challenger.register_challenger(
                    scope=skill_id,
                    version=record.version,
                    metrics={},
                )
            except Exception:
                pass  # Never crash the deploy path

        return record

    # --- Discover patterns ---

    def discover_patterns(
        self, min_occurrences: int | None = None
    ) -> list[SkillPattern]:
        """Analyze observation history to find recurring patterns.

        Looks for:
        - Common task_family + stage combinations
        - Repeated tag sequences
        - Successful strategies across multiple sessions
        """
        if min_occurrences is None:
            min_occurrences = self._min_pattern_occurrences
        all_metrics = self._observer.get_all_metrics()
        if not all_metrics:
            return []

        # Group observations by task_family + stage
        family_stage_counts: dict[str, dict[str, Any]] = {}

        for skill_id, _metrics in all_metrics.items():
            observations = self._observer.get_observations(skill_id, limit=1000)
            for obs in observations:
                if not obs.success:
                    continue
                key = f"{obs.task_family}::{obs.stage_id}"
                if key not in family_stage_counts:
                    family_stage_counts[key] = {
                        "count": 0,
                        "task_families": set(),
                        "stages": set(),
                        "tags": [],
                        "run_ids": set(),
                    }
                bucket = family_stage_counts[key]
                bucket["count"] += 1
                bucket["task_families"].add(obs.task_family)
                bucket["stages"].add(obs.stage_id)
                bucket["tags"].extend(obs.tags)
                bucket["run_ids"].add(obs.run_id)

        patterns: list[SkillPattern] = []
        for key, bucket in family_stage_counts.items():
            if bucket["count"] >= min_occurrences:
                # Deduplicate tags to approximate a tool sequence
                tag_counts: dict[str, int] = {}
                for t in bucket["tags"]:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
                sorted_tags = sorted(
                    tag_counts.keys(), key=lambda t: tag_counts[t], reverse=True
                )

                pattern_id = (
                    f"pat_{hashlib.sha256(key.encode()).hexdigest()[:12]}"
                )
                confidence = min(bucket["count"] / 10.0, 1.0)

                patterns.append(
                    SkillPattern(
                        pattern_id=pattern_id,
                        description=(
                            f"Recurring successful pattern for {key} "
                            f"({bucket['count']} occurrences)"
                        ),
                        occurrences=bucket["count"],
                        task_families=sorted(bucket["task_families"]),
                        stages=sorted(bucket["stages"]),
                        tool_sequence=sorted_tags[:10],
                        confidence=confidence,
                        source_sessions=sorted(bucket["run_ids"]),
                    )
                )

        patterns.sort(key=lambda p: p.occurrences, reverse=True)
        return patterns

    # --- Create new skills ---

    def create_skill_from_pattern(
        self, pattern: SkillPattern
    ) -> SkillDefinition | None:
        """Generate a new skill definition from a discovered pattern.

        With LLM: generate full SKILL.md content.
        Without LLM: template-based generation from pattern data.
        """
        if self._llm is not None:
            try:
                return self._llm_create_skill(pattern)
            except Exception:
                pass  # fall through to template

        return self._template_create_skill(pattern)

    def _llm_create_skill(self, pattern: SkillPattern) -> SkillDefinition:
        """Use LLM to generate a skill definition from a pattern."""
        from hi_agent.llm.protocol import LLMRequest

        prompt = (
            "Create a reusable skill definition from this observed pattern:\n\n"
            f"Description: {pattern.description}\n"
            f"Task families: {', '.join(pattern.task_families)}\n"
            f"Stages: {', '.join(pattern.stages)}\n"
            f"Tool sequence: {', '.join(pattern.tool_sequence)}\n"
            f"Occurrences: {pattern.occurrences}\n\n"
            "Generate a skill prompt that formalizes this pattern. "
            "Return ONLY the prompt text."
        )

        assert self._llm is not None
        request = LLMRequest(
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at creating reusable agent skills.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        response = self._llm.complete(request)

        now = datetime.now(UTC).isoformat()
        skill_id = f"evolved_{pattern.pattern_id}"
        name = f"pattern-{pattern.pattern_id[:8]}"
        scope = pattern.task_families[0] if pattern.task_families else "*"

        return SkillDefinition(
            skill_id=skill_id,
            name=name,
            version="0.1.0",
            description=pattern.description,
            when_to_use=f"When working on {scope} tasks in stages: {', '.join(pattern.stages)}",
            prompt_content=response.content,
            tags=list(pattern.tool_sequence[:5]),
            lifecycle_stage="candidate",
            confidence=pattern.confidence,
            source="evolved",
            created_at=now,
            updated_at=now,
        )

    def _template_create_skill(self, pattern: SkillPattern) -> SkillDefinition:
        """Create a skill definition using templates."""
        now = datetime.now(UTC).isoformat()
        skill_id = f"evolved_{pattern.pattern_id}"
        name = f"pattern-{pattern.pattern_id[:8]}"
        scope = pattern.task_families[0] if pattern.task_families else "*"

        prompt_lines: list[str] = [
            f"# {name}",
            "",
            "## Description",
            f"{pattern.description}",
            "",
            "## Applicable Context",
            f"- Task families: {', '.join(pattern.task_families)}",
            f"- Stages: {', '.join(pattern.stages)}",
            "",
            "## Procedure",
        ]

        for i, tool in enumerate(pattern.tool_sequence, 1):
            prompt_lines.append(f"{i}. Execute: {tool}")

        prompt_lines.extend([
            "",
            "## Quality Checks",
            "- Verify each step completed successfully before proceeding",
            "- If a step fails, report the failure and stop",
        ])

        return SkillDefinition(
            skill_id=skill_id,
            name=name,
            version="0.1.0",
            description=pattern.description,
            when_to_use=f"When working on {scope} tasks in stages: {', '.join(pattern.stages)}",
            prompt_content="\n".join(prompt_lines),
            tags=list(pattern.tool_sequence[:5]),
            lifecycle_stage="candidate",
            confidence=pattern.confidence,
            source="evolved",
            created_at=now,
            updated_at=now,
        )

    # --- Full evolution cycle ---

    def evolve_cycle(
        self, min_observations: int = 10
    ) -> EvolutionReport:
        """Run a full evolution cycle.

        1. Analyze all skills with enough observations
        2. Optimize underperforming skills (success_rate < threshold)
        3. Discover new patterns
        4. Create skills from strong patterns
        5. Return report of actions taken
        """
        all_metrics = self._observer.get_all_metrics()
        details: list[str] = []
        skills_analyzed = 0
        skills_optimized = 0
        challenger_deployed = 0
        patterns_discovered = 0
        skills_created = 0

        # 1-2. Analyze and optimize
        for skill_id, metrics in all_metrics.items():
            if metrics.total_executions < min_observations:
                continue

            skills_analyzed += 1
            analysis = self.analyze_skill(skill_id)

            if analysis.optimization_needed:
                new_prompt = self.optimize_prompt(skill_id)
                if new_prompt is not None:
                    self.deploy_optimization(skill_id, new_prompt)
                    skills_optimized += 1
                    challenger_deployed += 1
                    details.append(
                        f"Optimized '{skill_id}' "
                        f"(success_rate={analysis.success_rate:.1%})"
                    )

        # 3. Discover patterns
        patterns = self.discover_patterns()
        patterns_discovered = len(patterns)
        for pattern in patterns:
            details.append(
                f"Pattern '{pattern.pattern_id}': {pattern.description}"
            )

        # 4. Create skills from strong patterns
        for pattern in patterns:
            if pattern.confidence >= 0.5:
                skill_def = self.create_skill_from_pattern(pattern)
                if skill_def is not None:
                    skills_created += 1
                    details.append(
                        f"Created skill '{skill_def.name}' from pattern"
                    )

        return EvolutionReport(
            skills_analyzed=skills_analyzed,
            skills_optimized=skills_optimized,
            patterns_discovered=patterns_discovered,
            skills_created=skills_created,
            challenger_deployed=challenger_deployed,
            details=details,
        )
