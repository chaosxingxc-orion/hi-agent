"""Tests for G-12 stage goals and exit criteria."""

import json

import pytest


def _make_contract(**kwargs):
    from hi_agent.contracts.task import TaskContract

    defaults = {
        "task_id": "test-id",
        "goal": "test",
        "task_family": "research",
        "risk_level": "low",
    }
    defaults.update(kwargs)
    return TaskContract(**defaults)


def test_contract_has_stage_goal_field():
    c = _make_contract(stage_goal="Survey international SOTA", exit_criterion={})
    assert c.stage_goal == "Survey international SOTA"


def test_contract_has_exit_criterion_field():
    criterion = {"type": "file_exists", "params": {"path": "survey.md"}}
    c = _make_contract(exit_criterion=criterion)
    assert c.exit_criterion["type"] == "file_exists"


def test_stage_goal_default_is_empty():
    c = _make_contract()
    assert c.stage_goal == ""


def test_exit_criterion_default_is_empty_dict():
    c = _make_contract()
    assert c.exit_criterion == {}


def test_file_exists_criterion_satisfied(tmp_path):
    (tmp_path / "survey.md").write_text("done")
    from unittest.mock import MagicMock

    from hi_agent.execution.gate_coordinator import GateCoordinator

    coord = GateCoordinator(executor=MagicMock())
    c = _make_contract(exit_criterion={"type": "file_exists", "params": {"path": "survey.md"}})
    # Should not raise
    coord.check_exit_criterion(c, workspace_root=tmp_path)


def test_file_exists_criterion_unsatisfied_raises(tmp_path):
    from unittest.mock import MagicMock

    from hi_agent.execution.gate_coordinator import GateCoordinator
    from hi_agent.gate_protocol import GatePendingError

    coord = GateCoordinator(executor=MagicMock())
    c = _make_contract(exit_criterion={"type": "file_exists", "params": {"path": "survey.md"}})
    with pytest.raises((GatePendingError, ValueError, RuntimeError)):
        coord.check_exit_criterion(c, workspace_root=tmp_path)


def test_metric_threshold_criterion_satisfied(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"accuracy": 0.95}))
    from unittest.mock import MagicMock

    from hi_agent.execution.gate_coordinator import GateCoordinator

    coord = GateCoordinator(executor=MagicMock())
    c = _make_contract(
        exit_criterion={
            "type": "metric_threshold",
            "params": {
                "metric_file": "metrics.json",
                "key": "accuracy",
                "threshold": 0.9,
                "op": ">=",
            },
        }
    )
    coord.check_exit_criterion(c, workspace_root=tmp_path)  # should not raise


def test_metric_threshold_criterion_unsatisfied_raises(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"accuracy": 0.7}))
    from unittest.mock import MagicMock

    from hi_agent.execution.gate_coordinator import GateCoordinator
    from hi_agent.gate_protocol import GatePendingError

    coord = GateCoordinator(executor=MagicMock())
    c = _make_contract(
        exit_criterion={
            "type": "metric_threshold",
            "params": {
                "metric_file": "metrics.json",
                "key": "accuracy",
                "threshold": 0.9,
                "op": ">=",
            },
        }
    )
    with pytest.raises((GatePendingError, ValueError, RuntimeError)):
        coord.check_exit_criterion(c, workspace_root=tmp_path)


def test_no_criterion_always_passes(tmp_path):
    from unittest.mock import MagicMock

    from hi_agent.execution.gate_coordinator import GateCoordinator

    coord = GateCoordinator(executor=MagicMock())
    c = _make_contract(exit_criterion={})
    coord.check_exit_criterion(c, workspace_root=tmp_path)  # should not raise


def test_unknown_criterion_type_passes(tmp_path):
    """Unknown criterion types pass silently."""
    from unittest.mock import MagicMock

    from hi_agent.execution.gate_coordinator import GateCoordinator

    coord = GateCoordinator(executor=MagicMock())
    c = _make_contract(exit_criterion={"type": "unknown_future_type", "params": {}})
    coord.check_exit_criterion(c, workspace_root=tmp_path)  # should not raise
