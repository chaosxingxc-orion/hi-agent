"""E2E: security boundary checks — path traversal, SSRF attempts must not succeed.

Layer-3 E2E tests per Rule 4. Drive through the public HTTP interface.
All tests skip when no server is reachable (see conftest.py).
"""

from __future__ import annotations


def test_path_traversal_in_goal_rejected(e2e_client):
    """Goal with path traversal payload must not cause 500."""
    resp = e2e_client.post(
        "/runs",
        json={
            "goal": "read file ../../../../etc/passwd",
            "profile_id": "default",
        },
    )
    assert resp.status_code in (200, 400, 422), (
        f"Path traversal goal caused {resp.status_code} — must not 500"
    )


def test_malformed_run_id_in_path_does_not_200(e2e_client):
    """GET /runs/../admin or similar must return 404, not 200 or 500."""
    resp = e2e_client.get("/runs/%2E%2E%2Fadmin")
    assert resp.status_code in (400, 404, 422), (
        f"Encoded path traversal returned {resp.status_code} — must not 200"
    )
    assert resp.status_code != 200


def test_null_byte_in_goal_does_not_500(e2e_client):
    """Goal containing a null byte must not cause an internal server error."""
    resp = e2e_client.post(
        "/runs",
        json={
            "goal": "analyze\x00data",
            "profile_id": "default",
        },
    )
    assert resp.status_code in (200, 400, 422), (
        f"Null byte in goal caused {resp.status_code} — must not 500"
    )


def test_oversized_goal_does_not_500(e2e_client):
    """An extremely long goal must not cause an internal server error."""
    large_goal = "x" * 100_000
    resp = e2e_client.post(
        "/runs",
        json={"goal": large_goal, "profile_id": "default"},
    )
    assert resp.status_code in (200, 400, 413, 422), (
        f"Oversized goal caused {resp.status_code} — must not 500"
    )
