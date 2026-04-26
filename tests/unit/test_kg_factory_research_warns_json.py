"""Unit: KG factory emits warning under research posture with JSON override (W6-E).

Layer 1 — Unit; file system faked via tmp_path.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from hi_agent.config.posture import Posture
from hi_agent.memory.kg_factory import make_knowledge_graph_backend


def test_research_warns_json_backend(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Under research posture with HI_AGENT_KG_BACKEND=json, WARNING must be logged."""
    with caplog.at_level(logging.WARNING, logger="hi_agent.memory.kg_factory"), patch.dict(
        os.environ, {"HI_AGENT_KG_BACKEND": "json"}, clear=False
    ):
        backend = make_knowledge_graph_backend(
            posture=Posture.RESEARCH,
            data_dir=tmp_path,
            profile_id="prof-research-warn",
        )

    from hi_agent.memory.long_term import JsonGraphBackend

    assert isinstance(backend, JsonGraphBackend), "research+json should return JsonGraphBackend"

    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("json" in m.lower() for m in warning_msgs), (
        f"Expected a WARNING mentioning 'json'; got: {warning_msgs}"
    )


def test_research_json_backend_still_returns_json(tmp_path: Path) -> None:
    """Research posture + json override must return JsonGraphBackend (not raise)."""
    from hi_agent.memory.long_term import JsonGraphBackend

    with patch.dict(os.environ, {"HI_AGENT_KG_BACKEND": "json"}, clear=False):
        backend = make_knowledge_graph_backend(
            posture=Posture.RESEARCH,
            data_dir=tmp_path,
            profile_id="prof-research-json",
        )
    assert isinstance(backend, JsonGraphBackend)


def test_dev_json_backend_no_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Dev posture + json override must NOT emit a warning (only research/prod)."""
    with caplog.at_level(logging.WARNING, logger="hi_agent.memory.kg_factory"), patch.dict(
        os.environ, {"HI_AGENT_KG_BACKEND": "json"}, clear=False
    ):
        make_knowledge_graph_backend(
            posture=Posture.DEV,
            data_dir=tmp_path,
            profile_id="prof-dev-json",
        )

    kg_warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "kg_factory" in r.name
    ]
    assert kg_warnings == [], f"Dev posture should not warn; got: {kg_warnings}"
