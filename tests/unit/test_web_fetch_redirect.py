"""Unit tests for web_fetch redirect SSRF protection (H-5)."""

from __future__ import annotations

import urllib.error
import urllib.response
from unittest.mock import MagicMock, patch

from hi_agent.capability.tools.builtin import web_fetch_handler


class _FakeResponse:
    """Minimal urllib response stub."""

    def __init__(
        self, content: bytes = b"hello", status: int = 200, url: str = "http://example.com"
    ) -> None:
        self._content = content
        self.status = status
        self.url = url

    def read(self) -> bytes:
        return self._content

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_normal_fetch_succeeds() -> None:
    """A normal allowed URL fetch must succeed when opener returns a valid response."""
    fake_resp = _FakeResponse(b"page content", 200, "http://example.com")
    with (
        patch("hi_agent.capability.tools.builtin.URLPolicy") as mock_policy_cls,
        patch("urllib.request.OpenerDirector.open", return_value=fake_resp),
    ):
        mock_policy_cls.return_value.validate.return_value = None
        result = web_fetch_handler({"url": "http://example.com"})
    assert result["success"] is True
    assert result["content"] == "page content"


def test_url_policy_violation_blocks_fetch() -> None:
    """URL policy violation must block the fetch before any network call."""
    from hi_agent.security.url_policy import URLPolicyViolation

    with patch("hi_agent.capability.tools.builtin.URLPolicy") as mock_policy_cls:
        mock_policy_cls.return_value.validate.side_effect = URLPolicyViolation("blocked")
        result = web_fetch_handler({"url": "http://169.254.169.254"})
    assert result["success"] is False
    assert "URL policy violation" in result["error"]


def test_redirect_to_blocked_url_raises_url_error() -> None:
    """A redirect to a policy-blocked URL must be intercepted and blocked."""
    from hi_agent.security.url_policy import URLPolicyViolation

    call_count = 0

    def _validate_side_effect(url: str) -> None:
        nonlocal call_count
        call_count += 1
        # First call (original URL) passes; redirect URL is blocked
        if "169.254" in url or "metadata" in url:
            raise URLPolicyViolation(f"blocked: {url}")

    with patch("hi_agent.capability.tools.builtin.URLPolicy") as mock_policy_cls:
        mock_policy = MagicMock()
        mock_policy.validate.side_effect = _validate_side_effect
        mock_policy_cls.return_value = mock_policy

        # Simulate opener raising URLError as if redirect was blocked
        with patch("urllib.request.OpenerDirector.open") as mock_open:
            mock_open.side_effect = urllib.error.URLError("Redirect blocked by URL policy")
            result = web_fetch_handler({"url": "http://example.com"})

    assert result["success"] is False
    assert result["error"] is not None


def test_empty_url_returns_error() -> None:
    """Empty URL must return an error without making any network call."""
    result = web_fetch_handler({"url": ""})
    assert result["success"] is False
    assert result["error"] == "url is required"
