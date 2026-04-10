"""Skill execution observer for async, non-blocking telemetry.

Inspired by ECC continuous-learning-v2 hooks: capture every skill
execution with inputs/outputs/metrics WITHOUT blocking the execution.

Observations are appended to a JSONL file (like ECC's observations.jsonl).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field

_MAX_SUMMARY_LEN = 500


@dataclass
class SkillObservation:
    """A single skill execution observation."""

    observation_id: str
    skill_id: str
    skill_version: str
    run_id: str
    stage_id: str
    timestamp: str
    # Execution data
    success: bool
    input_summary: str = ""
    output_summary: str = ""
    quality_score: float | None = None
    tokens_used: int = 0
    latency_ms: int = 0
    failure_code: str | None = None
    # Context
    task_family: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Truncate summaries to max length."""
        if len(self.input_summary) > _MAX_SUMMARY_LEN:
            self.input_summary = self.input_summary[:_MAX_SUMMARY_LEN]
        if len(self.output_summary) > _MAX_SUMMARY_LEN:
            self.output_summary = self.output_summary[:_MAX_SUMMARY_LEN]


@dataclass
class SkillMetrics:
    """Aggregated metrics for a skill version."""

    skill_id: str
    total_executions: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    avg_quality: float = 0.0
    avg_tokens: float = 0.0
    avg_latency_ms: float = 0.0
    failure_patterns: list[str] = field(default_factory=list)
    # Per-version breakdown
    version_stats: dict[str, dict] = field(default_factory=dict)


def make_observation_id() -> str:
    """Generate a unique observation id."""
    return f"obs_{uuid.uuid4().hex[:12]}"


class SkillObserver:
    """Non-blocking skill execution observer.

    Appends observations to JSONL file. Thread-safe via lock.
    Does NOT block skill execution -- fire-and-forget pattern.
    """

    def __init__(self, storage_dir: str = ".hi_agent/skill_observations") -> None:
        """Initialize SkillObserver."""
        self._storage_dir = storage_dir
        self._lock = threading.Lock()

    def observe(self, obs: SkillObservation) -> None:
        """Record an observation. Non-blocking, thread-safe."""
        with self._lock:
            os.makedirs(self._storage_dir, exist_ok=True)
            path = os.path.join(self._storage_dir, f"{obs.skill_id}.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(obs), default=str) + "\n")

    def get_observations(
        self, skill_id: str, limit: int = 100
    ) -> list[SkillObservation]:
        """Load observations for a skill from disk."""
        path = os.path.join(self._storage_dir, f"{skill_id}.jsonl")
        if not os.path.exists(path):
            return []

        observations: list[SkillObservation] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                observations.append(SkillObservation(**data))

        # Return most recent observations up to limit
        return observations[-limit:]

    def get_metrics(self, skill_id: str) -> SkillMetrics:
        """Aggregate metrics for a skill from observations."""
        observations = self.get_observations(skill_id, limit=10000)
        return _aggregate_metrics(skill_id, observations)

    def get_all_metrics(self) -> dict[str, SkillMetrics]:
        """Aggregate metrics for all observed skills."""
        result: dict[str, SkillMetrics] = {}
        if not os.path.exists(self._storage_dir):
            return result

        for filename in os.listdir(self._storage_dir):
            if filename.endswith(".jsonl"):
                skill_id = filename[:-6]  # strip .jsonl
                result[skill_id] = self.get_metrics(skill_id)

        return result


def _aggregate_metrics(
    skill_id: str, observations: list[SkillObservation]
) -> SkillMetrics:
    """Compute aggregated metrics from a list of observations."""
    metrics = SkillMetrics(skill_id=skill_id)
    if not observations:
        return metrics

    metrics.total_executions = len(observations)
    metrics.success_count = sum(1 for o in observations if o.success)
    metrics.failure_count = metrics.total_executions - metrics.success_count
    metrics.success_rate = (
        metrics.success_count / metrics.total_executions
        if metrics.total_executions > 0
        else 0.0
    )

    # Average quality (only from observations that have a score)
    quality_scores = [
        o.quality_score for o in observations if o.quality_score is not None
    ]
    metrics.avg_quality = (
        sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    )

    # Average tokens
    token_values = [o.tokens_used for o in observations]
    metrics.avg_tokens = (
        sum(token_values) / len(token_values) if token_values else 0.0
    )

    # Average latency
    latency_values = [o.latency_ms for o in observations]
    metrics.avg_latency_ms = (
        sum(latency_values) / len(latency_values) if latency_values else 0.0
    )

    # Top failure codes
    failure_codes: dict[str, int] = {}
    for o in observations:
        if o.failure_code:
            failure_codes[o.failure_code] = failure_codes.get(o.failure_code, 0) + 1
    sorted_codes = sorted(failure_codes.items(), key=lambda x: x[1], reverse=True)
    metrics.failure_patterns = [code for code, _ in sorted_codes[:5]]

    # Per-version breakdown
    version_buckets: dict[str, list[SkillObservation]] = {}
    for o in observations:
        version_buckets.setdefault(o.skill_version, []).append(o)

    for ver, ver_obs in version_buckets.items():
        ver_success = sum(1 for o in ver_obs if o.success)
        ver_total = len(ver_obs)
        ver_quality = [
            o.quality_score for o in ver_obs if o.quality_score is not None
        ]
        metrics.version_stats[ver] = {
            "total": ver_total,
            "success_count": ver_success,
            "success_rate": ver_success / ver_total if ver_total > 0 else 0.0,
            "avg_quality": (
                sum(ver_quality) / len(ver_quality) if ver_quality else 0.0
            ),
        }

    return metrics
