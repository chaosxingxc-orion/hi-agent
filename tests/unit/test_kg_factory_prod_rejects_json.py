"""Unit: KG factory rejects JSON backend under prod posture (Rule 11 / W6-E).

Layer 1 — Unit; file system faked via tmp_path.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from hi_agent.config.posture import Posture
from hi_agent.memory.kg_factory import make_knowledge_graph_backend


def test_prod_rejects_json_backend(tmp_path: Path) -> None:
    """Under prod posture, HI_AGENT_KG_BACKEND=json must raise ValueError."""
    with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": "json"}, clear=False), pytest.raises(
        ValueError, match="prod posture"
    ):
        make_knowledge_graph_backend(
            posture=Posture.PROD,
            data_dir=tmp_path,
            profile_id="prof-prod-test",
        )


def test_prod_rejects_json_backend_message_content(tmp_path: Path) -> None:
    """Error message names the fix: remove override or use sqlite."""
    with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": "json"}, clear=False), pytest.raises(
        ValueError
    ) as exc_info:
        make_knowledge_graph_backend(
            posture=Posture.PROD,
            data_dir=tmp_path,
            profile_id="prof-prod-msg-test",
        )
    msg = str(exc_info.value).lower()
    assert "prod" in msg
    assert "json" in msg


def test_prod_accepts_sqlite_backend(tmp_path: Path) -> None:
    """Under prod posture, HI_AGENT_KG_BACKEND=sqlite is accepted."""
    from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

    with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": "sqlite"}, clear=False):
        backend = make_knowledge_graph_backend(
            posture=Posture.PROD,
            data_dir=tmp_path,
            profile_id="prof-prod-sqlite",
        )
    assert isinstance(backend, SqliteKnowledgeGraphBackend)


def test_prod_default_no_override_uses_sqlite(tmp_path: Path) -> None:
    """Under prod posture with no env override, SQLite is the default."""
    from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

    with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": ""}, clear=False):
        backend = make_knowledge_graph_backend(
            posture=Posture.PROD,
            data_dir=tmp_path,
            profile_id="prof-prod-default",
        )
    assert isinstance(backend, SqliteKnowledgeGraphBackend)
