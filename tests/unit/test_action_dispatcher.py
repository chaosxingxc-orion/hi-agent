from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from hi_agent.execution.action_dispatcher import (
    ActionDispatchContext,
    ActionDispatcher,
)


def _ctx(invoker: MagicMock, *, action_max_retries: int = 0) -> ActionDispatchContext:
    return ActionDispatchContext(
        run_id="run-001",
        current_stage="S1",
        action_seq=7,
        invoker=invoker,
        harness_executor=None,
        runner_role=None,
        invoker_accepts_role=False,
        invoker_accepts_metadata=False,
        hook_manager=None,
        capability_provenance_store={},
        force_fail_actions=set(),
        action_max_retries=action_max_retries,
        record_event_fn=MagicMock(),
        emit_observability_fn=MagicMock(),
        nudge_check_fn=MagicMock(),
    )


def _proposal() -> SimpleNamespace:
    return SimpleNamespace(branch_id="branch-001", action_kind="tool")


def test_execute_action_success_returns_attempt_one() -> None:
    invoker = MagicMock()
    invoker.invoke.return_value = {"success": True}
    dispatcher = ActionDispatcher(_ctx(invoker))

    success, result, attempt = dispatcher._execute_action_with_retry(
        "S1",
        _proposal(),
    )

    assert success is True
    assert result == {"success": True}
    assert attempt == 1


def test_execute_action_failure_returns_unsuccessful_result() -> None:
    invoker = MagicMock()
    invoker.invoke.return_value = {"success": False}
    dispatcher = ActionDispatcher(_ctx(invoker))

    success, result, attempt = dispatcher._execute_action_with_retry(
        "S1",
        _proposal(),
    )

    assert success is False
    assert result == {"success": False}
    assert attempt == 1


def test_execute_action_retries_after_exception() -> None:
    invoker = MagicMock()
    invoker.invoke.side_effect = [RuntimeError("boom"), {"success": True}]
    dispatcher = ActionDispatcher(_ctx(invoker, action_max_retries=2))

    success, result, attempt = dispatcher._execute_action_with_retry(
        "S1",
        _proposal(),
    )

    assert success is True
    assert result == {"success": True}
    assert attempt == 2


def test_parse_invoker_role_returns_role_string() -> None:
    assert ActionDispatcher._parse_invoker_role(
        ["fast", "invoker_role:researcher"]
    ) == "researcher"


def test_parse_invoker_role_with_empty_list_returns_none() -> None:
    assert ActionDispatcher._parse_invoker_role([]) is None
