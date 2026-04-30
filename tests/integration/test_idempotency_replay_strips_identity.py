"""HD-7 (W24-J7): idempotency replay strips identity metadata.

Verifies:
1. ``IdempotencyStore._normalize_response_for_replay`` strips
   ``request_id`` / ``trace_id`` / ``x_request_id`` / ``_response_timestamp``
   from the JSON payload before returning.
2. ``mark_complete`` persists the *normalized* snapshot so a subsequent
   replay does not re-emit the original request's trace metadata.
3. Non-identity fields are preserved exactly.
"""

from __future__ import annotations

import json
from pathlib import Path

from hi_agent.server.idempotency import IdempotencyStore


def test_normalize_response_strips_all_identity_fields() -> None:
    raw = json.dumps(
        {
            "run_id": "run-1",
            "state": "succeeded",
            "request_id": "req-original-1",
            "trace_id": "trace-original-1",
            "x_request_id": "x-original-1",
            "_response_timestamp": 1700000000.5,
        }
    )
    out = IdempotencyStore._normalize_response_for_replay(raw)
    payload = json.loads(out)
    for stripped in ("request_id", "trace_id", "x_request_id", "_response_timestamp"):
        assert stripped not in payload, f"HD-7: {stripped} must be stripped"
    # Non-identity fields preserved
    assert payload["run_id"] == "run-1"
    assert payload["state"] == "succeeded"


def test_normalize_response_preserves_clean_payload() -> None:
    """A snapshot with no identity fields must return byte-identical."""
    raw = json.dumps({"run_id": "run-2", "state": "succeeded"})
    out = IdempotencyStore._normalize_response_for_replay(raw)
    assert out == raw


def test_normalize_response_handles_non_json_input() -> None:
    """Plain text or invalid JSON is returned unchanged."""
    assert IdempotencyStore._normalize_response_for_replay("") == ""
    assert IdempotencyStore._normalize_response_for_replay("not json") == "not json"


def test_normalize_response_handles_non_object_json() -> None:
    """JSON arrays / scalars are not objects → return unchanged."""
    raw = json.dumps([1, 2, 3])
    assert IdempotencyStore._normalize_response_for_replay(raw) == raw


def test_mark_complete_strips_identity_at_write_time(tmp_path: Path) -> None:
    """End-to-end: mark_complete persists the normalized snapshot."""
    store = IdempotencyStore(db_path=str(tmp_path / "idem.db"))
    store.reserve_or_replay(
        tenant_id="tenant-A",
        idempotency_key="key-1",
        request_hash="hash-1",
        run_id="run-x",
    )
    raw = json.dumps(
        {
            "run_id": "run-x",
            "state": "succeeded",
            "request_id": "req-leak",
            "trace_id": "trace-leak",
            "_response_timestamp": 1700000000.5,
        }
    )
    store.mark_complete(
        tenant_id="tenant-A",
        idempotency_key="key-1",
        response_json=raw,
        terminal_state="succeeded",
    )
    # Read back via the public reserve_or_replay path on a matching hash.
    outcome, record = store.reserve_or_replay(
        tenant_id="tenant-A",
        idempotency_key="key-1",
        request_hash="hash-1",
        run_id="run-x",
    )
    assert outcome == "replayed"
    persisted = json.loads(record.response_snapshot)
    assert "request_id" not in persisted
    assert "trace_id" not in persisted
    assert "_response_timestamp" not in persisted
    assert persisted["run_id"] == "run-x"
    assert persisted["state"] == "succeeded"


def test_identity_fields_constant_is_documented() -> None:
    """The contract: which fields are considered identity metadata."""
    expected = {"request_id", "trace_id", "x_request_id", "_response_timestamp"}
    assert set(IdempotencyStore._IDENTITY_FIELDS_STRIPPED_ON_REPLAY) == expected
