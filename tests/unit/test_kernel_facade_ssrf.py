"""Unit tests for KernelFacadeClient SSRF protection (H-4)."""
from __future__ import annotations

import pytest
from hi_agent.runtime_adapter.kernel_facade_client import KernelFacadeClient


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254",
        "http://10.0.0.1:9090",
        "http://192.168.1.1:9090",
        "file:///etc/passwd",
        "http://evil.example.com:9090",
        "http://metadata.google.internal",
    ],
)
def test_non_loopback_rejected(bad_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-loopback base_url must raise ValueError without override env var."""
    monkeypatch.delenv("HI_AGENT_KERNEL_BASE_URL_OVERRIDE_UNSAFE", raising=False)
    with pytest.raises(ValueError, match="not an allowed loopback"):
        KernelFacadeClient(mode="http", base_url=bad_url)


@pytest.mark.parametrize(
    "good_url",
    [
        "http://localhost:9090",
        "http://127.0.0.1:9090",
        "http://localhost",
        "http://127.0.0.1",
    ],
)
def test_loopback_accepted(good_url: str) -> None:
    """Loopback base_url must be accepted without any override."""
    client = KernelFacadeClient(mode="http", base_url=good_url)
    assert client._base_url == good_url.rstrip("/")


def test_override_env_var_allows_non_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """HI_AGENT_KERNEL_BASE_URL_OVERRIDE_UNSAFE must allow non-loopback when set."""
    monkeypatch.setenv("HI_AGENT_KERNEL_BASE_URL_OVERRIDE_UNSAFE", "1")
    client = KernelFacadeClient(mode="http", base_url="http://10.0.0.1:9090")
    assert client._base_url == "http://10.0.0.1:9090"
