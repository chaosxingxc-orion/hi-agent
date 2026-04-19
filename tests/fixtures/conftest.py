"""Pytest fixtures for fake external servers (W11-002)."""
from __future__ import annotations

import pytest

from tests.fixtures.fake_kernel_http_server import fake_kernel_server
from tests.fixtures.fake_llm_http_server import fake_llm_server


@pytest.fixture
def fake_llm_base_url():
    """Start a fake LLM HTTP server and yield its base URL."""
    with fake_llm_server() as url:
        yield url


@pytest.fixture
def fake_kernel_base_url():
    """Start a fake kernel HTTP server and yield its base URL."""
    with fake_kernel_server() as url:
        yield url
