"""Long-running operation coordinator (G-8)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from hi_agent.operations.op_store import LongRunningOpStore, OpHandle, OpStatus

_logger = logging.getLogger(__name__)


class LongRunningOpCoordinator:
    def __init__(self, store: LongRunningOpStore):
        self._store = store
        self._backends: dict[str, Any] = {}

    def register_backend(self, name: str, backend: Any) -> None:
        self._backends[name] = backend

    def submit(
        self,
        *,
        op_spec: dict,
        backend_name: str,
        tenant_id: str = "",
        user_id: str = "",
        session_id: str = "",
        project_id: str = "",
    ) -> OpHandle:
        from hi_agent.config.posture_guards import require_tenant

        tenant_id = require_tenant(tenant_id or None, where="LongRunningOpCoordinator.submit")
        backend = self._backends[backend_name]
        external_id = backend.submit(op_spec)
        op_id = str(uuid.uuid4())
        handle = self._store.create(
            op_id=op_id,
            backend=backend_name,
            external_id=external_id,
            submitted_at=time.time(),
            tenant_id=tenant_id,
            project_id=project_id,
        )
        _logger.info(
            "LongRunningOp submitted op_id=%s backend=%s ext=%s",
            op_id,
            backend_name,
            external_id,
        )
        return handle

    def get(self, op_id: str) -> OpHandle | None:
        return self._store.get(op_id)

    def cancel(self, op_id: str) -> bool:
        handle = self._store.get(op_id)
        if handle is None:
            return False
        backend = self._backends.get(handle.backend)
        if backend is not None:
            try:
                backend.cancel(handle.external_id)
            except Exception as exc:
                _logger.warning("Backend cancel failed for op_id=%s: %s", op_id, exc)
        self._store.update_status(op_id, OpStatus.CANCELLED, completed_at=time.time())
        return True
