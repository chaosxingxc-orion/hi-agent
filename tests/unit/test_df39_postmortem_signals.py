"""DF-39 regression tests for postmortem fallback observability."""

from __future__ import annotations

from unittest.mock import MagicMock

from hi_agent.evolve.contracts import RunPostmortem
from hi_agent.evolve.postmortem import PostmortemAnalyzer
from hi_agent.observability.fallback import clear_fallback_events, get_fallback_events


def test_postmortem_llm_json_parse_records_fallback() -> None:
    run_id = "test-df39-postmortem-001"
    clear_fallback_events(run_id)

    gateway = MagicMock()
    response = MagicMock()
    response.content = "not valid json at all {{{"
    gateway.complete.return_value = response

    analyzer = PostmortemAnalyzer(llm_gateway=gateway)
    postmortem = RunPostmortem(
        run_id=run_id,
        task_id="task-df39",
        task_family="quick_task",
        outcome="completed",
        stages_completed=["s1"],
        stages_failed=[],
        branches_explored=1,
        branches_pruned=0,
        total_actions=2,
        failure_codes=[],
        duration_seconds=1.0,
    )

    result = analyzer.analyze(postmortem)

    assert result is not None
    events = get_fallback_events(run_id)
    assert any(event["reason"] == "llm_json_parse_error" for event in events), events
    match = next(event for event in events if event["reason"] == "llm_json_parse_error")
    assert match["kind"] == "heuristic"
    assert match["extra"]["site"] == "postmortem._parse_llm_changes"
    assert match["extra"]["error_type"] == "JSONDecodeError"
