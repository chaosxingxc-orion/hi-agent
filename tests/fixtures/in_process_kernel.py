"""In-process kernel stub for honest PI-D / PI-E integration tests.

Purpose
-------
``DelegationManager`` talks to a ``RuntimeAdapter``-shaped object via exactly
two methods: ``spawn_child_run_async`` and ``query_run``.  The real kernel
(``MockKernel`` in ``tests/helpers/kernel_adapter_fixture.py``) spawns child
runs in a ``"created"`` lifecycle and never advances them to a terminal
state without a worker — so the delegation poller would block indefinitely
in an integration test.

``InProcessKernelStub`` is a **minimal real implementation** of the subset
of ``RuntimeAdapter`` that delegation touches.  It is not a ``Mock`` /
``MagicMock`` — it stores state, generates distinct run_ids, and produces
real configurable outputs.  A PI-D / PI-E test using it therefore exercises
the real ``DelegationManager`` / ``ChildRunPoller`` / ``ResultSummarizer``
code paths without any internal mocking.

Design constraints (Rule 13 ID uniqueness, Rule 7 Three-Layer Testing):

* Every ``spawn_child_run_async`` call yields a fresh ``uuid.uuid4``-based
  ``child_run_id`` — never a semantic label.
* ``query_run`` returns a terminal lifecycle (``"completed"`` by default)
  immediately so the poller converges.  Failure / gate_pending modes are
  configurable per child via :class:`ChildOutcome`.
* Recorded spawn calls are available on ``.spawn_calls`` so tests can
  assert the parent/child wiring without patching.

The fixture is deliberately small and reusable — Wave-4 E2E tests can import
it directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChildOutcome:
    """Canned outcome for a spawned child run.

    Attributes:
        lifecycle_state: Terminal state returned by ``query_run``.
        output: Output payload returned by ``query_run``.
    """

    lifecycle_state: str = "completed"
    output: str = "in-process subrun output"


@dataclass
class InProcessKernelStub:
    """Minimal real in-process implementation of the subset of
    ``RuntimeAdapter`` that ``DelegationManager`` depends on.

    Only the delegation surface is implemented:

    * ``spawn_child_run_async(parent_run_id, task_id, config)`` — returns a
      fresh uuid-based child_run_id and records the call.
    * ``query_run(run_id)`` — returns a snapshot containing
      ``lifecycle_state`` and ``output``.

    The default behavior yields ``"completed"`` with a non-empty output
    payload.  Tests that want to exercise alternative branches can preload
    ``outcomes`` with a ``ChildOutcome`` keyed by child_run_id **or** by
    task_id (checked in that order).
    """

    spawn_calls: list[dict[str, Any]] = field(default_factory=list)
    outcomes: dict[str, ChildOutcome] = field(default_factory=dict)
    default_outcome: ChildOutcome = field(default_factory=ChildOutcome)

    # Internal map: child_run_id -> task_id, so query_run can route by task.
    _child_to_task: dict[str, str] = field(default_factory=dict)

    async def spawn_child_run_async(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Spawn a child run and return a fresh uuid-based child_run_id."""
        if not parent_run_id or not parent_run_id.strip():
            raise ValueError("parent_run_id must be non-empty")
        if not task_id or not task_id.strip():
            raise ValueError("task_id must be non-empty")
        child_run_id = f"child-{uuid.uuid4().hex[:12]}"
        self._child_to_task[child_run_id] = task_id
        self.spawn_calls.append(
            {
                "parent_run_id": parent_run_id,
                "task_id": task_id,
                "config": dict(config or {}),
                "child_run_id": child_run_id,
            }
        )
        return child_run_id

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Return a run snapshot including terminal lifecycle_state and output."""
        outcome = self.outcomes.get(run_id)
        if outcome is None:
            task_id = self._child_to_task.get(run_id)
            if task_id is not None:
                outcome = self.outcomes.get(task_id)
        if outcome is None:
            outcome = self.default_outcome
        return {
            "run_id": run_id,
            "lifecycle_state": outcome.lifecycle_state,
            "output": outcome.output,
        }
