"""SSHBackend: remote SSH-based operation execution stub (G-9).

Full implementation requires paramiko or fabric. This stub satisfies the
ExperimentBackend protocol interface and raises NotImplementedError when called.
Wire up paramiko in a follow-on sprint when remote operation execution is needed.
"""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


class SSHBackend:
    """SSH-based operation backend stub.

    Replace the body of submit/status/fetch_artifacts/cancel with paramiko
    calls when remote execution is needed. All methods raise NotImplementedError
    until implemented.
    """

    def __init__(
        self,
        host: str,
        user: str,
        work_dir: str,
        port: int = 22,
        key_path: str = "",
        password: str = "",
    ):
        self._host = host
        self._user = user
        self._work_dir = work_dir
        self._port = port
        self._key_path = key_path
        self._password = password
        _logger.info("SSHBackend initialized (stub) host=%s user=%s", host, user)

    def submit(self, op_spec: dict) -> str:
        raise NotImplementedError(
            "SSHBackend.submit is not yet implemented. "
            "Install paramiko and implement SSH job submission."
        )

    def status(self, external_id: str) -> str:
        raise NotImplementedError("SSHBackend.status is not yet implemented.")

    def fetch_artifacts(self, external_id: str) -> list[str]:
        raise NotImplementedError("SSHBackend.fetch_artifacts is not yet implemented.")

    def cancel(self, external_id: str) -> None:
        raise NotImplementedError("SSHBackend.cancel is not yet implemented.")
