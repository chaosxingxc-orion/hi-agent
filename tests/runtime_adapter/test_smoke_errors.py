"""Smoke test: hi_agent.runtime_adapter.errors importable and raisable."""
import pytest


@pytest.mark.smoke
def test_runtime_adapter_error_importable():
    """RuntimeAdapterError can be imported without error."""
    from hi_agent.runtime_adapter.errors import RuntimeAdapterError

    assert RuntimeAdapterError is not None


@pytest.mark.smoke
def test_illegal_state_transition_error_importable():
    """IllegalStateTransitionError can be imported without error."""
    from hi_agent.runtime_adapter.errors import IllegalStateTransitionError

    assert IllegalStateTransitionError is not None


@pytest.mark.smoke
def test_runtime_adapter_backend_error_importable():
    """RuntimeAdapterBackendError can be imported without error."""
    from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError

    assert RuntimeAdapterBackendError is not None


@pytest.mark.smoke
def test_runtime_adapter_backend_error_construction():
    """RuntimeAdapterBackendError can be instantiated with operation and cause."""
    from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError

    cause = ValueError("network timeout")
    err = RuntimeAdapterBackendError("open_stage", cause=cause)
    assert err.operation == "open_stage"
    assert "open_stage" in str(err)


@pytest.mark.smoke
def test_errors_are_exception_subclasses():
    """All error types are proper Exception subclasses."""
    from hi_agent.runtime_adapter.errors import (
        IllegalStateTransitionError,
        RuntimeAdapterBackendError,
        RuntimeAdapterError,
    )

    assert issubclass(RuntimeAdapterError, Exception)
    assert issubclass(IllegalStateTransitionError, Exception)
    assert issubclass(RuntimeAdapterBackendError, RuntimeAdapterError)
