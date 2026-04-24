"""Smoke test: hi_agent.runtime_adapter.async_kernel_facade_adapter importable."""
import pytest


@pytest.mark.smoke
def test_async_kernel_facade_adapter_importable():
    """AsyncKernelFacadeAdapter can be imported without error."""
    from hi_agent.runtime_adapter.async_kernel_facade_adapter import AsyncKernelFacadeAdapter

    assert AsyncKernelFacadeAdapter is not None


@pytest.mark.smoke
def test_async_kernel_facade_adapter_requires_facade():
    """AsyncKernelFacadeAdapter constructor requires a facade argument."""
    import inspect

    from hi_agent.runtime_adapter.async_kernel_facade_adapter import AsyncKernelFacadeAdapter

    sig = inspect.signature(AsyncKernelFacadeAdapter.__init__)
    params = list(sig.parameters.keys())
    assert "facade" in params
