"""Unit tests for circuit breaker state transitions."""

from hi_agent.capability import CircuitBreaker


class _FakeClock:
    """Mutable clock for deterministic timing tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allow_transitions_open_to_half_open_after_cooldown() -> None:
    """Allow should stay blocked while open, then permit a half-open probe."""
    clock = _FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10.0, clock=clock)

    breaker.mark_failure("cap")
    breaker.mark_failure("cap")
    assert breaker.allow("cap") is False

    clock.advance(9.0)
    assert breaker.allow("cap") is False

    clock.advance(1.0)
    assert breaker.allow("cap") is True


def test_half_open_success_closes_breaker() -> None:
    """A successful half-open probe should close and reset the breaker."""
    clock = _FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=5.0, clock=clock)

    breaker.mark_failure("cap")
    assert breaker.allow("cap") is False

    clock.advance(5.0)
    assert breaker.allow("cap") is True

    breaker.mark_success("cap")
    assert breaker.allow("cap") is True


def test_half_open_failure_reopens_breaker() -> None:
    """A failed half-open probe should reopen and require another cooldown."""
    clock = _FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=5.0, clock=clock)

    breaker.mark_failure("cap")
    clock.advance(5.0)
    assert breaker.allow("cap") is True

    breaker.mark_failure("cap")
    assert breaker.allow("cap") is False

    clock.advance(4.9)
    assert breaker.allow("cap") is False

    clock.advance(0.1)
    assert breaker.allow("cap") is True
