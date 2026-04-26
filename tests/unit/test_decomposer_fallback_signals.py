"""Track W2-D regression: TaskDecomposer LLM-error fallbacks emit Rule-7 signals.

When the LLM gateway raises during ``_llm_dag_decompose`` or
``_llm_tree_decompose``, the decomposer falls back to its heuristic DAG /
linear chain.  That fallback must be loud (countable + attributable +
inspectable) per Rule 7.  Attribution is keyed on ``task:<task_id>`` since
``run_id`` is not in scope at the decomposer call site.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.contracts import TaskContract
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events
from hi_agent.task_decomposition.decomposer import TaskDecomposer


def test_dag_decomposer_records_fallback_on_llm_error() -> None:
    """LLM exception during DAG decomposition -> heuristic DAG + fallback event."""
    task_id = "test-w2d-dag-001"
    scope = f"task:{task_id}"
    clear_fallback_events(scope)

    gateway = MagicMock()
    gateway.complete.side_effect = RuntimeError("boom: LLM unreachable")

    decomposer = TaskDecomposer(llm_gateway=gateway)
    contract = TaskContract(
        task_id=task_id,
        goal="Decompose the failing task",
        decomposition_strategy="dag",
    )

    dag = decomposer.decompose(contract)

    # Behavioural invariant: heuristic DAG still produced (5 stages).
    assert dag is not None
    assert len(dag.nodes) == 5  # understand/gather/build/synthesize/review

    events = get_fallback_events(scope)
    assert any(e["reason"] == "llm_decomposer_dag_error" for e in events), events
    match = next(e for e in events if e["reason"] == "llm_decomposer_dag_error")
    assert match["kind"] == "heuristic"
    assert match["extra"]["site"] == "TaskDecomposer._dag_decompose"
    assert match["extra"]["error_type"] == "RuntimeError"


def test_tree_decomposer_records_fallback_on_llm_error() -> None:
    """LLM exception during tree decomposition -> linear fallback + fallback event."""
    task_id = "test-w2d-tree-001"
    scope = f"task:{task_id}"
    clear_fallback_events(scope)

    gateway = MagicMock()
    gateway.complete.side_effect = ValueError("malformed tree response")

    decomposer = TaskDecomposer(llm_gateway=gateway)
    contract = TaskContract(
        task_id=task_id,
        goal="Decompose the failing task",
        decomposition_strategy="tree",
    )

    dag = decomposer.decompose(contract)

    # Behavioural invariant: linear fallback DAG produced (5 stages).
    assert dag is not None
    assert len(dag.nodes) == 5

    events = get_fallback_events(scope)
    assert any(e["reason"] == "llm_decomposer_tree_error" for e in events), events
    match = next(e for e in events if e["reason"] == "llm_decomposer_tree_error")
    assert match["kind"] == "heuristic"
    assert match["extra"]["site"] == "TaskDecomposer._tree_decompose"
    assert match["extra"]["error_type"] == "ValueError"
