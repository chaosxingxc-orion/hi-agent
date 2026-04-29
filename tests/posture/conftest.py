"""Shared fixtures for posture-matrix tests (Rule 11 coverage)."""
from __future__ import annotations

import pytest

POSTURES = ["dev", "research", "prod"]


@pytest.fixture(params=POSTURES)
def posture_env(request, monkeypatch):
    """Parametrize tests across all three postures."""
    monkeypatch.setenv("HI_AGENT_POSTURE", request.param)
    return request.param


@pytest.fixture
def dev_posture(monkeypatch):
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    return "dev"


@pytest.fixture
def prod_posture(monkeypatch):
    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    return "prod"


@pytest.fixture
def research_posture(monkeypatch):
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    return "research"
