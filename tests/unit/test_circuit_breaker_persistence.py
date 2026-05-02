"""Unit tests for CircuitBreaker optional SQLite persistence (H-1)."""

from __future__ import annotations

import sqlite3

import pytest
from hi_agent.capability.circuit_breaker import CircuitBreaker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trip(cb: CircuitBreaker, name: str) -> None:
    """Drive breaker to open state using its configured threshold."""
    for _ in range(cb.failure_threshold):
        cb.mark_failure(name)


# ---------------------------------------------------------------------------
# No-db path: behavior must be identical to original
# ---------------------------------------------------------------------------


class TestNoPersistence:
    """With no db_path, CircuitBreaker works exactly as before."""

    def test_allow_closed_by_default(self) -> None:
        cb = CircuitBreaker()
        assert cb.allow("svc") is True

    def test_trips_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        _trip(cb, "svc")
        assert cb.allow("svc") is False

    def test_success_resets(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        _trip(cb, "svc")
        cb.mark_success("svc")
        assert cb.allow("svc") is True

    def test_half_open_after_cooldown(self) -> None:
        ticks = [0.0]
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10.0, clock=lambda: ticks[0])
        _trip(cb, "svc")
        assert cb.allow("svc") is False
        ticks[0] = 11.0
        assert cb.allow("svc") is True

    def test_no_db_attribute_is_none(self) -> None:
        cb = CircuitBreaker()
        assert cb._db is None

    def test_close_noop_without_db(self) -> None:
        cb = CircuitBreaker()
        cb.close()  # must not raise


# ---------------------------------------------------------------------------
# In-memory SQLite path (:memory:)
# ---------------------------------------------------------------------------


class TestInMemoryPersistence:
    """db_path=':memory:' creates SQLite backend and persists transitions."""

    def test_table_created(self) -> None:
        cb = CircuitBreaker(db_path=":memory:")
        assert cb._db is not None
        cursor = cb._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='circuit_breaker_state'"
        )
        assert cursor.fetchone() is not None
        cb.close()

    def test_wal_mode(self) -> None:
        cb = CircuitBreaker(db_path=":memory:")
        row = cb._db.execute("PRAGMA journal_mode").fetchone()  # type: ignore[union-attr]  expiry_wave: Wave 30
        # :memory: always returns "memory" for journal_mode, which is fine —
        # the PRAGMA is accepted without error.
        assert row is not None, "Expected non-None result for row"
        cb.close()

    def test_failure_persisted(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, db_path=":memory:")
        cb.mark_failure("cap")
        row = cb._db.execute(  # type: ignore[union-attr]  expiry_wave: Wave 30
            "SELECT state, failures FROM circuit_breaker_state WHERE name='cap'"
        ).fetchone()
        assert row is not None, "Expected non-None result for row"
        assert row[0] == "closed"
        assert row[1] == 1
        cb.close()

    def test_open_state_persisted(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, db_path=":memory:")
        _trip(cb, "cap")
        row = cb._db.execute(  # type: ignore[union-attr]  expiry_wave: Wave 30
            "SELECT state FROM circuit_breaker_state WHERE name='cap'"
        ).fetchone()
        assert row is not None, "Expected non-None result for row"
        assert row[0] == "open"
        cb.close()

    def test_success_persists_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, db_path=":memory:")
        _trip(cb, "cap")
        cb.mark_success("cap")
        row = cb._db.execute(  # type: ignore[union-attr]  expiry_wave: Wave 30
            "SELECT state, failures FROM circuit_breaker_state WHERE name='cap'"
        ).fetchone()
        assert row is not None, "Expected non-None result for row"
        assert row[0] == "closed"
        assert row[1] == 0
        cb.close()

    def test_half_open_persisted_on_cooldown(self) -> None:
        ticks = [0.0]
        cb = CircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=5.0,
            clock=lambda: ticks[0],
            db_path=":memory:",
        )
        _trip(cb, "cap")
        ticks[0] = 6.0
        cb.allow("cap")  # triggers half_open transition
        row = cb._db.execute(  # type: ignore[union-attr]  expiry_wave: Wave 30
            "SELECT state FROM circuit_breaker_state WHERE name='cap'"
        ).fetchone()
        assert row is not None, "Expected non-None result for row"
        assert row[0] == "half_open"
        cb.close()


