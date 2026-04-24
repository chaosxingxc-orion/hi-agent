"""Branch-parity tests for ``execute_async`` vs ``execute`` kernel wiring.

Regression coverage for DF-16 / K-2 / K-3 / K-15:

* K-2: after ``execute_async`` calls ``kernel.start_run``, ``executor._run_id``
  is the value the kernel returned (not a locally minted placeholder).
* K-3: ``kernel.start_run`` is invoked with the *same* signature the
  synchronous ``execute()`` path uses — a single positional ``task_id``.
* K-15: ``executor._run_start_monotonic`` is populated so downstream
  duration metrics are measurable.
"""

from __future__ import annotations

import contextlib

import pytest
from hi_agent.contracts import TaskContract
from hi_agent.runner import RunExecutor, execute_async

from tests.helpers.kernel_adapter_fixture import MockKernel


class _RecordingAsyncKernel:
    """Minimal async kernel that records start_run calls and returns a
    deterministic run_id.  Conforms to the RuntimeAdapter protocol signature
    ``start_run(task_id: str) -> Awaitable[str]``.
    """

    def __init__(self, fixed_run_id: str = "kernel-run-xyz") -> None:
        self.fixed_run_id = fixed_run_id
        self.start_run_calls: list[tuple[tuple, dict]] = []

    async def start_run(self, *args, **kwargs):
        self.start_run_calls.append((args, kwargs))
        return self.fixed_run_id

    # Unused by this test but required so execute_async's post-start_run
    # branch (_stage_executor.kernel pre-registration) doesn't explode.
    # Leave `runs` absent so that branch is skipped.


@pytest.mark.asyncio
async def test_execute_async_start_run_matches_sync_signature():
    """K-3: async path must call start_run with the identical single-arg
    form that the sync execute() path uses.
    """
    contract = TaskContract(task_id="task-parity-001", goal="hello")
    sync_kernel = MockKernel(strict_mode=False)
    executor = RunExecutor(contract=contract, kernel=sync_kernel)

    recorder = _RecordingAsyncKernel()
    executor.kernel = recorder  # swap to the recording async kernel

    # We don't care about the full run completing — execute_async will
    # likely raise downstream once it tries to drive the (missing) turn
    # machinery.  The invariants we care about are set before that.
    with contextlib.suppress(Exception):
        await execute_async(executor)

    # K-3: exactly one call, positional task_id, no kwargs.
    assert len(recorder.start_run_calls) == 1
    args, kwargs = recorder.start_run_calls[0]
    assert args == (contract.task_id,), (
        f"async path must call start_run(task_id) positionally to mirror sync "
        f"execute(); got args={args!r} kwargs={kwargs!r}"
    )
    assert kwargs == {}


@pytest.mark.asyncio
async def test_execute_async_sets_run_id_and_monotonic():
    """K-2 + K-15: after start_run, executor._run_id matches the kernel's
    returned run_id and _run_start_monotonic is populated.
    """
    contract = TaskContract(task_id="task-parity-002", goal="hello")
    sync_kernel = MockKernel(strict_mode=False)
    executor = RunExecutor(contract=contract, kernel=sync_kernel)

    recorder = _RecordingAsyncKernel(fixed_run_id="async-run-42")
    executor.kernel = recorder

    with contextlib.suppress(Exception):
        await execute_async(executor)

    # K-2: _run_id equals what the kernel returned.
    assert executor._run_id == "async-run-42"
    # K-15: _run_start_monotonic initialized to a float > 0.
    assert executor._run_start_monotonic is not None
    assert isinstance(executor._run_start_monotonic, float)
    assert executor._run_start_monotonic > 0.0
