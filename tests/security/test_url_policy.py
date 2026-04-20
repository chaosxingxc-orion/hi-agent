"""Unit tests for URLPolicy SSRF prevention (P0-1d)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from hi_agent.security.url_policy import URLPolicy, URLPolicyViolation


def test_loopback_blocked():
    """http://127.0.0.1/ must be blocked (loopback)."""
    policy = URLPolicy()
    with pytest.raises(URLPolicyViolation, match="blocked"):
        policy.validate("http://127.0.0.1/")


def test_metadata_ip_blocked():
    """http://169.254.169.254/ must be blocked (cloud metadata service)."""
    policy = URLPolicy()
    with pytest.raises(URLPolicyViolation, match="blocked"):
        policy.validate("http://169.254.169.254/latest/meta-data")


def test_private_10_blocked():
    """http://10.0.0.1/ must be blocked (RFC 1918 private)."""
    policy = URLPolicy()
    with pytest.raises(URLPolicyViolation, match="blocked"):
        policy.validate("http://10.0.0.1/")


def test_private_192_blocked():
    """http://192.168.1.1/ must be blocked (RFC 1918 private)."""
    policy = URLPolicy()
    with pytest.raises(URLPolicyViolation, match="blocked"):
        policy.validate("http://192.168.1.1/")


def test_file_scheme_blocked():
    """file:///etc/passwd must be rejected (non http/https scheme)."""
    policy = URLPolicy()
    with pytest.raises(URLPolicyViolation, match="Scheme"):
        policy.validate("file:///etc/passwd")


def test_ftp_scheme_blocked():
    """ftp://example.com/ must be rejected (non http/https scheme)."""
    policy = URLPolicy()
    with pytest.raises(URLPolicyViolation, match="Scheme"):
        policy.validate("ftp://example.com/")


def test_https_public_allowed():
    """https://example.com/ must be allowed when resolving to a public IP.

    Mocks socket.getaddrinfo to return a public IP to avoid real DNS resolution.
    """
    public_addr_info = [(2, 1, 6, "", ("93.184.216.34", 0))]
    policy = URLPolicy()
    with patch("hi_agent.security.url_policy.socket.getaddrinfo", return_value=public_addr_info):
        # Should not raise
        policy.validate("https://example.com/")


def test_allow_private_disables_blocking():
    """URLPolicy(allow_private=True) must not block private IPs."""
    policy = URLPolicy(allow_private=True)
    # Should not raise — allow_private skips network checks
    policy.validate("http://192.168.1.1/")
    policy.validate("http://10.0.0.1/")
    policy.validate("http://127.0.0.1/")


def test_no_hostname_blocked():
    """URL without a hostname must be rejected."""
    policy = URLPolicy()
    with pytest.raises(URLPolicyViolation, match="no hostname"):
        policy.validate("http:///path")


def test_ipv4_mapped_ipv6_loopback_blocked():
    """::ffff:127.0.0.1 (IPv4-mapped IPv6) must be blocked as loopback.

    Mocks getaddrinfo to return an IPv4-mapped IPv6 address that maps to
    127.0.0.1 — a bypass vector if _check_ip only checks the IPv6 block list.
    """
    # AF_INET6=10, sockaddr includes scope_id for IPv6
    ipv4_mapped_loopback = [(10, 1, 6, "", ("::ffff:127.0.0.1", 0, 0, 0))]
    policy = URLPolicy()
    with patch("hi_agent.security.url_policy.socket.getaddrinfo", return_value=ipv4_mapped_loopback):
        with pytest.raises(URLPolicyViolation, match="blocked"):
            policy.validate("http://evil.com/")
