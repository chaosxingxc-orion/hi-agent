"""Tests that concurrent recovery claims on the same run are prevented via adoption_token CAS.

Integration tests: real RunQueue components wired together, no mocks on the subsystem
under test (Rule 4, Layer 2).
"""
from __future__ import annotations

import threading
import time

import pytest
from hi_agent.server.run_queue import OptimisticLockError, RunQueue


class TestOptimisticLockErrorImport:
    def test_exception_importable(self):
        """OptimisticLockError must be importable from hi_agent.server.run_queue."""
        assert issubclass(OptimisticLockError, Exception)


class TestAdoptionTokenColumn:
    def test_adoption_token_column_exists(self, tmp_path):
        """run_queue table must contain adoption_token column after init."""
        db_path = str(tmp_path / "test_adoption.db")
        queue = RunQueue(db_path=db_path)
        try:
            col_names = {
                row[1]
                for row in queue._conn.execute("PRAGMA table_info(run_queue)")
            }
            assert "adoption_token" in col_names, (
                "adoption_token column must exist in run_queue table."
            )
        finally:
            queue.close()

    def test_adoption_token_null_by_default(self, tmp_path):
        """Newly enqueued runs must have adoption_token = NULL."""
        db_path = str(tmp_path / "test_adoption_null.db")
        queue = RunQueue(db_path=db_path)
        try:
            queue.enqueue("run-null-check", tenant_id="t1")
            row = queue._conn.execute(
                "SELECT adoption_token FROM run_queue WHERE run_id = ?",
                ("run-null-check",),
            ).fetchone()
            assert row is not None
            assert row[0] is None, "adoption_token must be NULL for a fresh enqueued run."
        finally:
            queue.close()


class TestConcurrentClaimPrevention:
    def test_first_claim_wins_second_returns_false(self, tmp_path):
        """Second claim_with_adoption_token call on same run must return False."""
        db_path = str(tmp_path / "test_cas.db")
        queue = RunQueue(db_path=db_path)
        try:
            queue.enqueue("run-cas-1", tenant_id="t1")
            # Manually move to 'leased' state to simulate a stale lease scenario.
            queue._conn.execute(
                "UPDATE run_queue SET status = 'leased', lease_expires_at = ? WHERE run_id = ?",
                (time.time() - 1.0, "run-cas-1"),
            )
            queue._conn.commit()

            first_claimed = queue.claim_with_adoption_token("run-cas-1", "token-alpha")
            second_claimed = queue.claim_with_adoption_token("run-cas-1", "token-beta")

            assert first_claimed is True, "First CAS claim must succeed."
            assert second_claimed is False, (
                "Second CAS claim on already-adopted run must return False."
            )
        finally:
            queue.close()

    def test_adoption_token_value_persisted(self, tmp_path):
        """The adoption_token set by the first claimer must be stored in DB."""
        db_path = str(tmp_path / "test_cas_token_value.db")
        queue = RunQueue(db_path=db_path)
        try:
            queue.enqueue("run-cas-2", tenant_id="t1")
            queue._conn.execute(
                "UPDATE run_queue SET status = 'leased', lease_expires_at = ? WHERE run_id = ?",
                (time.time() - 1.0, "run-cas-2"),
            )
            queue._conn.commit()

            queue.claim_with_adoption_token("run-cas-2", "token-gamma")

            row = queue._conn.execute(
                "SELECT adoption_token FROM run_queue WHERE run_id = ?",
                ("run-cas-2",),
            ).fetchone()
            assert row is not None
            assert row[0] == "token-gamma", "Adoption token must be persisted after CAS claim."
        finally:
            queue.close()

    def test_concurrent_threads_only_one_claim_succeeds(self, tmp_path):
        """Under concurrent access, exactly one of N threads must claim the run."""
        db_path = str(tmp_path / "test_concurrent_cas.db")
        queue = RunQueue(db_path=db_path)
        try:
            queue.enqueue("run-concurrent", tenant_id="t1")
            queue._conn.execute(
                "UPDATE run_queue SET status = 'leased', lease_expires_at = ? WHERE run_id = ?",
                (time.time() - 1.0, "run-concurrent"),
            )
            queue._conn.commit()

            results: list[bool] = []
            errors: list[Exception] = []
            barrier = threading.Barrier(5)

            def try_claim(token: str) -> None:
                try:
                    barrier.wait()  # All threads race simultaneously.
                    result = queue.claim_with_adoption_token("run-concurrent", token)
                    results.append(result)
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=try_claim, args=(f"token-{i}",))
                for i in range(5)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

            assert not errors, f"Unexpected errors during concurrent claim: {errors}"
            assert results.count(True) == 1, (
                "Exactly one thread must succeed in claiming the adoption token."
            )
            assert results.count(False) == 4, (
                "All other threads must fail the CAS claim."
            )
        finally:
            queue.close()


class TestOptimisticLockErrorCallerPattern:
    def test_caller_can_raise_on_false_return(self, tmp_path):
        """Callers that raise OptimisticLockError on False return are supported."""
        db_path = str(tmp_path / "test_caller_pattern.db")
        queue = RunQueue(db_path=db_path)
        try:
            queue.enqueue("run-olck", tenant_id="t1")
            queue._conn.execute(
                "UPDATE run_queue SET status = 'leased', lease_expires_at = ? WHERE run_id = ?",
                (time.time() - 1.0, "run-olck"),
            )
            queue._conn.commit()

            # First pass claims.
            queue.claim_with_adoption_token("run-olck", "token-first")

            # Second pass (a competing recovery worker) raises the exception.
            def second_recovery_pass() -> None:
                claimed = queue.claim_with_adoption_token("run-olck", "token-second")
                if not claimed:
                    raise OptimisticLockError(
                        "run-olck already adopted by another recovery pass"
                    )

            with pytest.raises(OptimisticLockError):
                second_recovery_pass()
        finally:
            queue.close()
