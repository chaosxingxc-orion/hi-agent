"""Integration tests for the ProjectPostmortem lifecycle (W10-M.3).

Tests PostmortemEngine wiring into RunManager: a terminal run that carries a
project_id triggers PostmortemEngine.on_project_completed, and the resulting
ProjectRetrospective is retrievable via PostmortemEngine.get().
"""

from __future__ import annotations

import threading

from hi_agent.evolve.contracts import ProjectRetrospective
from hi_agent.evolve.postmortem import PostmortemEngine
from hi_agent.server.run_manager import RunManager


def _make_manager(engine: PostmortemEngine) -> RunManager:
    return RunManager(
        max_concurrent=2,
        queue_size=4,
        postmortem_engine=engine,
    )


def _run_sync(manager: RunManager, project_id: str) -> str:
    """Create, start, and wait for a single run with the given project_id."""
    run = manager.create_run({"task_id": "t1", "project_id": project_id})
    event = threading.Event()

    def executor(r):  # expiry_wave: Wave 28
        event.set()
        return None

    manager.start_run(run.run_id, executor)
    event.wait(timeout=5.0)
    # Wait for the thread to finish so the finally block runs.
    import time
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        r = manager.get_run(run.run_id)
        if r is not None and r.state in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.02)
    manager.shutdown(timeout=2.0)
    return run.run_id


def test_postmortem_created_on_project_completion() -> None:
    """A terminal run with a project_id must produce a stored retrospective."""
    engine = PostmortemEngine()
    manager = _make_manager(engine)
    project_id = "proj-lifecycle-1"

    _run_sync(manager, project_id)

    retro = engine.get(project_id)
    assert retro is not None, "PostmortemEngine should have stored a retrospective"


def test_postmortem_retrievable_after_creation() -> None:
    """A stored retrospective is retrievable by project_id after creation."""
    engine = PostmortemEngine()
    manager = _make_manager(engine)
    project_id = "proj-lifecycle-2"

    run_id = _run_sync(manager, project_id)

    retro = engine.get(project_id)
    assert retro is not None
    assert run_id in retro.run_ids, "retrospective must reference the completed run_id"


def test_postmortem_has_required_fields() -> None:
    """Stored retrospective must carry project_id and tenant_id (Rule 12)."""
    engine = PostmortemEngine()
    manager = _make_manager(engine)
    project_id = "proj-lifecycle-3"

    _run_sync(manager, project_id)

    retro = engine.get(project_id)
    assert retro is not None
    assert isinstance(retro, ProjectRetrospective)
    assert retro.project_id == project_id, "project_id must match"
    # tenant_id is "" under dev posture (no workspace); the field must exist.
    assert hasattr(retro, "tenant_id"), "ProjectRetrospective must carry tenant_id (Rule 12)"
    assert hasattr(retro, "run_ids"), "ProjectRetrospective must carry run_ids"
