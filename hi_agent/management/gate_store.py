"""Durable SQLite-backed gate store."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from time import time
from typing import TYPE_CHECKING, ClassVar

from hi_agent.management.gate_api import GateRecord, GateStatus, InMemoryGateAPI
from hi_agent.management.gate_context import GateContext
from hi_agent.management.gate_timeout import GateTimeoutPolicy
from hi_agent.observability.silent_degradation import record_silent_degradation

if TYPE_CHECKING:
    from hi_agent.context.run_execution_context import RunExecutionContext

_logger = logging.getLogger(__name__)


def _warn_unscoped_gate_read(
    method: str, gate_ref: str | None, *, internal_unscoped: bool = False
) -> None:
    """Emit a WARNING (dev) or raise ValueError (strict) for unscoped gate reads.

    When ``internal_unscoped=True`` the call is from a process-internal caller
    (e.g. resolve, apply_timeouts) that legitimately reads across tenants;
    no warning or error is emitted.
    """
    if internal_unscoped:
        return
    try:
        from hi_agent.config.posture import Posture

        p = Posture.from_env()
        if p.is_strict:
            raise ValueError(
                f"Gate read {method!r} called without tenant_id under strict posture "
                f"(gate_ref={gate_ref!r}). Pass tenant_id= or use internal_unscoped=True "
                "(only for process-internal callers)."
            )
        _logger.warning(
            "Gate read %s called without tenant_id under strict posture "
            "(gate_ref=%s); cross-tenant gate pool is being read",
            method,
            gate_ref,
        )
    except ValueError:
        raise
    except Exception as exc:
        record_silent_degradation(
            component="management.gate_store._check_tenant_scope",
            reason="posture_lookup_failed",
            exc=exc,
        )
        return


class SQLiteGateStore:
    """Durable gate store backed by SQLite.

    Schema-compatible with InMemoryGateAPI interface so it can be swapped in
    transparently. Only uses primitive types in the DB schema; complex objects
    are serialized to JSON payload column.

    Thread-safe for concurrent in-process access (WAL mode + threading.Lock).
    """

    _SCHEMA_VERSION = 1

    _DDL = """
    CREATE TABLE IF NOT EXISTS gates (
        gate_ref TEXT PRIMARY KEY,
        run_id TEXT NOT NULL DEFAULT '',
        project_id TEXT NOT NULL DEFAULT '',
        stage_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        payload JSON NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        resolved_at REAL NOT NULL DEFAULT 0,
        tenant_id TEXT NOT NULL,
        user_id TEXT NOT NULL DEFAULT '',
        session_id TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS gate_schema_version (version INTEGER PRIMARY KEY);
    """

    _MIGRATE_SPINE: ClassVar[list[str]] = [
        "ALTER TABLE gates ADD COLUMN resolved_at REAL NOT NULL DEFAULT 0",
        "ALTER TABLE gates ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE gates ADD COLUMN user_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE gates ADD COLUMN session_id TEXT NOT NULL DEFAULT ''",
    ]

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(self._path), check_same_thread=False)
        # Track D C-1: WAL + busy_timeout via shared helper.
        from hi_agent._sqlite_init import configure_sqlite_connection
        configure_sqlite_connection(self._con)
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.executescript(self._DDL)
        self._con.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add spine columns to gates table if missing."""
        cols = {row[1] for row in self._con.execute("PRAGMA table_info(gates)")}
        for stmt in self._MIGRATE_SPINE:
            col = stmt.split("ADD COLUMN ")[1].split(" ")[0]
            if col not in cols:
                self._con.execute(stmt)
        self._con.commit()

    def _record_to_payload(self, record: GateRecord) -> str:
        ctx = record.context
        ctx_dict = {
            "gate_ref": ctx.gate_ref,
            "run_id": ctx.run_id,
            "stage_id": ctx.stage_id,
            "branch_id": ctx.branch_id,
            "submitter": ctx.submitter,
            "decision_ref": ctx.decision_ref,
            "rationale": ctx.rationale,
            "opened_at": ctx.opened_at,
            "metadata": ctx.metadata,
            "tenant_id": ctx.tenant_id,
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "project_id": ctx.project_id,
        }
        payload = {
            "context": ctx_dict,
            "status": record.status.value,
            "timeout_seconds": record.timeout_seconds,
            "timeout_policy": record.timeout_policy.value,
            "resolution_by": record.resolution_by,
            "resolution_comment": record.resolution_comment,
            "resolution_reason": record.resolution_reason,
            "resolved_at": record.resolved_at,
            "escalation_target": record.escalation_target,
        }
        return json.dumps(payload)

    def _row_to_record(self, row: tuple) -> GateRecord:
        payload = json.loads(row[5])
        ctx_data = payload["context"]
        col_project_id = row[2]
        col_tenant_id = row[6]
        col_user_id = row[7]
        col_session_id = row[8]
        ctx = GateContext(
            gate_ref=ctx_data["gate_ref"],
            run_id=ctx_data["run_id"],
            stage_id=ctx_data["stage_id"],
            branch_id=ctx_data["branch_id"],
            submitter=ctx_data["submitter"],
            decision_ref=ctx_data.get("decision_ref"),
            rationale=ctx_data.get("rationale"),
            opened_at=float(ctx_data.get("opened_at", 0.0)),
            metadata=dict(ctx_data.get("metadata") or {}),
            tenant_id=col_tenant_id or ctx_data.get("tenant_id", ""),
            user_id=col_user_id or ctx_data.get("user_id", ""),
            session_id=col_session_id or ctx_data.get("session_id", ""),
            project_id=col_project_id or ctx_data.get("project_id", ""),
        )
        return GateRecord(
            context=ctx,
            status=GateStatus(payload["status"]),
            timeout_seconds=float(payload.get("timeout_seconds", 300.0)),
            timeout_policy=GateTimeoutPolicy(payload.get("timeout_policy", "reject")),
            resolution_by=payload.get("resolution_by"),
            resolution_comment=payload.get("resolution_comment"),
            resolution_reason=payload.get("resolution_reason"),
            resolved_at=payload.get("resolved_at"),
            escalation_target=payload.get("escalation_target"),
        )

    def create_gate(
        self,
        *,
        context: GateContext,
        timeout_seconds: float = 300.0,
        timeout_policy: GateTimeoutPolicy = GateTimeoutPolicy.REJECT,
        escalation_target: str | None = None,
        tenant_id: str = "",
        user_id: str = "",
        session_id: str = "",
        project_id: str = "",
        exec_ctx: RunExecutionContext | None = None,  # prefer over explicit kwargs when available
    ) -> GateRecord:
        """Create and persist a new pending gate."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        # When exec_ctx is provided, use it as the authoritative spine source
        if exec_ctx is not None:
            _spine = exec_ctx.to_spine_kwargs()
            tenant_id = _spine.get("tenant_id", tenant_id) or tenant_id
            user_id = _spine.get("user_id", user_id) or user_id
            session_id = _spine.get("session_id", session_id) or session_id
            project_id = _spine.get("project_id", project_id) or project_id
        from dataclasses import replace as _replace
        ctx = _replace(
            context,
            tenant_id=context.tenant_id or tenant_id,
            user_id=context.user_id or user_id,
            session_id=context.session_id or session_id,
            project_id=context.project_id or project_id,
        )
        record = GateRecord(
            context=ctx,
            status=GateStatus.PENDING,
            timeout_seconds=timeout_seconds,
            timeout_policy=timeout_policy,
            escalation_target=escalation_target.strip() if escalation_target else None,
        )
        now = time()
        with self._lock:
            self._con.execute(
                "INSERT INTO gates "
                "(gate_ref, run_id, project_id, stage_id, status, payload, created_at, updated_at, "
                " tenant_id, user_id, session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ctx.gate_ref,
                    ctx.run_id,
                    ctx.project_id,
                    ctx.stage_id,
                    record.status.value,
                    self._record_to_payload(record),
                    now,
                    now,
                    ctx.tenant_id,
                    ctx.user_id,
                    ctx.session_id,
                ),
            )
            self._con.commit()
        return record

    def get_gate(
        self, gate_ref: str, tenant_id: str | None = None, *, internal_unscoped: bool = False
    ) -> GateRecord:
        """Fetch a gate by reference. Raises ValueError if not found.

        When ``tenant_id`` is provided, a row whose ``tenant_id`` does not
        match raises ``ValueError(f"gate {gate_ref} not found")`` — same shape
        as a missing row, preserving object-level 404 semantics.  When
        ``tenant_id is None`` the lookup is unscoped (legacy / process-internal
        callers); under strict posture this raises ValueError unless
        ``internal_unscoped=True``.
        """
        normalized = gate_ref.strip()
        if not normalized:
            raise ValueError("gate_ref must be a non-empty string")
        if tenant_id is None:
            _warn_unscoped_gate_read("get_gate", normalized, internal_unscoped=internal_unscoped)
        row = self._con.execute(
            "SELECT gate_ref, run_id, project_id, stage_id, status, payload, "
            "tenant_id, user_id, session_id "
            "FROM gates WHERE gate_ref = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            raise ValueError(f"gate {normalized} not found")
        if tenant_id is not None and (row[6] or "") != tenant_id:
            raise ValueError(f"gate {normalized} not found")
        return self._row_to_record(row)

    def list_pending(
        self, tenant_id: str | None = None, *, internal_unscoped: bool = False
    ) -> list[GateRecord]:
        """Return all gates currently in PENDING status.

        When ``tenant_id`` is provided, only gates owned by that tenant are
        returned.  When ``tenant_id is None`` the listing is unscoped (legacy
        / process-internal callers); under strict posture this raises ValueError
        unless ``internal_unscoped=True``.
        """
        if tenant_id is None:
            _warn_unscoped_gate_read("list_pending", None, internal_unscoped=internal_unscoped)
            rows = self._con.execute(
                "SELECT gate_ref, run_id, project_id, stage_id, status, payload, "
                "tenant_id, user_id, session_id "
                "FROM gates WHERE status = ?",
                (GateStatus.PENDING.value,),
            ).fetchall()
        else:
            rows = self._con.execute(
                "SELECT gate_ref, run_id, project_id, stage_id, status, payload, "
                "tenant_id, user_id, session_id "
                "FROM gates WHERE status = ? AND tenant_id = ?",
                (GateStatus.PENDING.value, tenant_id),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def resolve(
        self,
        *,
        gate_ref: str,
        action: str,
        approver: str,
        comment: str | None = None,
        reason: str | None = None,
    ) -> GateRecord:
        """Resolve a pending gate. Delegates validation to InMemoryGateAPI, then persists."""
        record = self.get_gate(gate_ref, internal_unscoped=True)
        # Use InMemoryGateAPI only for action validation and status transition logic.
        _mem = InMemoryGateAPI(enforce_separation_of_concerns=False)
        _mem._records[gate_ref] = record
        resolved = _mem.resolve(
            gate_ref=gate_ref,
            action=action,
            approver=approver,
            comment=comment,
            reason=reason,
        )
        with self._lock:
            self._con.execute(
                "UPDATE gates SET status = ?, payload = ?, updated_at = ? WHERE gate_ref = ?",
                (resolved.status.value, self._record_to_payload(resolved), time(), gate_ref),
            )
            self._con.commit()
        return resolved

    def apply_timeouts(self) -> list[GateRecord]:
        """Apply timeout policy to pending gates. Returns changed records."""
        # Delegate to InMemoryGateAPI logic over current pending set.
        pending = self.list_pending(internal_unscoped=True)
        if not pending:
            return []
        _mem = InMemoryGateAPI(enforce_separation_of_concerns=False)
        for record in pending:
            _mem._records[record.context.gate_ref] = record
        changed = _mem.apply_timeouts()
        for record in changed:
            with self._lock:
                self._con.execute(
                    "UPDATE gates SET status = ?, payload = ?, updated_at = ? WHERE gate_ref = ?",
                    (
                        record.status.value,
                        self._record_to_payload(record),
                        time(),
                        record.context.gate_ref,
                    ),
                )
                self._con.commit()
        return changed

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._con.close()
