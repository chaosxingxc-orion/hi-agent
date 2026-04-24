"""E2E test fixtures — requires a running hi_agent HTTP server.

Tests in this package drive the public HTTP interface of hi_agent as per
Rule 4 Layer-3 E2E requirements. All tests skip gracefully when no server
is reachable.

Start the server before running these tests:
    python -m hi_agent serve --port 8080

Override the server URL:
    HI_AGENT_E2E_URL=http://127.0.0.1:8080 pytest tests/e2e/http_server/
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("HI_AGENT_E2E_URL", "http://127.0.0.1:8080")


@pytest.fixture(scope="session")
def e2e_client():
    """HTTP client for e2e tests. Skips the session if server is not reachable."""
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=3)
        r.raise_for_status()
    except Exception:
        pytest.skip(
            f"hi_agent server not reachable at {BASE_URL} — "
            "set HI_AGENT_E2E_URL or start the server with: "
            "python -m hi_agent serve --port 8080"
        )
    client = httpx.Client(base_url=BASE_URL, timeout=30)
    yield client
    client.close()
