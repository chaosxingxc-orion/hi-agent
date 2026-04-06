"""Observability metrics helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class RunMetricsRecord:
    """Single run metrics row used by aggregation helpers.

    Attributes:
      run_id: Run identifier.
      status: Run status (for example ``completed`` or ``failed``).
      input_tokens: Total prompt/input tokens.
      output_tokens: Total completion/output tokens.
      latency_ms: End-to-end latency in milliseconds.
    """

    run_id: str
    status: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


def run_success_rate(records: list[RunMetricsRecord]) -> float:
    """Calculate completed/succeeded ratio for runs."""
    if not records:
        return 0.0
    success = sum(1 for record in records if record.status in {"completed", "succeeded"})
    return success / len(records)


def avg_token_per_run(records: list[RunMetricsRecord]) -> float:
    """Return average total tokens (input + output) per run."""
    if not records:
        return 0.0
    total_tokens = sum(record.input_tokens + record.output_tokens for record in records)
    return total_tokens / len(records)


def p95_latency_ms(records: list[RunMetricsRecord]) -> float:
    """Return p95 latency in milliseconds via nearest-rank percentile."""
    if not records:
        return 0.0
    latencies = sorted(record.latency_ms for record in records)
    rank = ceil(0.95 * len(latencies))
    return latencies[rank - 1]


def p95_latency(records: list[RunMetricsRecord]) -> float:
    """Backward-compatible alias for code paths expecting `p95_latency`."""
    return p95_latency_ms(records)


def aggregate_counters(counter_rows: list[dict[str, int]]) -> dict[str, int]:
    """Aggregate homogeneous counter dictionaries by summation."""
    result: dict[str, int] = {}
    for row in counter_rows:
        for key, value in row.items():
            result[key] = result.get(key, 0) + int(value)
    return result
