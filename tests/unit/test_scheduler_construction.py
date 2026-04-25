"""Unit tests: TaskScheduler raises ValueError for each missing required injection.

Guards Rule 6 (H2-Track3) — both inline fallback constructions removed:
  communicator, monitor.
Each must fail fast with a clear ValueError when not explicitly injected.
"""

from __future__ import annotations

import pytest
from hi_agent.task_mgmt.monitor import TaskMonitor
from hi_agent.task_mgmt.notification import TaskCommunicator
from hi_agent.task_mgmt.scheduler import TaskScheduler


def _base_kwargs() -> dict:
    """Return all required args so individual tests can omit one at a time."""
    return {
        "communicator": TaskCommunicator(),
        "monitor": TaskMonitor(),
    }


# ---------------------------------------------------------------------------
# communicator
# ---------------------------------------------------------------------------


def test_scheduler_raises_on_missing_communicator() -> None:
    """TaskScheduler must raise ValueError when communicator=None.

    Rule 6: unscoped TaskCommunicator inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["communicator"] = None
    with pytest.raises(ValueError, match="communicator"):
        TaskScheduler(**kwargs)


def test_scheduler_communicator_error_mentions_rule6() -> None:
    """ValueError for missing communicator must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["communicator"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        TaskScheduler(**kwargs)


# ---------------------------------------------------------------------------
# monitor
# ---------------------------------------------------------------------------


def test_scheduler_raises_on_missing_monitor() -> None:
    """TaskScheduler must raise ValueError when monitor=None.

    Rule 6: unscoped TaskMonitor inline fallback is forbidden.
    """
    kwargs = _base_kwargs()
    kwargs["monitor"] = None
    with pytest.raises(ValueError, match="monitor"):
        TaskScheduler(**kwargs)


def test_scheduler_monitor_error_mentions_rule6() -> None:
    """ValueError for missing monitor must reference Rule 6."""
    kwargs = _base_kwargs()
    kwargs["monitor"] = None
    with pytest.raises(ValueError, match="Rule 6"):
        TaskScheduler(**kwargs)


# ---------------------------------------------------------------------------
# Positive: all args provided → construction succeeds
# ---------------------------------------------------------------------------


def test_scheduler_constructs_successfully_with_all_required_args() -> None:
    """TaskScheduler must construct without error when all args are injected."""
    comm = TaskCommunicator()
    mon = TaskMonitor()
    sched = TaskScheduler(communicator=comm, monitor=mon)
    assert sched._communicator is comm
    assert sched._monitor is mon
