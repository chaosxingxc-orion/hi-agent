"""Idempotency facade — thin wrapper over hi_agent IdempotencyStore (W24 I-D).

Per R-AS-1 the facade module is the only seam allowed to reach into
hi_agent internals. The middleware that rides on top of this facade
imports ONLY from agent_server.* — never from hi_agent.*.

LOC budget: <=200 (R-AS-8).

Responsibilities:
  * Hash the canonical request body to a stable digest.
  * Reserve a new idempotency slot or replay/409 an existing one.
  * Persist the final HTTP response so retries replay byte-identical
    content.
  * Strip identity metadata (request_id, trace_id, _response_timestamp)
    before storing so replays do not leak prior request identifiers
    (HD-7 closure).

The facade does NOT itself perform HTTP work; the middleware does.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hi_agent.server.idempotency import IdempotencyStore

# Identity metadata keys stripped from the persisted response so replays
# never leak the original request's tracing fields (HD-7).
_IDENTITY_KEYS_TO_STRIP: tuple[str, ...] = (
    "request_id",
    "trace_id",
    "_response_timestamp",
)


def _canonical_body_hash(body: dict[str, Any]) -> str:
    """Return SHA-256 hex digest of canonical sorted-key JSON body."""
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _strip_identity(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with identity metadata fields removed (HD-7)."""
    cleaned = {k: v for k, v in payload.items() if k not in _IDENTITY_KEYS_TO_STRIP}
    return cleaned


class IdempotencyFacade:
    """Tenant-scoped wrapper over the SQLite-backed IdempotencyStore.

    Methods are intentionally minimal: middleware-level callers should
    not need to know about TTL, run_id placeholders, or any persistence
    detail beyond reserve / replay / mark.
    """

    def __init__(
        self,
        *,
        store: IdempotencyStore | None = None,
        db_path: str | Path | None = None,
        is_strict: bool = False,
    ) -> None:
        """Construct a facade backed by an existing or new store.

        Either ``store`` (already-built) or ``db_path`` (path for a fresh
        store) must be supplied. Tests use ``db_path=tmp_path/...``.

        W31-N (N.4): ``is_strict`` carries the posture-derived strict flag.
        Route handlers consult :attr:`is_strict` to decide whether a missing
        ``Idempotency-Key`` is a hard 400 or a dev-tolerable warning. The
        bootstrap module is the single seam allowed to derive this value
        from :class:`hi_agent.config.posture.Posture`; route handlers
        themselves never import Posture.
        """
        if store is None and db_path is None:
            raise ValueError("IdempotencyFacade requires either store or db_path")
        if store is not None:
            self._store = store
            self._owns_store = False
        else:
            # db_path branch — caller asked us to build a fresh store
            assert db_path is not None  # mypy: above guard ensures it
            self._store = IdempotencyStore(db_path=db_path)
            self._owns_store = True
        self._is_strict = bool(is_strict)

    @property
    def is_strict(self) -> bool:
        """Return whether the strict posture rule applies (W31-N N.4)."""
        return self._is_strict

    # ------------------------------------------------------------------
    # Public API used by IdempotencyMiddleware
    # ------------------------------------------------------------------

    def reserve_or_replay(
        self,
        *,
        tenant_id: str,
        key: str,
        body: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None, int]:
        """Reserve or replay an idempotency slot for ``key``.

        Returns a tuple ``(outcome, response_or_None, status_code)`` where:
          * ``outcome == "created"``  → first time this key is seen; the
            middleware MUST forward the request to the handler and then
            call ``mark_complete``. ``response_or_None`` is None.
          * ``outcome == "replayed"`` → identical request seen before;
            ``response_or_None`` carries the stored JSON-decoded body and
            ``status_code`` is the cached HTTP status (default 200).
          * ``outcome == "conflict"`` → key reused with a different body;
            middleware MUST return HTTP 409 with the conflict envelope.

        ``key`` is required and must be non-empty. The hash is computed
        deterministically from the canonical JSON-serialized body.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for idempotency lookup")
        if not key:
            raise ValueError("idempotency key must be non-empty")
        request_hash = _canonical_body_hash(body)
        outcome, record = self._store.reserve_or_replay(
            tenant_id=tenant_id,
            idempotency_key=key,
            request_hash=request_hash,
            run_id=f"reserved::{key}",
        )
        if outcome == "created":
            return "created", None, 0
        if outcome == "replayed":
            cached_body, cached_status = self._decode_snapshot(record.response_snapshot)
            return "replayed", cached_body, cached_status
        # conflict
        return "conflict", None, 409

    def mark_complete(
        self,
        *,
        tenant_id: str,
        key: str,
        response_json: dict[str, Any],
        status_code: int = 200,
    ) -> None:
        """Persist the final response body so replays return it verbatim.

        Identity metadata fields are stripped before storage (HD-7) so
        retries do not surface a stale request_id / trace_id.
        """
        if not tenant_id or not key:
            return
        cleaned = _strip_identity(dict(response_json))
        snapshot = json.dumps(
            {"status_code": int(status_code), "body": cleaned},
            sort_keys=True,
            ensure_ascii=True,
        )
        self._store.mark_complete(
            tenant_id=tenant_id,
            idempotency_key=key,
            response_json=snapshot,
        )

    def release(self, *, tenant_id: str, key: str) -> None:
        """Release a reserved slot when handler dispatch fails.

        Used by middleware on 5xx errors so a retry can re-attempt rather
        than collide forever with the abandoned reservation.
        """
        if not tenant_id or not key:
            return
        self._store.release(tenant_id, key)

    def close(self) -> None:
        """Close the underlying store iff this facade constructed it."""
        if self._owns_store:
            self._store.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_snapshot(snapshot: str) -> tuple[dict[str, Any], int]:
        """Return ``(body, status_code)`` from a stored snapshot.

        Snapshots are written by ``mark_complete`` as the canonical JSON
        envelope ``{"status_code": int, "body": {...}}``. Empty snapshots
        (still pending) produce an explicit pending envelope so middleware
        can degrade gracefully when a prior request has not finished.
        """
        if not snapshot:
            return ({"error": "ConflictError", "message": "request still in flight"}, 409)
        try:
            decoded = json.loads(snapshot)
        except json.JSONDecodeError:
            return ({"error": "InternalError", "message": "snapshot corrupt"}, 500)
        body = decoded.get("body")
        if not isinstance(body, dict):
            return ({"error": "InternalError", "message": "snapshot malformed"}, 500)
        status_code = int(decoded.get("status_code", 200))
        return body, status_code
