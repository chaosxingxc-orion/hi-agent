"""SSRF prevention policy (P0-1d).

Provides URLPolicy to validate URLs against private/reserved network ranges.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network


class URLPolicyViolation(Exception):  # noqa: N818 - public API keeps the established name.
    """Raised when a URL fails security policy."""


# Private/reserved networks to block
_BLOCKED_NETWORKS_V4 = [
    IPv4Network("127.0.0.0/8"),  # loopback
    IPv4Network("10.0.0.0/8"),  # private
    IPv4Network("172.16.0.0/12"),  # private
    IPv4Network("192.168.0.0/16"),  # private
    IPv4Network("169.254.0.0/16"),  # link-local + metadata (169.254.169.254)
    IPv4Network("0.0.0.0/8"),  # "this" network
    IPv4Network("100.64.0.0/10"),  # shared address space (RFC 6598)
]
_BLOCKED_NETWORKS_V6 = [
    IPv6Network("::1/128"),  # loopback
    IPv6Network("fc00::/7"),  # unique local
    IPv6Network("fe80::/10"),  # link-local
]


class URLPolicy:
    def __init__(self, *, allow_private: bool = False) -> None:
        """allow_private=True disables private network blocking (for dev/trusted-backend use)."""
        self._allow_private = allow_private

    def validate(self, url: str) -> None:
        """Validate url against SSRF policy.

        Raises URLPolicyViolation if the URL is disallowed.

        Checks:
        1. URL must be parseable.
        2. Scheme must be http or https.
        3. Hostname must resolve to an IP.
        4. Resolved IP must not be in blocked networks.
        """
        parsed = urllib.parse.urlparse(url)

        # Rule 1: Only http/https
        if parsed.scheme not in ("http", "https"):
            raise URLPolicyViolation(f"Scheme {parsed.scheme!r} is not allowed (only http/https)")

        hostname = parsed.hostname
        if not hostname:
            raise URLPolicyViolation("URL has no hostname")

        if self._allow_private:
            return

        # Rule 2: Resolve and check IP
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise URLPolicyViolation(f"Cannot resolve hostname {hostname!r}: {exc}") from exc

        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            self._check_ip(ip_str, hostname)

    def _check_ip(self, ip_str: str, hostname: str) -> None:
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:  # rule7-exempt: expiry_wave="Wave 26" replacement_test: wave22-tests
            return

        # Unwrap IPv4-mapped IPv6 addresses (::ffff:x.x.x.x)
        if isinstance(addr, IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped  # becomes an IPv4Address

        if isinstance(addr, IPv4Address):
            for net in _BLOCKED_NETWORKS_V4:
                if addr in net:
                    raise URLPolicyViolation(
                        f"URL resolves to blocked IP {ip_str} ({hostname}) in network {net}"
                    )
        elif isinstance(addr, IPv6Address):
            for net in _BLOCKED_NETWORKS_V6:
                if addr in net:
                    raise URLPolicyViolation(
                        f"URL resolves to blocked IPv6 {ip_str} ({hostname}) in network {net}"
                    )
