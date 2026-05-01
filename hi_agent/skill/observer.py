"""Skill execution observer for async, non-blocking telemetry.

Inspired by ECC continuous-learning-v2 hooks: capture every skill
execution with inputs/outputs/metrics WITHOUT blocking the execution.

Observations are appended to a JSONL file (like ECC's observations.jsonl).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field

_logger = logging.getLogger(__name__)


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
    # Contract spine (Rule 12)
    tenant_id: str = ""  # scope: process-internal — observation; populated from exec_ctx
    user_id: str = ""
    session_id: str = ""
    project_id: str = ""
    # Summary truncation limit (configurable per-observation)
    max_summary_len: int = 500

    def __post_init__(self) -> None:
        """Truncate summaries to max length."""
        if len(self.input_summary) > self.max_summary_len:
            self.input_summary = self.input_summary[: self.max_summary_len]
        if len(self.output_summary) > self.max_summary_len:
            self.output_summary = self.output_summary[: self.max_summary_len]


@dataclass
class SkillMetrics:
    """Aggregated metrics for a skill version.

    Wave 24 H1: tenant_id is on the spine so per-tenant skill registries can
    surface skill-level metrics without crosstenant leakage.
    """

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
    tenant_id: str = ""  # scope: spine-required — enforced under strict posture

    def __post_init__(self) -> None:
        from hi_agent.config.posture import Posture

        if Posture.from_env().is_strict and not self.tenant_id:
            raise ValueError(
                "SkillMetrics.tenant_id required under research/prod posture"
            )


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
        self,
        skill_id: str,
        limit: int = 100,
        tenant_id: str | None = None,
    ) -> list[SkillObservation]:
        """Load observations for a skill from disk.

        When ``tenant_id`` is provided, observations are filtered to those
        whose ``tenant_id`` field matches.  When ``tenant_id is None`` the
        full unfiltered stream is returned (legacy / process-internal call
        path); under strict posture this triggers a WARNING because every
        request-scoped caller is required to pass an authenticated tenant.
        """
        if tenant_id is None:
            self._warn_unscoped_read("get_observations", skill_id)
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
                obs = SkillObservation(**data)
                if tenant_id is not None and obs.tenant_id != tenant_id:
                    continue
                observations.append(obs)

        # Return most recent observations up to limit
        return observations[-limit:]

    def get_metrics(
        self, skill_id: str, tenant_id: str | None = None
    ) -> SkillMetrics:
        """Aggregate metrics for a skill from observations.

        When ``tenant_id`` is provided, only that tenant's observations are
        aggregated.  See :meth:`get_observations` for the unscoped-read trip.
        """
        if tenant_id is None:
            self._warn_unscoped_read("get_metrics", skill_id)
        observations = self.get_observations(
            skill_id, limit=10000, tenant_id=tenant_id
        )
        return _aggregate_metrics(skill_id, observations)

    def get_all_metrics(
        self, tenant_id: str | None = None
    ) -> dict[str, SkillMetrics]:
        """Aggregate metrics for all observed skills.

        When ``tenant_id`` is provided, each skill's metrics are aggregated
        only over that tenant's observations.
        """
        if tenant_id is None:
            self._warn_unscoped_read("get_all_metrics", skill_id=None)
        result: dict[str, SkillMetrics] = {}
        if not os.path.exists(self._storage_dir):
            return result

        for filename in os.listdir(self._storage_dir):
            if filename.endswith(".jsonl"):
                skill_id = filename[:-6]  # strip .jsonl
                result[skill_id] = self.get_metrics(skill_id, tenant_id=tenant_id)

        return result

    def _warn_unscoped_read(self, method: str, skill_id: str | None) -> None:
        """Emit a WARNING when a strict-posture read is made without tenant_id.

        Rule 11 — research/prod default-on: every request-scoped read of a
        shared observation pool must carry an authenticated ``tenant_id``.
        Process-internal callers (e.g. ``SkillEvolver.evolve_cycle``) operate
        on the cross-tenant pool by design and may pass ``tenant_id=None``;
        the warning surfaces accidental cross-tenant reads from route
        handlers.
        """
        try:
            from hi_agent.config.posture import Posture

            if Posture.from_env().is_strict:
                _logger.warning(
                    "SkillObserver.%s called without tenant_id under strict "
                    "posture (skill_id=%s); cross-tenant pool is being read",
                    method,
                    skill_id,
                )
        except Exception:  # rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests
            # Posture lookup must never break reads.
            return


def _aggregate_metrics(skill_id: str, observations: list[SkillObservation]) -> SkillMetrics:
    """Compute aggregated metrics from a list of observations."""
    metrics = SkillMetrics(skill_id=skill_id)
    if not observations:
        return metrics

    metrics.total_executions = len(observations)
    metrics.success_count = sum(1 for o in observations if o.success)
    metrics.failure_count = metrics.total_executions - metrics.success_count
    metrics.success_rate = (
        metrics.success_count / metrics.total_executions if metrics.total_executions > 0 else 0.0
    )

    # Average quality (only from observations that have a score)
    quality_scores = [o.quality_score for o in observations if o.quality_score is not None]
    metrics.avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

    # Average tokens
    token_values = [o.tokens_used for o in observations]
    metrics.avg_tokens = sum(token_values) / len(token_values) if token_values else 0.0

    # Average latency
    latency_values = [o.latency_ms for o in observations]
    metrics.avg_latency_ms = sum(latency_values) / len(latency_values) if latency_values else 0.0

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
        ver_quality = [o.quality_score for o in ver_obs if o.quality_score is not None]
        metrics.version_stats[ver] = {
            "total": ver_total,
            "success_count": ver_success,
            "success_rate": ver_success / ver_total if ver_total > 0 else 0.0,
            "avg_quality": (sum(ver_quality) / len(ver_quality) if ver_quality else 0.0),
        }

    return metrics
