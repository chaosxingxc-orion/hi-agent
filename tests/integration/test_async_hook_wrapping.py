"""Integration test: hooks fire when called inside a running event loop.

J3-4 regression guard — verifies that _invoke_capability_via_hooks()
does NOT skip pre_tool hooks when loop.is_running() is True.

The test calls _invoke_capability_via_hooks() directly from within an async
function (which guarantees loop.is_running() == True) so that the J3-4 code
path (ThreadPoolExecutor branch) is exercised without requiring the full
execute_async() pipeline.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from hi_agent.contracts import TaskContract, deterministic_id
from hi_agent.middleware.hooks import ExecutionHookManager, HookEvent, HookRegistry
from hi_agent.runner import RunExecutor

from tests.helpers.kernel_adapter_fixture import MockKernel


@pytest.mark.asyncio
async def test_pre_tool_hook_fires_inside_running_loop() -> None:
    """pre_tool hook must fire when _invoke_capability_via_hooks() runs inside an active loop.

    Before J3-4 the method detected loop.is_running() == True and bypassed
    all hooks with a direct _invoke_capability() call. After the fix it uses
    a ThreadPoolExecutor to run the hook chain in an isolated event loop.

    This test verifies the fix by:
    1. Creating an executor with a spy pre_tool hook.
    2. Calling _invoke_capability_via_hooks() from inside an async function
       (loop is guaranteed to be running at that point).
    3. Asserting the hook was invoked.
    """
    fired: list[str] = []

    def _pre_tool_hook(ctx: Any) -> Any:
        fired.append("fired")
        return ctx

    kernel = MockKernel(strict_mode=False)
    contract = TaskContract(
        task_id=deterministic_id("hook-loop-test"),
        goal="test hook firing inside running loop",
        task_family="test",
    )
    executor = RunExecutor(contract=contract, kernel=kernel)

    # Replace with a spy-augmented hook manager
    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL, _pre_tool_hook)
    executor._hook_manager = ExecutionHookManager(registry)
    executor._hook_registry = registry

    # Verify that we ARE inside a running loop (the async test runner provides this)
    loop = asyncio.get_event_loop()
    assert loop.is_running(), "Test must run inside an active event loop"

    # Build a minimal proposal and payload using a real registered capability.
    # The executor registers TRACE capabilities (analyze_goal, search_evidence,
    # build_draft, synthesize, evaluate_acceptance) during __init__.
    from unittest.mock import MagicMock
    proposal = MagicMock()
    proposal.action_kind = "analyze_goal"
    proposal.branch_id = "branch-0"

    payload = {
        "run_id": "test-run-j34",
        "stage_id": "S1_perceive",
        "branch_id": "branch-0",
        "action_kind": "analyze_goal",
        "seq": 0,
        "attempt": 1,
        "should_fail": False,
        "upstream_artifact_ids": [],
    }

    # Call the method that was broken — must not skip hooks.
    # The capability may succeed or fail; what matters is that the hook fired.
    with contextlib.suppress(Exception):
        executor._invoke_capability_via_hooks(proposal, payload)

    # The hook must have fired via the ThreadPoolExecutor path
    assert len(fired) > 0, (
        "pre_tool hook never fired inside a running event loop; "
        "J3-4 async hook bypass regression detected."
    )
