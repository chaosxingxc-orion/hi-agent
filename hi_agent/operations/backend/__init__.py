"""Operation execution backend protocol (G-9)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExperimentBackend(Protocol):
    """Protocol for operation execution backends.

    Implementations: LocalBackend (subprocess).
    Future: SSHBackend (paramiko), SlurmBackend, KubernetesBackend.
    """

    def submit(self, op_spec: dict) -> str:
        """Submit an operation; return external_id immediately."""
        ...

    def status(self, external_id: str) -> str:
        """Return current status: pending | running | succeeded | failed | cancelled | unknown."""
        ...

    def fetch_artifacts(self, external_id: str) -> list[str]:
        """Return list of artifact URIs (file paths or s3:// etc.) for a completed op."""
        ...

    def cancel(self, external_id: str) -> None:
        """Cancel a running or pending operation."""
        ...
