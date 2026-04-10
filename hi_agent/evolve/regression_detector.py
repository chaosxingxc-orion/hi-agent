"""Detect quality and efficiency regressions across runs."""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass

_logger = logging.getLogger(__name__)


@dataclass
class RegressionReport:
    """Report from a regression check on a task family.

    Attributes:
        task_family: The task family that was checked.
        is_regression: Whether a regression was detected.
        quality_delta: Difference between current and baseline quality.
        efficiency_delta: Difference between current and baseline efficiency.
        baseline_quality: Average quality over the baseline window.
        current_quality: Most recent quality observation.
        runs_in_window: Number of runs in the baseline window.
        recommendation: Action recommendation (no_action, investigate, rollback).
    """

    task_family: str
    is_regression: bool
    quality_delta: float
    efficiency_delta: float
    baseline_quality: float
    current_quality: float
    runs_in_window: int
    recommendation: str


@dataclass
class _RunRecord:
    """Internal record for a single run's metrics."""

    run_id: str
    quality: float
    efficiency: float


class RegressionDetector:
    """Detects quality and efficiency regressions across runs.

    Maintains a sliding window of recent run metrics per task family and
    compares the latest observation against the baseline average.
    """

    def __init__(
        self,
        baseline_window: int = 10,
        threshold: float = 0.15,
        storage_path: str | None = None,
    ) -> None:
        """Initialize the regression detector.

        Args:
            baseline_window: Number of recent runs to use as baseline.
            threshold: Minimum delta (absolute drop) to flag a regression.
            storage_path: Optional path to a JSON file for persistent storage.
        """
        self._baseline_window = baseline_window
        self._threshold = threshold
        self._storage_path = storage_path
        self._records: dict[str, list[_RunRecord]] = defaultdict(list)

    def record(
        self,
        run_id: str,
        task_family: str,
        quality: float,
        efficiency: float,
    ) -> None:
        """Record metrics for a completed run.

        Args:
            run_id: Unique run identifier.
            task_family: Task family for grouping.
            quality: Quality score (0.0-1.0).
            efficiency: Efficiency score (0.0-1.0).
        """
        self._records[task_family].append(
            _RunRecord(run_id=run_id, quality=quality, efficiency=efficiency)
        )
        if self._storage_path is not None:
            self._save_best_effort()

    def save(self) -> None:
        """Persist _records to storage_path as JSON.

        Best-effort: creates parent directories as needed.
        Raises exceptions on failure (caller should use _save_best_effort).
        """
        if self._storage_path is None:
            return
        os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
        payload: dict[str, list[dict]] = {}
        for family, records in self._records.items():
            payload[family] = [
                {"run_id": r.run_id, "quality": r.quality, "efficiency": r.efficiency}
                for r in records
            ]
        with open(self._storage_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        _logger.debug("RegressionDetector: saved %d families to %s", len(payload), self._storage_path)

    def load(self) -> None:
        """Load _records from storage_path JSON if the file exists.

        Best-effort: logs a warning on failure and leaves _records unchanged.
        """
        if self._storage_path is None or not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path, "r", encoding="utf-8") as fh:
                payload: dict[str, list[dict]] = json.load(fh)
            self._records = defaultdict(list)
            for family, records in payload.items():
                self._records[family] = [
                    _RunRecord(
                        run_id=r["run_id"],
                        quality=float(r["quality"]),
                        efficiency=float(r["efficiency"]),
                    )
                    for r in records
                ]
            _logger.debug(
                "RegressionDetector: loaded %d families from %s", len(self._records), self._storage_path
            )
        except Exception as exc:
            _logger.warning("RegressionDetector.load failed: %s", exc)

    def _save_best_effort(self) -> None:
        """Attempt to save; log debug message on failure."""
        try:
            self.save()
        except Exception as exc:
            _logger.debug("RegressionDetector.save failed: %s", exc)

    def check(self, task_family: str) -> RegressionReport:
        """Check for regressions in a task family.

        Compares the most recent run against the baseline window average.

        Args:
            task_family: The task family to check.

        Returns:
            A RegressionReport with findings and recommendation.
        """
        records = self._records.get(task_family, [])

        if len(records) < 2:
            return RegressionReport(
                task_family=task_family,
                is_regression=False,
                quality_delta=0.0,
                efficiency_delta=0.0,
                baseline_quality=records[0].quality if records else 0.0,
                current_quality=records[0].quality if records else 0.0,
                runs_in_window=len(records),
                recommendation="no_action",
            )

        # Baseline = all records except the last, capped to window size.
        latest = records[-1]
        baseline_records = records[-(self._baseline_window + 1) : -1]

        baseline_quality = sum(r.quality for r in baseline_records) / len(
            baseline_records
        )
        baseline_efficiency = sum(r.efficiency for r in baseline_records) / len(
            baseline_records
        )

        quality_delta = latest.quality - baseline_quality
        efficiency_delta = latest.efficiency - baseline_efficiency

        is_regression = (
            quality_delta < -self._threshold
            or efficiency_delta < -self._threshold
        )

        recommendation = "no_action"
        if is_regression:
            # Severe regression if both quality and efficiency dropped.
            if (
                quality_delta < -self._threshold
                and efficiency_delta < -self._threshold
            ):
                recommendation = "rollback"
            else:
                recommendation = "investigate"

        return RegressionReport(
            task_family=task_family,
            is_regression=is_regression,
            quality_delta=quality_delta,
            efficiency_delta=efficiency_delta,
            baseline_quality=baseline_quality,
            current_quality=latest.quality,
            runs_in_window=len(baseline_records),
            recommendation=recommendation,
        )
