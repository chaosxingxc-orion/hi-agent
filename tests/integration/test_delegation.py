"""Tests for hi_agent.task_mgmt.delegation (DelegationManager).

Covers:
- ChildRunPoller: completion and timeout paths
- ResultSummarizer: short output, truncation without LLM, LLM call for long output
- DelegationManager: single request end-to-end, concurrency limiting,
  exception handling, and context formatting
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio  # noqa: F401 - imported for pytest-asyncio registration  expiry_wave: Wave 29
from hi_agent.task_mgmt.delegation import (
    ChildRunPoller,
    DelegationConfig,
    DelegationManager,
    DelegationRequest,
    DelegationResult,
    ResultSummarizer,
)

from tests._helpers.run_states import SUCCESS_STATES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kernel(lifecycle_states: list[str], output: str | None = None) -> MagicMock:
    """Build a mock kernel dependency whose query_run cycles through *lifecycle_states*.

    The last state is returned for all subsequent calls once the list is
    exhausted.  This is a mock of the *kernel dependency* injected into
    ChildRunPoller/DelegationManager (SUT), not a mock of the SUT itself.
    """
    mock_kernel = MagicMock()
    responses = [
        {
            "lifecycle_state": s,
            "output": output if s in SUCCESS_STATES else None,
        }
        for s in lifecycle_states
    ]
    # Pad with the last response so the poller doesn't IndexError.
    responses_iter = iter(responses)
    last: dict = responses[-1]

    def _query_run(run_id: str) -> dict:
        try:
            return next(responses_iter)
        except StopIteration:
            return last

    mock_kernel.query_run.side_effect = _query_run
    return mock_kernel


# ---------------------------------------------------------------------------
# ChildRunPoller tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_child_run_poller_completes() -> None:
    """Poller should exit as soon as lifecycle_state becomes 'completed'."""
    mock_kernel = _make_kernel(["running", "running", "completed"], output="done!")
    poller = ChildRunPoller(mock_kernel, poll_interval=0.01)

    status, raw = await poller.wait_for_completion("child-1", timeout=5.0)

    assert status == "completed"
    assert raw == "done!"
    # query_run must have been called at least twice (running x 2, completed)
    assert mock_kernel.query_run.call_count >= 2


@pytest.mark.asyncio
async def test_child_run_poller_timeout() -> None:
    """Poller should return ('timeout', None) when the run never terminates."""
    mock_kernel = _make_kernel(["running"] * 100)
    poller = ChildRunPoller(mock_kernel, poll_interval=0.01)

    status, raw = await poller.wait_for_completion("child-2", timeout=0.05)

    assert status == "timeout"
    assert raw is None


# ---------------------------------------------------------------------------
# ResultSummarizer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_summarizer_short_output() -> None:
    """Short output (≤ max_chars) must be returned verbatim without calling LLM."""
    llm = AsyncMock()
    summarizer = ResultSummarizer(llm)

    result = await summarizer.summarize("do something", "short output", max_chars=500)

    assert result == "short output"
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_result_summarizer_long_output_truncated_without_llm() -> None:
    """When llm=None, output longer than max_chars must be truncated."""
    summarizer = ResultSummarizer(llm=None)
    long_output = "x" * 3000

    result = await summarizer.summarize("goal", long_output, max_chars=100)

    assert len(result) == 100
    assert result == "x" * 100


@pytest.mark.asyncio
async def test_result_summarizer_calls_llm_for_long_output() -> None:
    """ResultSummarizer should invoke LLM.complete() when output exceeds max_chars."""
    from hi_agent.llm.protocol import LLMResponse, TokenUsage

    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(
        content="Summary of the output.",
        model="mock-light",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )

    summarizer = ResultSummarizer(llm=llm)
    long_output = "y" * 3000

    result = await summarizer.summarize("my goal", long_output, max_chars=500)

    assert result == "Summary of the output."
    assert llm.complete.call_count == 1
    # Verify the prompt mentions the goal and the output
    request_arg = llm.complete.call_args[0][0]
    assert "my goal" in request_arg.messages[0]["content"]
    assert "y" * 100 in request_arg.messages[0]["content"]  # at least first chars present


# ---------------------------------------------------------------------------
# DelegationManager tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegation_manager_single_request() -> None:
    """End-to-end: single request is spawned, polled, summarised, and returned."""
    from hi_agent.llm.protocol import LLMResponse, TokenUsage

    mock_kernel = MagicMock()
    mock_kernel.spawn_child_run_async = AsyncMock(return_value="child-run-001")
    mock_kernel.query_run.return_value = {"lifecycle_state": "completed", "output": "task done"}

    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(
        content="Summarised result.",
        model="mock-light",
        usage=TokenUsage(),
    )

    config = DelegationConfig(max_concurrent=2, poll_interval_seconds=0.01)
    manager = DelegationManager(kernel=mock_kernel, config=config, llm=llm)

    req = DelegationRequest(goal="Analyse data", task_id="t-001", timeout_seconds=5.0)
    results = await manager.delegate([req], parent_run_id="parent-run-001")

    assert len(results) == 1
    result = results[0]
    assert result.child_run_id == "child-run-001"
    assert result.status == "completed"
    assert result.request is req
    assert isinstance(result.duration_seconds, float)
    mock_kernel.spawn_child_run_async.assert_awaited_once_with(
        "parent-run-001", "t-001", config={"budget_fraction": 0.25, "max_turns": 20}
    )


@pytest.mark.asyncio
async def test_delegation_manager_concurrency_limit() -> None:
    """With max_concurrent=2 and 5 requests, at most 2 children run concurrently."""
    active: list[int] = [0]
    peak: list[int] = [0]

    async def fake_spawn(parent_run_id, task_id, config=None) -> str:
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.05)  # simulate child run execution time
        active[0] -= 1
        return f"child-{task_id}"

    mock_kernel = MagicMock()
    mock_kernel.spawn_child_run_async = fake_spawn
    # All spawned children complete immediately on first poll.
    mock_kernel.query_run.return_value = {"lifecycle_state": "completed", "output": None}

    config = DelegationConfig(max_concurrent=2, poll_interval_seconds=0.01)
    manager = DelegationManager(kernel=mock_kernel, config=config, llm=None)

    requests = [
        DelegationRequest(goal=f"Task {i}", task_id=f"t-{i}", timeout_seconds=5.0) for i in range(5)
    ]
    results = await manager.delegate(requests, parent_run_id="parent-run-X")

    assert len(results) == 5
    # Peak active count must never exceed max_concurrent.
    assert peak[0] <= 2


@pytest.mark.asyncio
async def test_delegation_manager_handles_exception() -> None:
    """When spawn raises, the result should carry status='failed' with error text."""
    mock_kernel = MagicMock()
    mock_kernel.spawn_child_run_async = AsyncMock(side_effect=RuntimeError("kernel unavailable"))

    config = DelegationConfig(max_concurrent=1, poll_interval_seconds=0.01)
    manager = DelegationManager(kernel=mock_kernel, config=config, llm=None)

    req = DelegationRequest(goal="Failing task", task_id="t-fail", timeout_seconds=5.0)
    results = await manager.delegate([req], parent_run_id="parent-run-Y")

    assert len(results) == 1
    result = results[0]
    assert result.status == "failed"
    assert "kernel unavailable" in (result.error or "")
    assert result.request is req


@pytest.mark.asyncio
async def test_delegation_manager_gather_exception_wrapping() -> None:
    """Exceptions raised inside _delegate_one are captured, not propagated."""
    mock_kernel = MagicMock()

    async def bad_spawn(*args, **kwargs):
        raise ValueError("unexpected error")

    mock_kernel.spawn_child_run_async = bad_spawn

    config = DelegationConfig(max_concurrent=3, poll_interval_seconds=0.01)
    manager = DelegationManager(kernel=mock_kernel, config=config, llm=None)

    requests = [
        DelegationRequest(goal="Task A", task_id="a", timeout_seconds=5.0),
        DelegationRequest(goal="Task B", task_id="b", timeout_seconds=5.0),
    ]
    # Should not raise — exceptions are wrapped in DelegationResult.
    results = await manager.delegate(requests, parent_run_id="parent-run-Z")

    assert len(results) == 2
    for r in results:
        assert r.status == "failed"


# ---------------------------------------------------------------------------
# format_results_for_context tests
# ---------------------------------------------------------------------------


def test_format_results_for_context() -> None:
    """Formatted output should mention all sub-tasks, statuses, and summaries."""
    config = DelegationConfig()
    manager = DelegationManager(kernel=MagicMock(), config=config)

    req1 = DelegationRequest(goal="Analyse revenue", task_id="t1")
    req2 = DelegationRequest(goal="Generate report", task_id="t2")

    results = [
        DelegationResult(
            request=req1,
            child_run_id="c-1",
            status="completed",
            summary="Revenue increased by 12%.",
            duration_seconds=42.5,
        ),
        DelegationResult(
            request=req2,
            child_run_id="c-2",
            status="failed",
            summary="",
            duration_seconds=10.0,
            error="Out of budget",
        ),
    ]

    output = manager.format_results_for_context(results)

    # Both goals should appear.
    assert "Analyse revenue" in output
    assert "Generate report" in output
    # Statuses must be present.
    assert "completed" in output
    assert "failed" in output
    # The summary text must be present.
    assert "Revenue increased by 12%." in output
    # Error text for the second task.
    assert "Out of budget" in output
    # Duration for the first task.
    assert "42.5" in output
    # Section headings.
    assert "Sub-task execution results" in output
    assert "Sub-task 1" in output
    assert "Sub-task 2" in output


def test_format_results_for_context_empty() -> None:
    """Empty results list should produce a graceful placeholder message."""
    config = DelegationConfig()
    manager = DelegationManager(kernel=MagicMock(), config=config)

    output = manager.format_results_for_context([])
    assert "Sub-task execution results" in output
    assert "no sub-tasks" in output


# ---------------------------------------------------------------------------
# _build_config tests
# ---------------------------------------------------------------------------


def test_build_config_includes_tool_allowlist() -> None:
    """_build_config must propagate tool_allowlist when specified."""
    config = DelegationConfig()
    manager = DelegationManager(kernel=MagicMock(), config=config)

    req = DelegationRequest(
        goal="Search docs",
        task_id="t-search",
        tool_allowlist=["search", "read_file"],
        budget_fraction=0.1,
        max_turns=10,
        config={"extra_key": "extra_val"},
    )
    result = manager._build_config(req)

    assert result["tool_allowlist"] == ["search", "read_file"]
    assert result["budget_fraction"] == 0.1
    assert result["max_turns"] == 10
    assert result["extra_key"] == "extra_val"


def test_build_config_no_tool_allowlist() -> None:
    """_build_config must not include tool_allowlist key when it is None."""
    config = DelegationConfig()
    manager = DelegationManager(kernel=MagicMock(), config=config)

    req = DelegationRequest(goal="Task", task_id="t-plain", tool_allowlist=None)
    result = manager._build_config(req)

    assert "tool_allowlist" not in result
    assert result["budget_fraction"] == 0.25
    assert result["max_turns"] == 20
