"""Unit test: RateLimiter._consume uses exec_ctx.tenant_id for bucket key."""
from hi_agent.context.run_execution_context import RunExecutionContext
from hi_agent.server.rate_limiter import RateLimiter


class _FakeApp:
    async def __call__(self, scope, receive, send):
        pass


def _make_limiter(max_requests=100, burst=100):
    return RateLimiter(_FakeApp(), max_requests=max_requests, window_seconds=60.0, burst=burst)


def test_consume_uses_exec_ctx_tenant_id():
    """exec_ctx.tenant_id is used as bucket key when provided."""
    limiter = _make_limiter()
    ctx = RunExecutionContext(tenant_id="ctx-tenant", run_id="r1")

    allowed, _ = limiter._consume("1.2.3.4", exec_ctx=ctx)

    assert allowed is True
    assert "tenant:ctx-tenant" in limiter._buckets
    assert "ip:1.2.3.4" not in limiter._buckets


def test_consume_exec_ctx_tenant_beats_kwarg_tenant():
    """exec_ctx.tenant_id takes precedence over tenant_id kwarg."""
    limiter = _make_limiter()
    ctx = RunExecutionContext(tenant_id="ctx-t")

    limiter._consume("1.2.3.4", tenant_id="kwarg-t", exec_ctx=ctx)

    assert "tenant:ctx-t" in limiter._buckets
    assert "tenant:kwarg-t" not in limiter._buckets


def test_consume_fallback_to_kwarg_when_exec_ctx_empty_tenant():
    """Falls back to tenant_id kwarg when exec_ctx.tenant_id is empty."""
    limiter = _make_limiter()
    ctx = RunExecutionContext(tenant_id="")

    limiter._consume("1.2.3.4", tenant_id="kwarg-t", exec_ctx=ctx)

    assert "tenant:kwarg-t" in limiter._buckets


def test_consume_fallback_to_ip_without_tenant():
    """Falls back to ip-based bucket when no tenant is available."""
    limiter = _make_limiter()

    limiter._consume("5.6.7.8")

    assert "ip:5.6.7.8" in limiter._buckets


def test_consume_without_exec_ctx_unchanged():
    """Original behaviour (tenant_id kwarg only) still works."""
    limiter = _make_limiter()

    limiter._consume("9.9.9.9", tenant_id="legacy-t")

    assert "tenant:legacy-t" in limiter._buckets
