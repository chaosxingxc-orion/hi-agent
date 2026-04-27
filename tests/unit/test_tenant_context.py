"""Unit tests for hi_agent.server.tenant_context.

Layer 1 — Unit: verifies ContextVar isolation semantics and all public helpers.
No external I/O; no mocking required.
"""

from __future__ import annotations

import asyncio

import pytest
from hi_agent.server.tenant_context import (
    TenantContext,
    get_tenant_context,
    require_tenant_context,
    reset_tenant_context,
    set_tenant_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(**kwargs: object) -> TenantContext:
    defaults: dict[str, object] = {
        "tenant_id": "t-abc",
        "team_id": "team-1",
        "user_id": "u-xyz",
        "roles": ["read"],
        "scopes": [],
        "auth_method": "api_key",
        "request_id": "req-001",
    }
    defaults.update(kwargs)
    return TenantContext(**defaults)  # type: ignore[arg-type]  expiry_wave: Wave 17


# ---------------------------------------------------------------------------
# Basic set / get / reset cycle
# ---------------------------------------------------------------------------


def test_get_returns_none_when_not_set() -> None:
    """get_tenant_context() returns None when no value has been set."""
    # Each test runs in its own context; no prior set should be visible.
    # We reset any leftover value to be safe.
    token = set_tenant_context(_make_ctx())
    reset_tenant_context(token)

    assert get_tenant_context() is None


def test_set_and_get_roundtrip() -> None:
    ctx = _make_ctx(tenant_id="t-roundtrip")
    token = set_tenant_context(ctx)
    try:
        result = get_tenant_context()
        assert result is ctx
        assert result.tenant_id == "t-roundtrip"
    finally:
        reset_tenant_context(token)


def test_reset_restores_previous_value() -> None:
    first = _make_ctx(tenant_id="t-first")
    second = _make_ctx(tenant_id="t-second")

    tok1 = set_tenant_context(first)
    tok2 = set_tenant_context(second)

    assert get_tenant_context() is second

    reset_tenant_context(tok2)
    assert get_tenant_context() is first

    reset_tenant_context(tok1)
    assert get_tenant_context() is None


# ---------------------------------------------------------------------------
# require_tenant_context
# ---------------------------------------------------------------------------


def test_require_raises_when_not_set() -> None:
    token = set_tenant_context(_make_ctx())
    reset_tenant_context(token)

    with pytest.raises(RuntimeError, match="No TenantContext set for this request"):
        require_tenant_context()


def test_require_returns_context_when_set() -> None:
    ctx = _make_ctx(tenant_id="t-require")
    token = set_tenant_context(ctx)
    try:
        result = require_tenant_context()
        assert result is ctx
    finally:
        reset_tenant_context(token)


# ---------------------------------------------------------------------------
# Async task isolation — different tasks must not share context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tasks_have_independent_contexts() -> None:
    """Two concurrently running tasks must not see each other's TenantContext."""
    results: dict[str, str | None] = {}

    async def task_a() -> None:
        ctx = _make_ctx(tenant_id="tenant-A")
        token = set_tenant_context(ctx)
        # Yield to allow the event loop to run task_b before we read back.
        await asyncio.sleep(0)
        results["a"] = (get_tenant_context() or TenantContext("")).tenant_id
        reset_tenant_context(token)

    async def task_b() -> None:
        # task_b deliberately does NOT set a context.
        await asyncio.sleep(0)
        tc = get_tenant_context()
        results["b"] = tc.tenant_id if tc is not None else None

    await asyncio.gather(
        asyncio.create_task(task_a()),
        asyncio.create_task(task_b()),
    )

    assert results["a"] == "tenant-A", "task_a should see its own tenant_id"
    assert results["b"] is None, "task_b should not see task_a's TenantContext"


@pytest.mark.asyncio
async def test_tasks_with_different_tenant_ids_isolated() -> None:
    """Two tasks each setting different tenant IDs must not cross-contaminate."""
    results: dict[str, str] = {}

    async def worker(name: str, tenant_id: str) -> None:
        ctx = _make_ctx(tenant_id=tenant_id)
        token = set_tenant_context(ctx)
        await asyncio.sleep(0)
        tc = get_tenant_context()
        results[name] = tc.tenant_id if tc is not None else ""
        reset_tenant_context(token)

    await asyncio.gather(
        asyncio.create_task(worker("x", "tenant-X")),
        asyncio.create_task(worker("y", "tenant-Y")),
    )

    assert results["x"] == "tenant-X"
    assert results["y"] == "tenant-Y"
