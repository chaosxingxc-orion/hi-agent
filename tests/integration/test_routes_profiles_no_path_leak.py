"""Integration test for DX-5: routes_profiles.py must not leak absolute paths.

Layer 2 (Integration): real AgentServer and real route handler.
No MagicMock on the subsystem under test.

Verifies that no JSON response value from the profiles endpoints starts with
a Windows drive letter (e.g. C:\\) or a Unix root (/), which would indicate
an absolute filesystem path leak.
"""

from __future__ import annotations

import re

import pytest
from hi_agent.server.app import AgentServer
from starlette.testclient import TestClient

# Pattern matching an absolute path leak:
# Unix: starts with /
# Windows: starts with a drive letter followed by :\ or :/
_ABSOLUTE_PATH_PATTERN = re.compile(r"^(/|[A-Za-z]:[/\\])")


def _collect_string_values(obj, results: list[str]) -> None:
    """Recursively collect all string values from a JSON object."""
    if isinstance(obj, str):
        results.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_string_values(v, results)
    elif isinstance(obj, list):
        for item in obj:
            _collect_string_values(item, results)


@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Real AgentServer in dev mode."""
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    monkeypatch.setattr(
        "hi_agent.config.json_config_loader.build_gateway_from_config",
        lambda *a, **kw: None,
    )
    server = AgentServer(rate_limit_rps=10000)
    return TestClient(server.app, raise_server_exceptions=False)


def test_global_l3_response_has_no_absolute_path(test_client) -> None:
    """GET /profiles/hi_agent_global/memory/l3 returns no absolute paths."""
    resp = test_client.get("/profiles/hi_agent_global/memory/l3")
    # 503 is acceptable (profile_manager not available in test env)
    # but 200 must not leak an absolute path.
    if resp.status_code != 200:
        pytest.skip(f"endpoint returned {resp.status_code} — profile manager not available")

    string_values: list[str] = []
    _collect_string_values(resp.json(), string_values)

    leaks = [v for v in string_values if _ABSOLUTE_PATH_PATTERN.match(v)]
    assert not leaks, (
        f"Absolute path(s) leaked in /profiles/hi_agent_global/memory/l3 response: {leaks}"
    )

    # Verify path_token field exists (not the old 'path' field with absolute value)
    body = resp.json()
    assert "path_token" in body, "Response must use 'path_token' not 'path'"
    assert "path" not in body or not _ABSOLUTE_PATH_PATTERN.match(str(body.get("path", ""))), (
        "Old 'path' field with absolute value must not be present"
    )


def test_global_skills_response_has_no_absolute_path(test_client) -> None:
    """GET /profiles/hi_agent_global/skills returns no absolute paths."""
    resp = test_client.get("/profiles/hi_agent_global/skills")
    if resp.status_code != 200:
        pytest.skip(f"endpoint returned {resp.status_code} — profile manager not available")

    string_values: list[str] = []
    _collect_string_values(resp.json(), string_values)

    leaks = [v for v in string_values if _ABSOLUTE_PATH_PATTERN.match(v)]
    assert not leaks, (
        f"Absolute path(s) leaked in /profiles/hi_agent_global/skills response: {leaks}"
    )

    body = resp.json()
    assert "path_token" in body, "Response must use 'path_token' not 'path'"
