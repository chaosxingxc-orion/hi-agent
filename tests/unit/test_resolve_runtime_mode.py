"""W33 Track E.1: ``hi_agent.config.posture.resolve_runtime_mode``.

Single source of truth for the canonical runtime mode (dev | research |
prod). Honors HI_AGENT_POSTURE first; falls back to HI_AGENT_ENV. When both
are unset the default is ``"prod"`` (fail-closed) per Rule 11. Invalid
values fall through to the next layer.
"""

from __future__ import annotations

import pytest
from hi_agent.config.posture import resolve_runtime_mode


@pytest.fixture
def clean_env(monkeypatch) -> None:
    """Clear both HI_AGENT_POSTURE and HI_AGENT_ENV per test."""
    monkeypatch.delenv("HI_AGENT_POSTURE", raising=False)
    monkeypatch.delenv("HI_AGENT_ENV", raising=False)


@pytest.mark.usefixtures("clean_env")
def test_unset_defaults_to_prod(monkeypatch) -> None:
    """Both vars unset → 'prod' (Rule 11 fail-closed default)."""
    assert resolve_runtime_mode() == "prod"


@pytest.mark.usefixtures("clean_env")
@pytest.mark.parametrize("value", ["dev", "research", "prod"])
def test_hi_agent_posture_wins(monkeypatch, value: str) -> None:
    """HI_AGENT_POSTURE returns its value verbatim."""
    monkeypatch.setenv("HI_AGENT_POSTURE", value)
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    assert resolve_runtime_mode() == value


@pytest.mark.usefixtures("clean_env")
@pytest.mark.parametrize("value", ["dev", "research", "prod"])
def test_hi_agent_env_fallback(monkeypatch, value: str) -> None:
    """HI_AGENT_ENV is honored when HI_AGENT_POSTURE is unset."""
    monkeypatch.setenv("HI_AGENT_ENV", value)
    assert resolve_runtime_mode() == value


@pytest.mark.usefixtures("clean_env")
def test_invalid_posture_falls_through_to_env(monkeypatch) -> None:
    """An invalid HI_AGENT_POSTURE drops through to HI_AGENT_ENV."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "rubbish")
    monkeypatch.setenv("HI_AGENT_ENV", "research")
    assert resolve_runtime_mode() == "research"


@pytest.mark.usefixtures("clean_env")
def test_invalid_both_defaults_to_prod(monkeypatch) -> None:
    """Both invalid → 'prod' (fail-closed)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "rubbish")
    monkeypatch.setenv("HI_AGENT_ENV", "alsobad")
    assert resolve_runtime_mode() == "prod"


@pytest.mark.usefixtures("clean_env")
def test_case_insensitive(monkeypatch) -> None:
    """Mixed-case values are normalised."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "DEV")
    assert resolve_runtime_mode() == "dev"


@pytest.mark.usefixtures("clean_env")
def test_whitespace_stripped(monkeypatch) -> None:
    """Surrounding whitespace is stripped before lookup."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "  research  ")
    assert resolve_runtime_mode() == "research"


@pytest.mark.usefixtures("clean_env")
def test_empty_posture_falls_through(monkeypatch) -> None:
    """Empty HI_AGENT_POSTURE → HI_AGENT_ENV is consulted."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "")
    monkeypatch.setenv("HI_AGENT_ENV", "dev")
    assert resolve_runtime_mode() == "dev"
