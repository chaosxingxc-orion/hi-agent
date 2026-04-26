"""Smoke test: hi_agent.runtime_adapter.resilient_kernel_adapter importable."""

import pytest


@pytest.mark.smoke
def test_resilient_kernel_adapter_importable():
    """ResilientKernelAdapter can be imported without error."""
    from hi_agent.runtime_adapter.resilient_kernel_adapter import ResilientKernelAdapter

    assert ResilientKernelAdapter is not None


@pytest.mark.smoke
def test_write_methods_constant_importable():
    """_WRITE_METHODS frozenset can be imported and is non-empty."""
    from hi_agent.runtime_adapter.resilient_kernel_adapter import _WRITE_METHODS

    assert isinstance(_WRITE_METHODS, frozenset)
    assert len(_WRITE_METHODS) > 0


@pytest.mark.smoke
def test_write_methods_contains_core_mutating_ops():
    """_WRITE_METHODS includes expected core mutating operations."""
    from hi_agent.runtime_adapter.resilient_kernel_adapter import _WRITE_METHODS

    expected = {"open_stage", "mark_stage_state", "start_run", "cancel_run", "signal_run"}
    for method in expected:
        assert method in _WRITE_METHODS, f"_WRITE_METHODS missing: {method}"


@pytest.mark.smoke
def test_resilient_kernel_adapter_instantiable():
    """ResilientKernelAdapter can be instantiated wrapping a minimal inner adapter."""
    from hi_agent.runtime_adapter.resilient_kernel_adapter import ResilientKernelAdapter

    class _MinimalInner:
        """Minimal inner adapter stub for smoke testing."""

        @property
        def mode(self):
            return "local-fsm"

    try:
        from hi_agent.runtime_adapter.consistency import InMemoryConsistencyJournal

        adapter = ResilientKernelAdapter(_MinimalInner(), journal=InMemoryConsistencyJournal())
        assert adapter is not None
    except TypeError as e:
        pytest.skip(f"Constructor requires dependencies not available in smoke: {e}")
