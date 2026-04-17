"""Unit tests for operation_policy RBAC/SOC decorator (HI-W1-D5-001)."""

import pytest
from hi_agent.auth.operation_policy import OPERATION_POLICIES, RoutePolicy, require_operation


def test_policy_table_exhaustive():
    expected_ops = {"skill.promote", "skill.evolve", "memory.consolidate"}
    assert set(OPERATION_POLICIES.keys()) == expected_ops


def test_skill_promote_requires_soc_separation():
    policy = OPERATION_POLICIES["skill.promote"]
    assert policy.require_soc_separation is True
    assert "approver" in policy.required_roles


def test_skill_evolve_requires_soc_separation():
    assert OPERATION_POLICIES["skill.evolve"].require_soc_separation is True


def test_memory_consolidate_no_soc():
    assert OPERATION_POLICIES["memory.consolidate"].require_soc_separation is False


def test_dev_bypass_enabled_by_default():
    for policy in OPERATION_POLICIES.values():
        assert policy.dev_bypass is True


def test_require_operation_raises_403_missing_role_in_prod():
    """Decorator produces 403 for wrong role in prod-real."""
    import asyncio
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    @require_operation("skill.promote")
    async def handler(request):
        return {"ok": True}

    mock_request = MagicMock()
    mock_request.headers = {"X-Role": "submitter"}
    mock_request.app.state.runtime_mode = "prod-real"

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(handler(mock_request))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["reason"] == "missing_role"


def test_require_operation_allows_dev_bypass():
    """Decorator allows dev-smoke without token."""
    import asyncio
    from unittest.mock import MagicMock

    @require_operation("skill.promote")
    async def handler(request):
        return {"ok": True}

    mock_request = MagicMock()
    mock_request.headers = {"X-Role": "submitter"}
    mock_request.app.state.runtime_mode = "dev-smoke"

    result = asyncio.run(handler(mock_request))
    assert result == {"ok": True}


def test_require_operation_raises_403_soc_violation_in_prod():
    """Decorator produces 403 when submitter == approver for SOC-required operations."""
    import asyncio
    from fastapi import HTTPException
    from unittest.mock import MagicMock

    @require_operation("skill.promote")
    async def handler(request):
        return {"ok": True}

    mock_request = MagicMock()
    mock_request.headers = {
        "X-Role": "approver",
        "X-Submitter": "alice",
        "X-Approver": "alice",
    }
    mock_request.app.state.runtime_mode = "prod-real"

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(handler(mock_request))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["reason"] == "soc_violation"


def test_require_operation_success_in_prod():
    """Decorator allows valid role + distinct submitter/approver in prod."""
    import asyncio
    from unittest.mock import MagicMock

    @require_operation("skill.promote")
    async def handler(request):
        return {"ok": True}

    mock_request = MagicMock()
    mock_request.headers = {
        "X-Role": "approver",
        "X-Submitter": "alice",
        "X-Approver": "bob",
    }
    mock_request.app.state.runtime_mode = "prod-real"

    result = asyncio.run(handler(mock_request))
    assert result == {"ok": True}
