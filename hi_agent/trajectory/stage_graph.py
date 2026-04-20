"""Stage graph definition and validation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from hi_agent.contracts.cts_budget import CTSBudget


@dataclass
class ValidationReport:
    """Structured result from running all stage-graph validations."""

    is_valid: bool
    unreachable_stages: list[str] = field(default_factory=list)
    dead_end_stages: list[str] = field(default_factory=list)
    terminal_unreachable_stages: list[str] = field(default_factory=list)
    incomplete_gates: list[str] = field(default_factory=list)
    budget_violations: list[str] = field(default_factory=list)


@dataclass
class StageGraph:
    """Directed graph of stage transitions."""

    transitions: dict[str, set[str]] = field(default_factory=dict)
    backtrack_edges: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Core graph operations
    # ------------------------------------------------------------------

    def add_edge(self, source: str, target: str) -> None:
        """Add directed edge from source to target."""
        self.transitions.setdefault(source, set()).add(target)
        self.transitions.setdefault(target, set())

    def successors(self, stage_id: str) -> set[str]:
        """Return outgoing transitions from stage."""
        return self.transitions.get(stage_id, set())

    def add_backtrack(self, source: str, target: str) -> None:
        """Add backtrack edge (failure recovery path)."""
        self.backtrack_edges[source] = target

    def get_backtrack(self, stage_id: str) -> str | None:
        """Return backtrack target for a stage, or None."""
        return self.backtrack_edges.get(stage_id)

    # ------------------------------------------------------------------
    # Legacy helpers (kept for backward compatibility)
    # ------------------------------------------------------------------

    def validate_reachability(
        self, start_stage: str, terminal_stage: str
    ) -> bool:
        """Return True if terminal is reachable from start."""
        if (
            start_stage not in self.transitions
            or terminal_stage not in self.transitions
        ):
            return False
        visited: set[str] = set()
        queue: deque[str] = deque([start_stage])
        while queue:
            current = queue.popleft()
            if current == terminal_stage:
                return True
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self.transitions.get(current, set()) - visited)
        return False

    def has_deadlock(self, terminal_stages: set[str]) -> bool:
        """Detect deadlock states (non-terminal nodes with zero outgoing edges)."""
        for stage, next_set in self.transitions.items():
            if stage in terminal_stages:
                continue
            if not next_set:
                return True
        return False

    # ------------------------------------------------------------------
    # Formal validation methods (EP-1.7)
    # ------------------------------------------------------------------

    def validate_reachability_from(self, initial_stage: str) -> list[str]:
        """BFS reachability check from *initial_stage*.

        Returns list of stages that are **not** reachable from the initial
        stage. An empty list means every stage is reachable.
        """
        if not self.transitions:
            return []
        if initial_stage not in self.transitions:
            return sorted(self.transitions)

        visited: set[str] = set()
        queue: deque[str] = deque([initial_stage])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self.transitions.get(current, set()) - visited)

        return sorted(set(self.transitions) - visited)

    def validate_terminal_reachability(
        self, terminal_stages: set[str]
    ) -> list[str]:
        """Return stages that cannot reach **any** terminal stage.

        Uses reverse-BFS from each terminal stage to find all stages that
        can eventually reach a terminal.
        """
        if not self.transitions:
            return []

        # Build reverse adjacency list.
        reverse: dict[str, set[str]] = {s: set() for s in self.transitions}
        for src, targets in self.transitions.items():
            for tgt in targets:
                reverse.setdefault(tgt, set()).add(src)

        # BFS backwards from every terminal stage.
        can_reach_terminal: set[str] = set()
        queue: deque[str] = deque(
            t for t in terminal_stages if t in self.transitions
        )
        while queue:
            current = queue.popleft()
            if current in can_reach_terminal:
                continue
            can_reach_terminal.add(current)
            queue.extend(reverse.get(current, set()) - can_reach_terminal)

        return sorted(set(self.transitions) - can_reach_terminal)

    def validate_gate_completeness(
        self, gate_stages: dict[str, str]
    ) -> list[str]:
        """Check that gated stages have both approved and rejected paths.

        *gate_stages* maps ``stage_id`` -> ``gate_type``.  A gate is
        considered **complete** when its stage has at least two distinct
        outgoing edges (one for the approved path, one for rejected).

        Returns stage IDs whose gate paths are incomplete.
        """
        incomplete: list[str] = []
        for stage_id in sorted(gate_stages):
            outgoing = self.transitions.get(stage_id, set())
            if len(outgoing) < 2:
                incomplete.append(stage_id)
        return incomplete

    @staticmethod
    def validate_cts_budget(budget: CTSBudget) -> list[str]:
        """Validate CTS budget invariants.

        Checks:
        - All token layers are positive.
        - Total tokens are positive.

        Returns a list of violation descriptions (empty means valid).
        """
        violations: list[str] = []
        if budget.l0_raw_tokens <= 0:
            violations.append(
                f"l0_raw_tokens must be positive, got {budget.l0_raw_tokens}"
            )
        if budget.l1_summary_tokens <= 0:
            violations.append(
                f"l1_summary_tokens must be positive, "
                f"got {budget.l1_summary_tokens}"
            )
        if budget.l2_index_tokens <= 0:
            violations.append(
                f"l2_index_tokens must be positive, "
                f"got {budget.l2_index_tokens}"
            )
        if budget.total_tokens <= 0:
            violations.append(
                f"total_tokens must be positive, got {budget.total_tokens}"
            )
        return violations

    def validate_no_dead_ends(self, terminal_stages: set[str]) -> list[str]:
        """Return non-terminal stages that have **no** successors."""
        return sorted(
            stage
            for stage, targets in self.transitions.items()
            if stage not in terminal_stages and not targets
        )

    # ------------------------------------------------------------------
    # Combined validation
    # ------------------------------------------------------------------

    def validate_all(
        self,
        initial_stage: str,
        terminal_stages: set[str],
        gate_stages: dict[str, str] | None = None,
        budget: CTSBudget | None = None,
    ) -> ValidationReport:
        """Run **all** formal validations and return a structured report.

        This is the single entry-point for full graph validation.  When
        called with only *initial_stage* and *terminal_stages* it remains
        backward-compatible with the legacy dict-based ``validate_all``.
        """
        unreachable = self.validate_reachability_from(initial_stage)
        dead_ends = self.validate_no_dead_ends(terminal_stages)
        terminal_unreachable = self.validate_terminal_reachability(
            terminal_stages
        )
        incomplete_gates: list[str] = (
            self.validate_gate_completeness(gate_stages)
            if gate_stages
            else []
        )
        budget_violations: list[str] = (
            self.validate_cts_budget(budget) if budget else []
        )

        is_valid = not any(
            [
                unreachable,
                dead_ends,
                terminal_unreachable,
                incomplete_gates,
                budget_violations,
            ]
        )

        return ValidationReport(
            is_valid=is_valid,
            unreachable_stages=unreachable,
            dead_end_stages=dead_ends,
            terminal_unreachable_stages=terminal_unreachable,
            incomplete_gates=incomplete_gates,
            budget_violations=budget_violations,
        )

    def trace_order(self, start_stage: str | None = None) -> list[str]:
        """Return deterministic traversal order for execution.

        Traversal is breadth-first with lexicographically sorted successors.
        If start is omitted, choose a deterministic root (lowest lexical
        stage among roots with zero indegree, otherwise lowest lexical node).
        """
        if not self.transitions:
            return []

        if start_stage is None:
            indegree: dict[str, int] = dict.fromkeys(self.transitions, 0)
            for next_set in self.transitions.values():
                for target in next_set:
                    indegree[target] = indegree.get(target, 0) + 1
            roots = sorted(
                stage for stage, count in indegree.items() if count == 0
            )
            start_stage = roots[0] if roots else sorted(self.transitions)[0]

        if start_stage not in self.transitions:
            return []

        order: list[str] = []
        visited: set[str] = set()
        queue: deque[str] = deque([start_stage])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            order.append(current)
            for successor in sorted(
                self.transitions.get(current, set())
            ):
                if successor not in visited:
                    queue.append(successor)
        return order


# ------------------------------------------------------------------
# Default graph builders
# ------------------------------------------------------------------


def default_trace_stage_graph() -> StageGraph:
    """Return the sample TRACE S1→S5 stage graph.

    .. deprecated::
        This is a *sample* configuration that lives in
        ``hi_agent.samples.trace_pipeline``.  Business agents should build
        and inject their own :class:`StageGraph` rather than relying on this
        default.  This function is kept for backward compatibility only.
    """
    from hi_agent.samples.trace_pipeline import build_trace_stage_graph
    return build_trace_stage_graph()


def build_default_trace_graph() -> StageGraph:
    """Alias for :func:`default_trace_stage_graph`.

    .. deprecated::
        Use ``hi_agent.samples.trace_pipeline.build_trace_stage_graph`` directly.
    """
    return default_trace_stage_graph()
