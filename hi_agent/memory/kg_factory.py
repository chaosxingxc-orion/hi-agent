"""Factory for knowledge graph backends.

Rule 6 — Single Construction Path: all KG backend construction goes through
``make_knowledge_graph_backend``. Inline fallbacks are forbidden.

Rule 11 — Posture-Aware Defaults:
  - dev posture  → JsonGraphBackend (fast, file-based, profile-scoped)
  - research/prod → SqliteKnowledgeGraphBackend (durable, tenant-scoped)

Override: set ``HI_AGENT_KG_BACKEND={json,sqlite}`` to force a specific
backend regardless of posture (one-wave migration window).
Precedence: env var > posture default.
"""

from __future__ import annotations

import os
from pathlib import Path

from hi_agent.config.posture import Posture
from hi_agent.memory.long_term import JsonGraphBackend
from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend


def make_knowledge_graph_backend(
    posture: Posture,
    data_dir: Path,
    profile_id: str,
    project_id: str = "",
    tenant_id: str = "",
) -> JsonGraphBackend | SqliteKnowledgeGraphBackend:
    """Build and return a KG backend appropriate for the given posture.

    Args:
        posture: Execution posture (dev / research / prod).
        data_dir: Root data directory; SQLite file is placed under
            ``data_dir/L3/{profile_id}/knowledge_graph.sqlite``.
        profile_id: Required scope identifier (Rule 6 / Rule 12).
        project_id: Optional project scope; empty string means no project.
        tenant_id: Optional tenant identifier stored on every record (Rule 12).

    Returns:
        A :class:`~hi_agent.memory.long_term.JsonGraphBackend` (dev default) or
        a :class:`~hi_agent.memory.sqlite_kg_backend.SqliteKnowledgeGraphBackend`
        (research/prod default or explicit override).
    """
    if not profile_id:
        raise ValueError(
            "make_knowledge_graph_backend requires profile_id; "
            "empty profile_id creates an unscoped store (Rule 6 / Rule 12)."
        )

    override = os.environ.get("HI_AGENT_KG_BACKEND", "").lower().strip()

    use_sqlite: bool
    if override == "json":
        use_sqlite = False
    elif override == "sqlite":
        use_sqlite = True
    else:
        # No override: follow posture default.
        use_sqlite = posture.is_strict

    if not use_sqlite:
        # dev default: JSON backend (fast, file-based).
        json_dir = data_dir / "L3" / profile_id
        if project_id:
            json_dir = json_dir / project_id
        json_path = str(json_dir / "graph.json")
        return JsonGraphBackend(
            storage_path=json_path,
            profile_id=profile_id,
            project_id=project_id,
        )
    else:
        # research/prod default: durable SQLite backend.
        sqlite_dir = data_dir / "L3" / profile_id
        if project_id:
            sqlite_dir = sqlite_dir / project_id
        return SqliteKnowledgeGraphBackend(
            data_dir=sqlite_dir,
            profile_id=profile_id,
            project_id=project_id,
            tenant_id=tenant_id,
        )
