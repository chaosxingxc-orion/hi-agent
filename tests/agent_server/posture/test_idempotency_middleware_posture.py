"""Unit tests: register_idempotency_middleware uses Posture.from_env() not string-compare."""
from __future__ import annotations

from agent_server.api.middleware.idempotency import (
    register_idempotency_middleware,
)


def test_idempotency_middleware_uses_posture_enum(monkeypatch):
    """register_idempotency_middleware imports Posture; no raw os.environ string-compare."""
    import agent_server.api.middleware.idempotency as mod

    # Verify Posture is imported in the module
    assert hasattr(mod, "Posture"), (
        "Posture must be imported in idempotency middleware module"
    )


def test_register_idempotency_strict_defaults_to_posture_dev(monkeypatch):
    """When strict is None and posture is dev, middleware is constructed with strict=False."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")

    # Capture what strict value is passed to IdempotencyMiddleware
    captured = {}

    class FakeApp:
        def add_middleware(self, cls, **kwargs):
            captured["cls"] = cls
            captured["strict"] = kwargs.get("strict")

    class FakeFacade:
        pass

    register_idempotency_middleware(FakeApp(), facade=FakeFacade(), strict=None)
    assert captured["strict"] is False, (
        "dev posture must produce strict=False in IdempotencyMiddleware"
    )


def test_register_idempotency_strict_defaults_to_posture_research(monkeypatch):
    """When strict is None and posture is research, middleware is constructed with strict=True."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    captured = {}

    class FakeApp:
        def add_middleware(self, cls, **kwargs):
            captured["cls"] = cls
            captured["strict"] = kwargs.get("strict")

    class FakeFacade:
        pass

    register_idempotency_middleware(FakeApp(), facade=FakeFacade(), strict=None)
    assert captured["strict"] is True, (
        "research posture must produce strict=True in IdempotencyMiddleware"
    )


def test_register_idempotency_explicit_strict_overrides_posture(monkeypatch):
    """Explicit strict=False overrides even a research posture (caller's explicit choice)."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")

    captured = {}

    class FakeApp:
        def add_middleware(self, cls, **kwargs):
            captured["strict"] = kwargs.get("strict")

    class FakeFacade:
        pass

    register_idempotency_middleware(FakeApp(), facade=FakeFacade(), strict=False)
    assert captured["strict"] is False, (
        "explicit strict=False must override posture-derived value"
    )
