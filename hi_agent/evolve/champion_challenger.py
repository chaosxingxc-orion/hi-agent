"""Champion/challenger comparison for routing and skill changes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ComparisonResult:
    """Result of a champion/challenger comparison.

    Attributes:
        scope: The scope being compared (e.g. routing heuristic ID).
        champion_version: Version string of the current champion.
        challenger_version: Version string of the challenger.
        winner: Outcome of the comparison.
        champion_score: Aggregate score of the champion.
        challenger_score: Aggregate score of the challenger.
        recommendation: Action recommendation.
        tenant_id: Tenant scope; required under research/prod posture.
    """

    scope: str
    champion_version: str
    challenger_version: str
    winner: str
    champion_score: float
    challenger_score: float
    recommendation: str
    tenant_id: str = ""  # scope: spine-required — enforced under strict posture

    def __post_init__(self) -> None:
        from hi_agent.config.posture import Posture

        if Posture.from_env().is_strict and not self.tenant_id:
            raise ValueError(
                "ComparisonResult.tenant_id required under research/prod posture"
            )


# Registry-side bookkeeping; tenant scope flows via ChampionChallenger.
# scope: process-internal — internal entry held by the enclosing registry instance.
@dataclass
class _Entry:
    """Internal entry for a registered champion or challenger."""

    version: str
    metrics: dict[str, float]


class ChampionChallenger:
    """Champion/challenger comparison for routing and skill changes.

    Before promoting a change (e.g., new routing heuristic), compare
    its performance against the current champion on the same task families.
    """

    def __init__(self) -> None:
        """Initialize the champion/challenger registry."""
        self._champions: dict[str, _Entry] = {}
        self._challengers: dict[str, _Entry] = {}
        self._run_counts: dict[str, int] = {}

    def record(
        self,
        scope: str,
        version: str,
        metrics: dict[str, float],
        is_challenger: bool = False,
    ) -> None:
        """Record run metrics for a champion or challenger version.

        Accumulates metrics by averaging with previously recorded values
        and increments the per-scope run counter.

        Args:
            scope: Scope identifier (e.g. skill ID).
            version: Version string of the entity.
            metrics: Performance metrics from this run.
            is_challenger: If True, record as challenger; otherwise as champion.
        """
        target = self._challengers if is_challenger else self._champions
        existing = target.get(scope)
        if existing is None:
            target[scope] = _Entry(version=version, metrics=dict(metrics))
        else:
            # Running average of shared keys, add new keys
            for k, v in metrics.items():
                if k in existing.metrics:
                    existing.metrics[k] = (existing.metrics[k] + v) / 2.0
                else:
                    existing.metrics[k] = v
            existing.version = version
        self._run_counts[scope] = self._run_counts.get(scope, 0) + 1

    def get_run_count(self, scope: str) -> int:
        """Return the number of runs recorded for a scope."""
        return self._run_counts.get(scope, 0)

    def has_challenger(self, scope: str) -> bool:
        """Return True if a challenger is registered for the scope."""
        return scope in self._challengers

    def scopes_with_challenger(self) -> list[str]:
        """Return all scopes that have both champion and challenger."""
        return [s for s in self._challengers if s in self._champions]

    def register_champion(
        self,
        scope: str,
        version: str,
        metrics: dict[str, float],
    ) -> None:
        """Register the current champion for a scope.

        Args:
            scope: Scope identifier (e.g. task family or routing heuristic).
            version: Version string of the champion.
            metrics: Performance metrics keyed by metric name.
        """
        self._champions[scope] = _Entry(version=version, metrics=metrics)

    def register_challenger(
        self,
        scope: str,
        version: str,
        metrics: dict[str, float],
    ) -> None:
        """Register a challenger for a scope.

        Args:
            scope: Scope identifier.
            version: Version string of the challenger.
            metrics: Performance metrics keyed by metric name.
        """
        self._challengers[scope] = _Entry(version=version, metrics=metrics)

    def compare(self, scope: str) -> ComparisonResult:
        """Compare champion and challenger for a given scope.

        The comparison aggregates all shared metric keys using a simple
        average.  If either side is missing, the result is ``inconclusive``.

        Args:
            scope: Scope identifier to compare.

        Returns:
            A ComparisonResult with winner and recommendation.
        """
        champion = self._champions.get(scope)
        challenger = self._challengers.get(scope)

        if champion is None or challenger is None:
            return ComparisonResult(
                scope=scope,
                champion_version=champion.version if champion else "unknown",
                challenger_version=challenger.version if challenger else "unknown",
                winner="inconclusive",
                champion_score=0.0,
                challenger_score=0.0,
                recommendation="need_more_data",
            )

        champion_score = _aggregate(champion.metrics)
        challenger_score = _aggregate(challenger.metrics)

        if challenger_score > champion_score:
            winner = "challenger"
            recommendation = "promote_challenger"
        elif champion_score > challenger_score:
            winner = "champion"
            recommendation = "keep_champion"
        else:
            winner = "inconclusive"
            recommendation = "need_more_data"

        return ComparisonResult(
            scope=scope,
            champion_version=champion.version,
            challenger_version=challenger.version,
            winner=winner,
            champion_score=champion_score,
            challenger_score=challenger_score,
            recommendation=recommendation,
        )


def _aggregate(metrics: dict[str, float]) -> float:
    """Compute the average of metric values.

    Args:
        metrics: Metric name to value mapping.

    Returns:
        Average value, or 0.0 if empty.
    """
    if not metrics:
        return 0.0
    return sum(metrics.values()) / len(metrics)
