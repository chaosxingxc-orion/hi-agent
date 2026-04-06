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
    """

    scope: str
    champion_version: str
    challenger_version: str
    winner: str
    champion_score: float
    challenger_score: float
    recommendation: str


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