# ---------------------------------------------------------------------------
# File-backed SQLite: state survives close/reopen
# ---------------------------------------------------------------------------


class TestFilePersistence:
    """Open state loaded on init from persisted storage (file-backed)."""

    def test_open_state_survives_restart(self, tmp_path: pytest.TempPathFactory) -> None:
        db_file = str(tmp_path / "cb.db")  # type: ignore[operator]  expiry_wave: Wave 30

        # First instance: trip the breaker
        cb1 = CircuitBreaker(failure_threshold=2, cooldown_seconds=9999.0, db_path=db_file)
        _trip(cb1, "svc")
        assert cb1.allow("svc") is False
        cb1.close()

        # Second instance: should load persisted "open" state
        cb2 = CircuitBreaker(failure_threshold=2, cooldown_seconds=9999.0, db_path=db_file)
        assert cb2.allow("svc") is False
        cb2.close()

    def test_closed_state_not_reloaded(self, tmp_path: pytest.TempPathFactory) -> None:
        db_file = str(tmp_path / "cb2.db")  # type: ignore[operator]  expiry_wave: Wave 30

        cb1 = CircuitBreaker(failure_threshold=2, cooldown_seconds=9999.0, db_path=db_file)
        _trip(cb1, "svc")
        cb1.mark_success("svc")
        cb1.close()

        # "closed" states are NOT loaded on init (only "open" states are)
        cb2 = CircuitBreaker(failure_threshold=2, cooldown_seconds=9999.0, db_path=db_file)
        assert "svc" not in cb2._states
        assert cb2.allow("svc") is True
        cb2.close()

    def test_only_open_loaded_on_init(self, tmp_path: pytest.TempPathFactory) -> None:
        """Verify that only 'open' rows are loaded, not 'closed' or 'half_open'."""
        db_file = str(tmp_path / "cb3.db")  # type: ignore[operator]  expiry_wave: Wave 30

        # Manually inject a half_open row directly into SQLite
        conn = sqlite3.connect(db_file)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS circuit_breaker_state"
            " (name TEXT PRIMARY KEY, state TEXT, opened_at REAL, failures INTEGER)"
        )
        conn.execute(
            "INSERT INTO circuit_breaker_state VALUES (?, ?, ?, ?)",
            ("half_cap", "half_open", 0.0, 1),
        )
        conn.execute(
            "INSERT INTO circuit_breaker_state VALUES (?, ?, ?, ?)",
            ("open_cap", "open", 0.0, 2),
        )
        conn.commit()
        conn.close()

        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=9999.0, db_path=db_file)
        assert "half_cap" not in cb._states  # half_open not reloaded
        assert "open_cap" in cb._states
        assert cb._states["open_cap"].status == "open"
        cb.close()

    def test_multiple_named_circuits_survive_restart(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        db_file = str(tmp_path / "cb4.db")  # type: ignore[operator]  expiry_wave: Wave 30

        cb1 = CircuitBreaker(failure_threshold=1, cooldown_seconds=9999.0, db_path=db_file)
        _trip(cb1, "alpha")
        _trip(cb1, "beta")
        cb1.mark_success("beta")  # reset beta
        cb1.close()

        cb2 = CircuitBreaker(failure_threshold=1, cooldown_seconds=9999.0, db_path=db_file)
        assert cb2.allow("alpha") is False  # still open
        assert cb2.allow("beta") is True  # was reset, not in _states → default closed
        cb2.close()
