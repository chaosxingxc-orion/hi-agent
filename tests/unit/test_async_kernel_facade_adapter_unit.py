"""Unit tests for AsyncKernelFacadeAdapter delegation logic (HD-9 / W24-J9).

This is a **unit test** — the helper ``_make_adapter()`` patches
``KernelFacadeAdapter`` with a MagicMock and asserts that the async wrapper
delegates correctly to the sync underlying. That is legitimate Rule 4
behaviour for the unit tier (the unit under test is the *delegation logic*
of ``AsyncKernelFacadeAdapter``; the patched ``KernelFacadeAdapter`` is its
external dependency, not the subject).

This file used to live under ``tests/integration/`` and was tagged
``@pytest.mark.skip(...)`` per the H1-Track4 integration-test-honesty audit
because mocking the subsystem under test inside an integration test is a
Rule 4 violation. W24-J9 takes option (b) from the plan: move to the unit
tier with an honest label so Rule 4 is satisfied at the integration tier
and the assertions can be unskipped here.

A future track may add a separate integration-tier test that wires a real
``KernelFacadeAdapter`` against an in-process ``KernelFacade`` stub; until
then, integration-tier coverage of the async delegation lives in the live
e2e suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hi_agent.runtime_adapter.async_kernel_facade_adapter import (
    AsyncKernelFacadeAdapter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter() -> tuple[AsyncKernelFacadeAdapter, MagicMock]:
    """Return an AsyncKernelFacadeAdapter wired to a MagicMock _sync.

    KernelFacadeAdapter.__init__ enforces a real KernelFacade instance, so we
    patch it out here.  This is legitimate mock usage: the unit under test is
    AsyncKernelFacadeAdapter's delegation logic, not KernelFacadeAdapter itself.
    """
    sync_mock = MagicMock()
    with patch(
        "hi_agent.runtime_adapter.async_kernel_facade_adapter.KernelFacadeAdapter",
        return_value=sync_mock,
    ):
        facade = MagicMock()
        adapter = AsyncKernelFacadeAdapter(facade)
    return adapter, sync_mock


# ---------------------------------------------------------------------------
# resolve_escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_escalation_delegates_to_sync() -> None:
    """resolve_escalation must call _sync.resolve_escalation with correct args."""
    adapter, sync_mock = _make_adapter()
    sync_mock.resolve_escalation.return_value = None

    with patch("asyncio.to_thread", new=_fake_to_thread):
        await adapter.resolve_escalation(
            "run-001",
            resolution_notes="all clear",
            caused_by="human-gate-A",
        )

    sync_mock.resolve_escalation.assert_called_once_with(
        "run-001",
        resolution_notes="all clear",
        caused_by="human-gate-A",
    )


@pytest.mark.asyncio
async def test_resolve_escalation_defaults_to_none() -> None:
    """resolve_escalation with no kwargs passes None for both optional args."""
    adapter, sync_mock = _make_adapter()
    sync_mock.resolve_escalation.return_value = None

    with patch("asyncio.to_thread", new=_fake_to_thread):
        await adapter.resolve_escalation("run-002")

    sync_mock.resolve_escalation.assert_called_once_with(
        "run-002",
        resolution_notes=None,
        caused_by=None,
    )


# ---------------------------------------------------------------------------
# spawn_child_run (sync version)
# ---------------------------------------------------------------------------


def test_spawn_child_run_sync_delegates_to_sync() -> None:
    """spawn_child_run (sync) must call _sync.spawn_child_run and return its result."""
    adapter, sync_mock = _make_adapter()
    sync_mock.spawn_child_run.return_value = "child-run-042"

    result = adapter.spawn_child_run("parent-001", "task-abc", {"key": "val"})

    assert result == "child-run-042"
    sync_mock.spawn_child_run.assert_called_once_with("parent-001", "task-abc", {"key": "val"})


def test_spawn_child_run_sync_no_config() -> None:
    """spawn_child_run with config=None passes None to the sync adapter."""
    adapter, sync_mock = _make_adapter()
    sync_mock.spawn_child_run.return_value = "child-run-001"

    result = adapter.spawn_child_run("parent-002", "task-xyz")

    assert result == "child-run-001"
    sync_mock.spawn_child_run.assert_called_once_with("parent-002", "task-xyz", None)


# ---------------------------------------------------------------------------
# Protocol completeness smoke test
# ---------------------------------------------------------------------------


def test_protocol_no_missing_methods() -> None:
    """AsyncKernelFacadeAdapter must implement every method in RuntimeAdapter."""
    import inspect

    from hi_agent.runtime_adapter.protocol import RuntimeAdapter

    proto_methods = {
        m for m, v in inspect.getmembers(RuntimeAdapter) if not m.startswith("_") and callable(v)
    }
    adapter_methods = {m for m in dir(AsyncKernelFacadeAdapter) if not m.startswith("_")}
    missing = proto_methods - adapter_methods
    assert not missing, f"AsyncKernelFacadeAdapter is missing protocol methods: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Internal helper — synchronous stand-in for asyncio.to_thread in tests
# ---------------------------------------------------------------------------


async def _fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Call *func* directly so tests work without a real thread pool."""
    return func(*args, **kwargs)
