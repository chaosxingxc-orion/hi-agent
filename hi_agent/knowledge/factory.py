"""Posture-aware factory for KnowledgeGraphBackend instances.

Rule 6 — Single Construction Path Per Resource Class:
    All consumers receive the backend via this factory function.
    Inline fallbacks of the shape ``x or DefaultX()`` are forbidden.

Rule 11 — Posture-Aware Defaults:
    - dev  -> JsonGraphBackend (LongTermMemoryGraph, in-memory JSON)
    - research / prod -> SqliteKnowledgeGraphBackend (durable, file-backed)

Override via environment variable ``HI_AGENT_KG_BACKEND={json,sqlite}``.

Note: The research/prod → Sqlite flip is available but NOT yet the default
for live server wiring; the factory is correct and tested but calling code
is not yet wired to use it.
"""

from __future__ import annotations

import os
from typing import Any

from hi_agent.config.posture import Posture


def make_knowledge_graph_backend(
    posture: Posture | None = None,
    data_dir: str = "",
) -> Any:
    """Return a posture-appropriate KnowledgeGraphBackend instance.

    Args:
        posture: Execution posture.  When ``None``, resolved from
            ``HI_AGENT_POSTURE`` env var via :meth:`Posture.from_env`.
        data_dir: Directory for the SQLite file when the sqlite backend is
            selected.  Defaults to the current directory when empty.

    Returns:
        A backend satisfying the ``KnowledgeGraphBackend`` Protocol:
        - ``json``   override  → :class:`~hi_agent.memory.long_term.JsonGraphBackend`
        - ``sqlite`` override  → :class:`SqliteKnowledgeGraphBackend`
        - no override, dev     → :class:`~hi_agent.memory.long_term.JsonGraphBackend`
        - no override, strict  → :class:`SqliteKnowledgeGraphBackend`
    """
    if posture is None:
        posture = Posture.from_env()

    override = os.environ.get("HI_AGENT_KG_BACKEND", "").strip().lower()

    use_sqlite = override == "sqlite" or (not override and posture.is_strict)

    if use_sqlite:
        from hi_agent.knowledge.sqlite_backend import SqliteKnowledgeGraphBackend

        db_path = os.path.join(data_dir or ".", "knowledge_graph.db")
        return SqliteKnowledgeGraphBackend(db_path=db_path)

    # Default: JsonGraphBackend (LongTermMemoryGraph alias).
    from hi_agent.memory.long_term import JsonGraphBackend

    return JsonGraphBackend()
