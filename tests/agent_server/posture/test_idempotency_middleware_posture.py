"""Unit tests: register_idempotency_middleware reads strict from the facade.

W31-N (N.4) removed the inline ``from hi_agent.config.posture import Posture``
from agent_server/api/middleware/idempotency.py per R-AS-1. The strict
flag is now stamped on the IdempotencyFacade by the bootstrap (which is
the SINGLE seam allowed to import Posture). Middleware reads
``facade.is_strict`` when ``strict=None``.
"""
from __future__ import annotations

from agent_server.api.middleware.idempotency import (
    register_idempotency_middleware,
)


def test_idempotency_middleware_does_not_import_hi_agent() -> None:
    """W31-N (N.4): middleware module must NOT import from hi_agent.* per R-AS-1."""
    import agent_server.api.middleware.idempotency as mod

    # Posture used to be imported here; the deferred-import violation
    # is closed in W31-N N.4 and the seam is now the bootstrap module.
    assert not hasattr(mod, "Posture"), (
        "Posture must NOT be imported in idempotency middleware (R-AS-1); "
        "see agent_server/bootstrap.py — the canonical seam"
    )


def test_register_idempotency_strict_defaults_to_facade_dev() -> None:
    """When strict=None and facade.is_strict=False, middleware is built with strict=False."""
    captured: dict[str, object] = {}

    class FakeApp:
        def add_middleware(self, cls, **kwargs):
            captured["cls"] = cls
            captured["strict"] = kwargs.get("strict")

    class FakeFacade:
        is_strict = False

    register_idempotency_middleware(FakeApp(), facade=FakeFacade(), strict=None)
    assert captured["strict"] is False, (
        "facade.is_strict=False must produce strict=False in IdempotencyMiddleware"
    )


def test_register_idempotency_strict_defaults_to_facade_research() -> None:
    """When strict=None and facade.is_strict=True, middleware is built with strict=True."""
    captured: dict[str, object] = {}

    class FakeApp:
        def add_middleware(self, cls, **kwargs):
            captured["strict"] = kwargs.get("strict")

    class FakeFacade:
        is_strict = True

    register_idempotency_middleware(FakeApp(), facade=FakeFacade(), strict=None)
    assert captured["strict"] is True, (
        "facade.is_strict=True must produce strict=True in IdempotencyMiddleware"
    )


def test_register_idempotency_explicit_strict_overrides_facade() -> None:
    """Explicit strict=False overrides even a research-stamped facade (caller's explicit choice)."""
    captured: dict[str, object] = {}

    class FakeApp:
        def add_middleware(self, cls, **kwargs):
            captured["strict"] = kwargs.get("strict")

    class FakeFacade:
        is_strict = True

    register_idempotency_middleware(FakeApp(), facade=FakeFacade(), strict=False)
    assert captured["strict"] is False, (
        "explicit strict=False must override facade-derived value"
    )
