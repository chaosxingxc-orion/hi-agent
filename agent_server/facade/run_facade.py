"""Run facade — translates contract types into kernel-side calls.

This module is the only place in agent_server/ allowed to touch
hi_agent runtime types (R-AS-1). Routes import only from here and from
agent_server.contracts. For W23 Phase 1 the facade accepts callables
injected at construction time so the kernel binding is wave-by-wave
incremental and easy to stub in tests.

LOC budget: <=200 (R-AS-8).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_server.contracts.errors import ContractError
from agent_server.contracts.run import RunRequest, RunResponse, RunStatus
from agent_server.contracts.tenancy import TenantContext

# Callable signatures injected at construction time. They MUST raise
# the contract errors defined in agent_server.contracts.errors when
# they need to surface tenant-visible failures.
StartRunFn = Callable[..., dict[str, Any]]
GetRunFn = Callable[..., dict[str, Any]]
SignalRunFn = Callable[..., dict[str, Any]]


class RunFacade:
    """Thin adapter from contract dataclasses to kernel callables."""

    def __init__(
        self,
        *,
        start_run: StartRunFn,
        get_run: GetRunFn,
        signal_run: SignalRunFn,
    ) -> None:
        self._start_run = start_run
        self._get_run = get_run
        self._signal_run = signal_run

    def start(self, ctx: TenantContext, req: RunRequest) -> RunResponse:
        if not req.idempotency_key:
            err = ContractError(
                "idempotency_key is required",
                tenant_id=ctx.tenant_id,
                detail="missing idempotency_key",
                http_status=400,
            )
            raise err
        if not req.profile_id:
            err = ContractError(
                "profile_id is required",
                tenant_id=ctx.tenant_id,
                detail="missing profile_id",
                http_status=400,
            )
            raise err
        record = self._start_run(
            tenant_id=ctx.tenant_id,
            profile_id=req.profile_id,
            goal=req.goal,
            project_id=req.project_id,
            run_id=req.run_id,
            idempotency_key=req.idempotency_key,
            metadata=dict(req.metadata),
        )
        return RunResponse(
            tenant_id=record["tenant_id"],
            run_id=record["run_id"],
            state=record["state"],
            current_stage=record.get("current_stage"),
            started_at=record.get("started_at"),
            finished_at=record.get("finished_at"),
            metadata=dict(record.get("metadata", {})),
        )

    def status(self, ctx: TenantContext, run_id: str) -> RunStatus:
        record = self._get_run(tenant_id=ctx.tenant_id, run_id=run_id)
        return RunStatus(
            tenant_id=record["tenant_id"],
            run_id=record["run_id"],
            state=record["state"],
            current_stage=record.get("current_stage"),
            llm_fallback_count=int(record.get("llm_fallback_count", 0)),
            finished_at=record.get("finished_at"),
        )

    def signal(
        self,
        ctx: TenantContext,
        run_id: str,
        signal: str,
        payload: dict[str, Any] | None = None,
    ) -> RunStatus:
        record = self._signal_run(
            tenant_id=ctx.tenant_id,
            run_id=run_id,
            signal=signal,
            payload=dict(payload or {}),
        )
        return RunStatus(
            tenant_id=record["tenant_id"],
            run_id=record["run_id"],
            state=record["state"],
            current_stage=record.get("current_stage"),
            llm_fallback_count=int(record.get("llm_fallback_count", 0)),
            finished_at=record.get("finished_at"),
        )
