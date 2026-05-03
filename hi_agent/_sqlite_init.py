"""Shared SQLite connection initialization helper.

Track D C-1 (Wave 32 audit BLOCKER): every SQLite store opened by hi-agent
must set ``PRAGMA busy_timeout`` so concurrent writers wait on locks instead
of immediately raising ``OperationalError: database is locked``. This helper
centralises that policy alongside the existing WAL + foreign_keys pragmas
so the 15+ store classes share one source of truth.

# scope: process-internal — pure connection-config helper, no spine
"""

from __future__ import annotations

import sqlite3

# 5 second default — long enough to absorb routine writer contention but
# short enough that a deadlocked writer surfaces quickly in tests.
DEFAULT_BUSY_TIMEOUT_MS = 5_000


def configure_sqlite_connection(
    conn: sqlite3.Connection,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    enable_foreign_keys: bool = False,
) -> sqlite3.Connection:
    """Apply hi-agent's standard pragmas to ``conn``.

    Sets, in order:

    * ``PRAGMA journal_mode=WAL`` — readers never block writers.
    * ``PRAGMA busy_timeout = <ms>`` — wait on lock contention instead of
      raising ``database is locked`` immediately.
    * ``PRAGMA foreign_keys = ON`` (only when ``enable_foreign_keys=True``).
      Defaults to ``False`` to preserve the legacy hi-agent behaviour where
      most stores never enabled FK enforcement; callers that DID enforce FKs
      pre-Track-D opt back in explicitly.

    Args:
        conn: An open ``sqlite3.Connection``.
        busy_timeout_ms: Lock-wait timeout in milliseconds. Defaults to
            ``DEFAULT_BUSY_TIMEOUT_MS`` (5000).
        enable_foreign_keys: Whether to enable FK enforcement. Defaults
            to ``False`` (matches pre-Track-D behaviour).

    Returns:
        The same connection (for chained-call ergonomics).
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    if enable_foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    return conn


__all__ = ["DEFAULT_BUSY_TIMEOUT_MS", "configure_sqlite_connection"]
