"""W35-T4 integration tests: TTL purge for IdempotencyStore.

Covers:

* :meth:`IdempotencyStore.purge_expired` deletes only past-expiry rows.
* The lazy-purge path inside :meth:`IdempotencyStore.reserve_or_replay`
  treats a re-reservation against an expired record as ``"created"``,
  not ``"replayed"`` / ``"conflict"``.
* No-op behaviour: an empty / all-future store returns 0 deletes.
* Disk reclaim (VACUUM) regression — a 10k-row purge shrinks the file.
* Lifespan integration — the purge task starts under
  :func:`build_real_kernel_lifespan`, ticks, and cancels cleanly on
  shutdown.

The suite is offline by design (Rule 16 ``default-offline`` profile):
all tests construct stores against ``tmp_path`` SQLite files; the
lifespan test stubs the backend so no AgentServer / LLM / network is
touched.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from hi_agent.server.idempotency import IdempotencyStore, _hash_payload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_record(
    store: IdempotencyStore,
    *,
    tenant_id: str,
    key: str,
    expires_at: float,
) -> None:
    """Insert a row directly with a chosen ``expires_at`` (bypasses TTL math).

    ``reserve_or_replay`` always derives ``expires_at = now + ttl_seconds``;
    for the purge tests we need rows that are already past-expiry from the
    moment they exist, so we INSERT directly.
    """
    now = time.time()
    with store._lock:
        store._conn.execute(
            "INSERT INTO idempotency_records "
            "(tenant_id, idempotency_key, request_hash, run_id, status, "
            "response_snapshot, created_at, updated_at, expires_at, "
            "project_id, user_id, session_id) "
            "VALUES (?, ?, ?, ?, 'pending', '', ?, ?, ?, '', '', '')",
            (
                tenant_id,
                key,
                _hash_payload({"goal": key}),
                f"run_{key}",
                now,
                now,
                expires_at,
            ),
        )
        store._conn.commit()


def _row_count(store: IdempotencyStore) -> int:
    cur = store._conn.execute("SELECT COUNT(*) FROM idempotency_records")
    (count,) = cur.fetchone()
    return int(count)


# ---------------------------------------------------------------------------
# Core purge behaviour
# ---------------------------------------------------------------------------


def test_purge_expired_deletes_only_expired(tmp_path: Path) -> None:
    """5 expired + 5 fresh rows → purge deletes exactly the 5 expired ones."""
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    try:
        now = time.time()
        for i in range(5):
            _seed_record(
                store,
                tenant_id="t1",
                key=f"expired-{i}",
                expires_at=now - 100.0,
            )
        for i in range(5):
            _seed_record(
                store,
                tenant_id="t1",
                key=f"future-{i}",
                expires_at=now + 3600.0,
            )

        assert _row_count(store) == 10
        deleted = store.purge_expired()
        assert deleted == 5
        assert _row_count(store) == 5

        cur = store._conn.execute(
            "SELECT idempotency_key FROM idempotency_records ORDER BY idempotency_key"
        )
        remaining = [row[0] for row in cur.fetchall()]
        assert remaining == [f"future-{i}" for i in range(5)]
    finally:
        store.close()


def test_lazy_purge_in_reserve_or_replay(tmp_path: Path) -> None:
    """A second reservation past expires_at returns ``"created"``, not replay."""
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    try:
        tenant = "t1"
        key = str(uuid.uuid4())
        payload_hash = _hash_payload({"goal": "x"})

        outcome1, rec1 = store.reserve_or_replay(
            tenant, key, payload_hash, run_id="run-1", ttl_seconds=0.1
        )
        assert outcome1 == "created"
        assert rec1.run_id == "run-1"

        # Wait past expiry. 0.1s TTL + 0.2s sleep = decisively expired.
        time.sleep(0.25)

        outcome2, rec2 = store.reserve_or_replay(
            tenant, key, payload_hash, run_id="run-2", ttl_seconds=60.0
        )
        # Lazy purge deletes the expired row; the new INSERT wins.
        assert outcome2 == "created"
        assert rec2.run_id == "run-2"
    finally:
        store.close()


def test_purge_no_expired_records(tmp_path: Path) -> None:
    """Empty DB and all-future DB both return 0 from purge_expired()."""
    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    try:
        # Empty: 0 deletions.
        assert store.purge_expired() == 0

        # All-future: 0 deletions.
        now = time.time()
        for i in range(3):
            _seed_record(
                store,
                tenant_id="t1",
                key=f"future-{i}",
                expires_at=now + 3600.0,
            )
        assert store.purge_expired() == 0
        assert _row_count(store) == 3
    finally:
        store.close()


def _total_db_bytes(db_path: Path) -> int:
    """Sum the SQLite main file plus its WAL/SHM sidecars.

    The store opens in WAL mode (see :mod:`hi_agent._sqlite_init`), which
    means freshly-inserted rows live in ``<db>.db-wal`` until a checkpoint
    folds them back into the main file. Comparing only ``<db>.db`` would
    miss the bloat we are trying to detect.
    """
    total = 0
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            total += candidate.stat().st_size
    return total


@pytest.mark.slow
def test_disk_growth_regression(tmp_path: Path) -> None:
    """10k expired rows + VACUUM ⇒ on-disk footprint shrinks (>=50%).

    We measure the combined size of the main DB file and its WAL/SHM
    sidecars because the store runs in WAL mode (see
    :func:`_total_db_bytes`).
    """
    db_path = tmp_path / "idem_big.db"
    store = IdempotencyStore(db_path=db_path)
    try:
        now = time.time()
        # Bulk-seed 10k expired rows in a single transaction for speed.
        rows = [
            (
                "t1",
                f"k-{i}",
                _hash_payload({"i": i}),
                f"run-{i}",
                "pending",
                "",
                now,
                now,
                now - 100.0,
                "",
                "",
                "",
            )
            for i in range(10_000)
        ]
        with store._lock:
            store._conn.executemany(
                "INSERT INTO idempotency_records "
                "(tenant_id, idempotency_key, request_hash, run_id, status, "
                "response_snapshot, created_at, updated_at, expires_at, "
                "project_id, user_id, session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            store._conn.commit()
            # Force a WAL checkpoint so the bloat is observable in the
            # main file rather than hiding in the still-open WAL.
            store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            store._conn.commit()

        size_before = _total_db_bytes(db_path)
        deleted = store.purge_expired()
        assert deleted == 10_000
        # Checkpoint and truncate the WAL so the post-purge measurement
        # reflects only the live (VACUUMed) data. Without this the WAL
        # still holds the DELETE+VACUUM pages and looks larger than the
        # original bloated state.
        with store._lock:
            store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            store._conn.commit()
        # VACUUM rewrites the database into a fresh, tightly-packed file.
        # After purge the on-disk footprint should be far smaller.
        # Allow generous slack: at least half the bytes must be reclaimed.
        size_after = _total_db_bytes(db_path)
        assert size_after < size_before * 0.5, (
            f"VACUUM did not reclaim disk: before={size_before} after={size_after}"
        )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Lifespan integration
# ---------------------------------------------------------------------------


class _FakeRunManager:
    """Minimal RunManager stand-in for the lifespan test."""

    def list_runs(self) -> list:
        return []

    def drain(self, timeout_s: float = 0.0) -> None:  # pragma: no cover
        return None

    def shutdown(self, timeout: float = 0.0) -> None:  # pragma: no cover
        return None


class _FakeAgentServer:
    """Minimal AgentServer stand-in matching what the lifespan touches."""

    def __init__(self) -> None:
        self.run_manager = _FakeRunManager()


class _FakeBackend:
    """Backend stub that exposes ``agent_server`` and ``aclose``."""

    def __init__(self, agent_server: _FakeAgentServer) -> None:
        self._agent_server = agent_server
        self.aclosed = False

    @property
    def agent_server(self) -> _FakeAgentServer:
        return self._agent_server

    def aclose(self) -> None:
        self.aclosed = True


@pytest.mark.asyncio
async def test_purge_loop_cancelled_on_lifespan_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lifespan starts purge loop, ticks, then cancels cleanly on exit.

    Uses a stub backend so the test stays inside the default-offline
    profile (no AgentServer construction, no SQLite stores beyond the
    IdempotencyStore under test). The purge interval is set to 0.1 s so
    the loop ticks at least once during the 0.3 s yield window.
    """
    # r-as-1-seam not relevant in tests; import here to keep module load light.
    from agent_server.runtime.lifespan import build_real_kernel_lifespan

    # Skip rehydration so the lifespan does not try to walk a real store.
    monkeypatch.setattr(
        "agent_server.runtime.lifespan._rehydrate_runs",
        lambda agent_server: None,
    )
    monkeypatch.setenv("HI_AGENT_IDEMPOTENCY_PURGE_INTERVAL_S", "0.1")
    monkeypatch.setenv("HI_AGENT_LEASE_EXPIRY_INTERVAL_S", "0.1")

    store = IdempotencyStore(db_path=tmp_path / "idem.db")
    try:
        # Seed one expired row so the loop has something to delete.
        _seed_record(
            store,
            tenant_id="t1",
            key="expired",
            expires_at=time.time() - 10.0,
        )

        backend = _FakeBackend(_FakeAgentServer())
        backend._idempotency_store = store  # type: ignore[attr-defined]  expiry_wave: permanent

        lifespan = build_real_kernel_lifespan(backend)  # type: ignore[arg-type]  expiry_wave: permanent

        async with lifespan(SimpleNamespace()):
            # Yield long enough for the loop to tick at least once.
            await asyncio.sleep(0.3)
            purge_task = backend._idempotency_purge_task  # type: ignore[attr-defined]  expiry_wave: permanent
            assert purge_task is not None
            assert not purge_task.done()

        # After exit: task is cancelled, no exception leaked, expired row gone.
        purge_task = backend._idempotency_purge_task  # type: ignore[attr-defined]  expiry_wave: permanent
        assert purge_task.cancelled() or purge_task.done()
        assert backend.aclosed is True
        assert _row_count(store) == 0
    finally:
        store.close()
        os.environ.pop("HI_AGENT_IDEMPOTENCY_PURGE_INTERVAL_S", None)
        os.environ.pop("HI_AGENT_LEASE_EXPIRY_INTERVAL_S", None)
