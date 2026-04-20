"""Background poller that reconciles long-running op status (G-8)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

from hi_agent.experiment.coordinator import LongRunningOpCoordinator
from hi_agent.experiment.op_store import LongRunningOpStore, OpStatus

_logger = logging.getLogger(__name__)


class OpPoller:
    def __init__(
        self,
        coordinator: LongRunningOpCoordinator,
        store: LongRunningOpStore,
        poll_interval: float = 30.0,
        on_event: Callable[[dict], None] | None = None,
    ):
        self._coord = coordinator
        self._store = store
        self._interval = poll_interval
        self._on_event = on_event or (lambda e: None)
        self._running = False

    async def poll_once(self) -> None:
        for handle in self._store.list_active():
            backend = self._coord._backends.get(handle.backend)
            if backend is None:
                _logger.warning(
                    "No backend registered for op_id=%s backend=%s", handle.op_id, handle.backend
                )
                continue
            try:
                status_str: str = backend.status(handle.external_id)
                if status_str == "running":
                    self._store.update_status(
                        handle.op_id, OpStatus.RUNNING, heartbeat_at=time.time()
                    )
                    self._on_event({"type": "experiment.heartbeat", "op_id": handle.op_id})
                elif status_str == "succeeded":
                    artifacts: list[str] = backend.fetch_artifacts(handle.external_id)
                    self._store.update_status(
                        handle.op_id,
                        OpStatus.SUCCEEDED,
                        completed_at=time.time(),
                        artifacts_uri=",".join(artifacts),
                    )
                    self._on_event(
                        {
                            "type": "experiment.result_posted",
                            "op_id": handle.op_id,
                            "artifacts": artifacts,
                        }
                    )
                    # G-10: hash each artifact and emit provenance events
                    from hi_agent.experiment.provenance import ArtifactRecord

                    for uri in artifacts:
                        try:
                            p = Path(uri)
                            if p.exists() and p.is_file():
                                record = ArtifactRecord.from_path(p)
                                self._on_event(
                                    {
                                        "type": "experiment.artifact_indexed",
                                        "op_id": handle.op_id,
                                        "uri": record.uri,
                                        "sha256": record.sha256,
                                        "size": record.size,
                                        "mime": record.mime,
                                    }
                                )
                        except Exception as exc:
                            _logger.warning(
                                "Artifact hashing failed for op_id=%s uri=%s: %s",
                                handle.op_id,
                                uri,
                                exc,
                            )
                elif status_str == "failed":
                    self._store.update_status(
                        handle.op_id, OpStatus.FAILED, completed_at=time.time()
                    )
                    self._on_event({"type": "experiment.failed", "op_id": handle.op_id})
                elif status_str == "cancelled":
                    self._store.update_status(
                        handle.op_id, OpStatus.CANCELLED, completed_at=time.time()
                    )
            except Exception as exc:
                _logger.warning("Poller error for op_id=%s: %s", handle.op_id, exc)

    async def run(self) -> None:
        self._running = True
        while self._running:
            await self.poll_once()
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        self._running = False
