"""RunService — thin accessor layer for route modules.

Routes extracted from app.py use this class to access shared server state
(RunManager, FeedbackStore, etc.) without importing AgentServer directly,
which would create a circular dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hi_agent.server.run_manager import RunManager
    from hi_agent.server.event_store import SQLiteEventStore


class RunService:
    """Provides route handlers access to shared server-level state.

    Passed by dependency injection to route modules so they do not need to
    import AgentServer (which would create a circular import) or access
    ``request.app.state.agent_server`` themselves.

    All attributes are read-only references; mutation goes through the
    underlying manager/store objects.
    """

    def __init__(self, agent_server: Any) -> None:
        self._server = agent_server

    # ------------------------------------------------------------------
    # Core managers
    # ------------------------------------------------------------------

    @property
    def run_manager(self) -> "RunManager":
        return self._server.run_manager  # type: ignore[return-value]

    @property
    def run_context_manager(self) -> Any:
        return getattr(self._server, "run_context_manager", None)

    @property
    def executor_factory(self) -> Any:
        return self._server.executor_factory

    @property
    def builder(self) -> Any:
        return getattr(self._server, "_builder", None)

    @property
    def artifact_registry(self) -> Any:
        return getattr(self._server, "artifact_registry", None)
