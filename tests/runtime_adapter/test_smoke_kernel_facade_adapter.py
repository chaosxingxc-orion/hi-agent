"""Smoke test: hi_agent.runtime_adapter.kernel_facade_adapter importable."""
import pytest


@pytest.mark.smoke
def test_kernel_facade_adapter_importable():
    """KernelFacadeAdapter can be imported without error."""
    from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

    assert KernelFacadeAdapter is not None


@pytest.mark.smoke
def test_ensure_workflow_signal_run_compat_importable():
    """_ensure_workflow_signal_run_compat helper can be imported without error."""
    from hi_agent.runtime_adapter.kernel_facade_adapter import (
        _ensure_workflow_signal_run_compat,
    )

    assert _ensure_workflow_signal_run_compat is not None


@pytest.mark.smoke
def test_kernel_facade_adapter_has_mode_property():
    """KernelFacadeAdapter exposes a 'mode' property."""
    import inspect

    from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

    assert isinstance(inspect.getattr_static(KernelFacadeAdapter, "mode"), property)
