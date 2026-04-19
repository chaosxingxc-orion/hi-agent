"""Integration tests for cooperative run cancellation."""

from __future__ import annotations

import pytest

from hi_agent.runtime.cancellation import CancellationToken, RunCancelledError
from hi_agent.server.run_queue import RunQueue


class TestCancellationTokenStandalone:
    """CancellationToken used without a RunQueue (in-memory only)."""

    def test_not_cancelled_by_default(self) -> None:
        token = CancellationToken(run_id="run-1")
        assert not token.is_cancelled

    def test_cancel_sets_flag(self) -> None:
        token = CancellationToken(run_id="run-1")
        token.cancel()
        assert token.is_cancelled

    def test_check_or_raise_raises_when_cancelled(self) -> None:
        token = CancellationToken(run_id="run-1")
        token.cancel()
        with pytest.raises(RunCancelledError):
            token.check_or_raise()

    def test_check_or_raise_does_not_raise_when_not_cancelled(self) -> None:
        token = CancellationToken(run_id="run-1")
        token.check_or_raise()  # must not raise


class TestCancellationTokenWithQueue:
    """CancellationToken reads cancellation state from durable RunQueue."""

    def test_cancel_run_via_queue_is_visible_to_token(self) -> None:
        rq = RunQueue(db_path=":memory:")
        try:
            rq.enqueue("run-q", priority=0)
            token = CancellationToken(run_id="run-q", run_queue=rq)
            assert not token.is_cancelled

            # Cancellation issued via the queue (simulates cancel_run() in RunManager).
            rq.cancel("run-q")

            assert token.is_cancelled

        finally:
            rq.close()

    def test_cancel_token_also_sets_queue_flag(self) -> None:
        rq = RunQueue(db_path=":memory:")
        try:
            rq.enqueue("run-q2", priority=0)
            token = CancellationToken(run_id="run-q2", run_queue=rq)
            assert not rq.is_cancelled("run-q2")

            token.cancel()

            assert rq.is_cancelled("run-q2")
            assert token.is_cancelled

        finally:
            rq.close()

    def test_check_or_raise_raises_when_queue_flag_set(self) -> None:
        rq = RunQueue(db_path=":memory:")
        try:
            rq.enqueue("run-q3", priority=0)
            token = CancellationToken(run_id="run-q3", run_queue=rq)
            rq.cancel("run-q3")

            with pytest.raises(RunCancelledError):
                token.check_or_raise()

        finally:
            rq.close()
