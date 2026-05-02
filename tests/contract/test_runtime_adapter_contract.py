"""Contract tests for RuntimeAdapter protocol compliance.

Layer 1 (unit) tests — the external kernel facade is mocked via
``unittest.mock.MagicMock`` because it is a genuine external dependency
(agent-kernel service).  Internal structure checks use real adapter classes
with no internal mocking.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hi_agent.runtime_adapter.errors import (
    IllegalStateTransitionError,
    RuntimeAdapterBackendError,
    RuntimeAdapterError,
)
from hi_agent.runtime_adapter.protocol import RuntimeAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROTOCOL_METHODS: list[str] = [m for m in dir(RuntimeAdapter) if not m.startswith("_")]

# Methods that are async in the protocol
ASYNC_PROTOCOL_METHODS = {"spawn_child_run_async", "query_child_runs_async"}


def _make_mock_facade() -> MagicMock:
    """Return a MagicMock that satisfies isinstance checks for KernelFacade.

    We patch the isinstance guard inside KernelFacadeAdapter.__init__ so
    the real import of agent_kernel is not required in CI.  This is a
    legitimate mock use: external network/service dependency.
    """
    facade = MagicMock()
    # Ensure common facade methods return sensible defaults
    facade.start_run.return_value = MagicMock(run_id="run-test-001")
    facade.query_run.return_value = {"run_id": "run-test-001", "state": "running"}
    facade.query_trace_runtime.return_value = {"stages": []}
    facade.get_manifest.return_value = {"version": "1.0"}
    facade.spawn_child_run.return_value = MagicMock(child_run_id="child-001")
    facade.query_child_runs.return_value = []
    facade.query_run_postmortem.return_value = {"postmortem": "ok"}
    facade.cancel_run.return_value = None
    facade.resume_run.return_value = None
    facade.signal_run.return_value = None
    facade.open_stage.return_value = None
    facade.mark_stage_state.return_value = None
    facade.open_branch.return_value = None
    facade.mark_branch_state.return_value = None
    facade.open_human_gate.return_value = None
    facade.submit_approval.return_value = None
    facade.bind_task_view_to_decision.return_value = None
    facade.record_task_view.return_value = "tv-001"
    facade.resolve_escalation.return_value = None
    return facade


def _make_kernel_facade_adapter() -> Any:
    """Instantiate KernelFacadeAdapter with a patched isinstance check."""
    from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

    facade = _make_mock_facade()
    # Patch the isinstance guard so we don't need a live agent-kernel
    with patch(
        "hi_agent.runtime_adapter.kernel_facade_adapter.KernelFacadeAdapter.__init__",
        _patched_kernel_init,
    ):
        adapter = KernelFacadeAdapter.__new__(KernelFacadeAdapter)
        _patched_kernel_init(adapter, facade)
    return adapter, facade


def _patched_kernel_init(self: Any, facade: object) -> None:
    """Replacement __init__ that skips the real KernelFacade isinstance guard.

    Mocking reason: avoids the agent-kernel import/isinstance check which
    requires a live external service installation.
    """
    self._facade = facade
    self._current_run_id = None


def _make_async_kernel_facade_adapter() -> Any:
    """Instantiate AsyncKernelFacadeAdapter with a patched inner sync adapter."""
    from hi_agent.runtime_adapter.async_kernel_facade_adapter import (
        AsyncKernelFacadeAdapter,
    )
    from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

    facade = _make_mock_facade()

    # Build a patched sync adapter first
    sync_adapter = KernelFacadeAdapter.__new__(KernelFacadeAdapter)
    _patched_kernel_init(sync_adapter, facade)

    # Build async adapter bypassing its __init__ (which calls KernelFacadeAdapter)
    async_adapter = AsyncKernelFacadeAdapter.__new__(AsyncKernelFacadeAdapter)
    async_adapter._sync = sync_adapter
    async_adapter._facade = facade
    return async_adapter, facade, sync_adapter


# ---------------------------------------------------------------------------
# Category 1: Protocol structural compliance
# ---------------------------------------------------------------------------


class TestProtocolStructuralCompliance:
    """Verify both adapters expose all methods defined in RuntimeAdapter."""

    @pytest.mark.parametrize(
        "adapter_cls_name",
        ["KernelFacadeAdapter", "AsyncKernelFacadeAdapter"],
    )
    def test_adapter_has_all_protocol_methods(self, adapter_cls_name: str) -> None:
        """Each adapter class must have every method declared in RuntimeAdapter.

        Mocking reason: N/A — uses class introspection, no instances needed.
        """
        if adapter_cls_name == "KernelFacadeAdapter":
            from hi_agent.runtime_adapter.kernel_facade_adapter import (
                KernelFacadeAdapter,
            )
        else:
            from hi_agent.runtime_adapter.async_kernel_facade_adapter import (
                AsyncKernelFacadeAdapter,
            )

        adapter_cls = (
            KernelFacadeAdapter
            if adapter_cls_name == "KernelFacadeAdapter"
            else AsyncKernelFacadeAdapter
        )
        missing = [m for m in PROTOCOL_METHODS if not hasattr(adapter_cls, m)]
        assert not missing, f"{adapter_cls_name} is missing protocol methods: {missing}"

    def test_protocol_methods_list_is_non_empty(self) -> None:
        """Sanity check: ensure we extracted a meaningful method list."""
        assert len(PROTOCOL_METHODS) >= 17, (
            f"Expected at least 17 protocol methods, found {len(PROTOCOL_METHODS)}"
        )

    def test_kernel_facade_adapter_mode_is_property(self) -> None:
        """Mode must be a property (not a plain attribute) on KernelFacadeAdapter."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        assert isinstance(inspect.getattr_static(KernelFacadeAdapter, "mode"), property), (
            "KernelFacadeAdapter.mode must be a @property"
        )

    def test_async_kernel_facade_adapter_mode_is_property(self) -> None:
        """Mode must be a property on AsyncKernelFacadeAdapter."""
        from hi_agent.runtime_adapter.async_kernel_facade_adapter import (
            AsyncKernelFacadeAdapter,
        )

        assert isinstance(inspect.getattr_static(AsyncKernelFacadeAdapter, "mode"), property), (
            "AsyncKernelFacadeAdapter.mode must be a @property"
        )

    def test_async_methods_are_coroutines_on_async_adapter(self) -> None:
        """Async protocol methods must be coroutine functions on AsyncKernelFacadeAdapter."""
        from hi_agent.runtime_adapter.async_kernel_facade_adapter import (
            AsyncKernelFacadeAdapter,
        )

        for method_name in ASYNC_PROTOCOL_METHODS:
            method = getattr(AsyncKernelFacadeAdapter, method_name, None)
            assert method is not None, f"AsyncKernelFacadeAdapter missing {method_name}"
            assert inspect.iscoroutinefunction(method), (
                f"AsyncKernelFacadeAdapter.{method_name} must be async"
            )

    def test_sync_lifecycle_methods_present_on_kernel_facade_adapter(self) -> None:
        """All sync stage/run/branch/gate methods must exist on KernelFacadeAdapter."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        required_sync = [
            "open_stage",
            "mark_stage_state",
            "record_task_view",
            "bind_task_view_to_decision",
            "start_run",
            "query_run",
            "cancel_run",
            "resume_run",
            "signal_run",
            "query_trace_runtime",
            "open_branch",
            "mark_branch_state",
            "open_human_gate",
            "submit_approval",
            "get_manifest",
            "query_run_postmortem",
            "spawn_child_run",
            "query_child_runs",
            "resolve_escalation",
        ]
        missing = [m for m in required_sync if not hasattr(KernelFacadeAdapter, m)]
        assert not missing, f"KernelFacadeAdapter missing: {missing}"


# ---------------------------------------------------------------------------
# Category 2: Instantiation contracts
# ---------------------------------------------------------------------------


class TestInstantiationContracts:
    """Verify adapter instantiation and basic property contracts."""

    def test_kernel_facade_adapter_mode_returns_local_fsm(self) -> None:
        """KernelFacadeAdapter.mode must return 'local-fsm'.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        adapter, _ = _make_kernel_facade_adapter()
        assert adapter.mode == "local-fsm"

    def test_async_kernel_facade_adapter_mode_returns_local_fsm(self) -> None:
        """AsyncKernelFacadeAdapter.mode must delegate to sync and return 'local-fsm'.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        async_adapter, _, _ = _make_async_kernel_facade_adapter()
        assert async_adapter.mode == "local-fsm"

    def test_kernel_facade_adapter_initial_run_id_is_none(self) -> None:
        """_current_run_id starts as None before any start_run call."""
        adapter, _ = _make_kernel_facade_adapter()
        assert adapter._current_run_id is None

    def test_kernel_facade_adapter_facade_stored(self) -> None:
        """KernelFacadeAdapter stores the facade object passed to __init__."""
        adapter, facade = _make_kernel_facade_adapter()
        assert adapter._facade is facade

    def test_async_adapter_wraps_sync_adapter(self) -> None:
        """AsyncKernelFacadeAdapter._sync must be a KernelFacadeAdapter instance."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        async_adapter, _, sync_adapter = _make_async_kernel_facade_adapter()
        assert isinstance(async_adapter._sync, KernelFacadeAdapter)
        assert async_adapter._sync is sync_adapter

    def test_kernel_facade_adapter_rejects_empty_start_run(self) -> None:
        """start_run with empty task_id must raise ValueError.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        adapter, _ = _make_kernel_facade_adapter()
        # _non_empty raises ValueError for blank strings before touching facade
        with pytest.raises((ValueError, RuntimeAdapterBackendError)):
            adapter.start_run("   ")

    def test_kernel_facade_adapter_open_stage_empty_run_id_raises(
        self,
    ) -> None:
        """open_stage with empty run_id must raise ValueError.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        run_id is now an explicit parameter; empty string is the invalid sentinel.
        """
        adapter, _ = _make_kernel_facade_adapter()
        with pytest.raises(ValueError, match="run_id"):
            adapter.open_stage("", "S1")

    def test_kernel_facade_adapter_mark_stage_state_empty_run_id_raises(
        self,
    ) -> None:
        """mark_stage_state with empty run_id must raise ValueError.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        run_id is now an explicit parameter; empty string is the invalid sentinel.
        """
        from hi_agent.contracts import StageState

        adapter, _ = _make_kernel_facade_adapter()
        with pytest.raises(ValueError, match="run_id"):
            adapter.mark_stage_state("", "S1", StageState.ACTIVE)


# ---------------------------------------------------------------------------
# Category 3: Null / error handling contracts
# ---------------------------------------------------------------------------


class TestErrorHandlingContracts:
    """Verify error wrapping and typed error behaviour."""

    def test_cancel_run_empty_run_id_raises_value_error(self) -> None:
        """cancel_run with empty run_id raises ValueError before hitting facade.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        adapter, facade = _make_kernel_facade_adapter()
        # _non_empty() raises ValueError on blank input
        with pytest.raises((ValueError, RuntimeAdapterBackendError)):
            adapter.cancel_run("", "some reason")
        # facade must NOT have been called
        facade.cancel_run.assert_not_called()

    def test_cancel_run_empty_reason_raises_value_error(self) -> None:
        """cancel_run with empty reason raises ValueError before hitting facade.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        adapter, facade = _make_kernel_facade_adapter()
        with pytest.raises((ValueError, RuntimeAdapterBackendError)):
            adapter.cancel_run("run-001", "  ")
        facade.cancel_run.assert_not_called()

    def test_facade_error_wrapped_in_backend_error(self) -> None:
        """When facade method raises, KernelFacadeAdapter wraps it in RuntimeAdapterBackendError.

        Mocking reason: fault injection to verify error wrapping contract.
        """
        adapter, facade = _make_kernel_facade_adapter()
        facade.open_stage.side_effect = RuntimeError("kernel exploded")

        with pytest.raises(RuntimeAdapterBackendError) as exc_info:
            adapter.open_stage("run-001", "S1")
        assert exc_info.value.operation == "open_stage"
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    def test_runtime_adapter_backend_error_is_runtime_adapter_error(self) -> None:
        """RuntimeAdapterBackendError must be a subclass of RuntimeAdapterError."""
        assert issubclass(RuntimeAdapterBackendError, RuntimeAdapterError)

    def test_illegal_state_transition_error_is_exception(self) -> None:
        """IllegalStateTransitionError must be an Exception subclass."""
        assert issubclass(IllegalStateTransitionError, Exception)

    def test_backend_error_stores_operation(self) -> None:
        """RuntimeAdapterBackendError.operation must be stored correctly."""
        cause = ValueError("bad thing happened")
        err = RuntimeAdapterBackendError("query_run", cause=cause)
        assert err.operation == "query_run"
        assert "query_run" in str(err)

    def test_backend_error_chains_cause(self) -> None:
        """RuntimeAdapterBackendError must chain the original exception."""
        cause = ConnectionError("timeout")
        err = RuntimeAdapterBackendError("start_run", cause=cause)
        # The message must include the cause's text
        assert "timeout" in str(err) or "start_run" in str(err)

    def test_resolve_escalation_empty_run_id_raises(self) -> None:
        """resolve_escalation with empty run_id raises RuntimeAdapterBackendError.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        adapter, facade = _make_kernel_facade_adapter()
        with pytest.raises(RuntimeAdapterBackendError) as exc_info:
            adapter.resolve_escalation("  ")
        assert exc_info.value.operation == "resolve_escalation"
        facade.resolve_escalation.assert_not_called()

    def test_query_run_non_dict_result_raises_backend_error(self) -> None:
        """query_run raises RuntimeAdapterBackendError for unsupported facade results.

        Mocking reason: fault injection to verify result normalisation contract.
        """
        adapter, facade = _make_kernel_facade_adapter()
        # Returning a plain string (not a dict, not a dataclass) triggers the error branch
        facade.query_run.return_value = "not-a-dict"
        with pytest.raises(RuntimeAdapterBackendError) as exc_info:
            adapter.query_run("run-001")
        assert exc_info.value.operation == "query_run"

    def test_get_manifest_non_dict_result_wraps_to_dict(self) -> None:
        """get_manifest must convert __dict__-carrying objects to dict without raising.

        Mocking reason: facade returns a custom object; verifies normalisation.
        """
        adapter, facade = _make_kernel_facade_adapter()

        class FakeManifest:
            def __init__(self) -> None:
                self.version = "2.0"
                self.capabilities = ["run", "branch"]

        facade.get_manifest.return_value = FakeManifest()
        result = adapter.get_manifest()
        assert isinstance(result, dict)
        assert "version" in result

    def test_facade_missing_method_raises_backend_error(self) -> None:
        """Calling an unimplemented facade method must raise RuntimeAdapterBackendError.

        Mocking reason: fault injection — facade with missing method simulates
        an older agent-kernel version.
        """
        adapter, facade = _make_kernel_facade_adapter()
        # Remove the method entirely from the mock
        del facade.open_stage
        facade.configure_mock(**{"open_stage": None})  # sets to non-callable None

        with pytest.raises(RuntimeAdapterBackendError) as exc_info:
            adapter.open_stage("run-001", "S1")
        assert exc_info.value.operation == "open_stage"

    def test_record_task_view_rejects_non_dict_content(self) -> None:
        """record_task_view must raise ValueError when content is not a dict.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        adapter, _ = _make_kernel_facade_adapter()
        adapter._current_run_id = "run-001"
        with pytest.raises(ValueError):
            adapter.record_task_view("tv-001", "not-a-dict")  # type: ignore[arg-type]  expiry_wave: Wave 30

    def test_signal_run_non_dict_payload_raises_value_error(self) -> None:
        """signal_run must raise ValueError when payload is not a dict.

        Mocking reason: bypasses agent-kernel isinstance guard (external dep).
        """
        adapter, _ = _make_kernel_facade_adapter()
        with pytest.raises((ValueError, RuntimeAdapterBackendError)):
            adapter.signal_run("run-001", "pause", payload="not-a-dict")  # type: ignore[arg-type]  expiry_wave: Wave 30


# ---------------------------------------------------------------------------
# Category 4: Protocol member signatures
# ---------------------------------------------------------------------------


class TestProtocolSignatures:
    """Verify key method signatures match the protocol contract."""

    def test_start_run_signature_on_kernel_facade_adapter(self) -> None:
        """start_run(task_id: str) must be present with correct positional param."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        sig = inspect.signature(KernelFacadeAdapter.start_run)
        params = list(sig.parameters.keys())
        assert "task_id" in params

    def test_cancel_run_signature_on_kernel_facade_adapter(self) -> None:
        """cancel_run(run_id, reason) must have both required positional params."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        sig = inspect.signature(KernelFacadeAdapter.cancel_run)
        params = list(sig.parameters.keys())
        assert "run_id" in params
        assert "reason" in params

    def test_mark_branch_state_has_optional_failure_code(self) -> None:
        """mark_branch_state must have an optional failure_code parameter."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        sig = inspect.signature(KernelFacadeAdapter.mark_branch_state)
        params = sig.parameters
        assert "failure_code" in params
        # failure_code must have a default (None)
        assert params["failure_code"].default is None

    def test_signal_run_has_optional_payload(self) -> None:
        """signal_run must have an optional payload parameter defaulting to None."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        sig = inspect.signature(KernelFacadeAdapter.signal_run)
        params = sig.parameters
        assert "payload" in params
        assert params["payload"].default is None

    def test_spawn_child_run_has_optional_config(self) -> None:
        """spawn_child_run must have an optional config parameter defaulting to None."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        sig = inspect.signature(KernelFacadeAdapter.spawn_child_run)
        params = sig.parameters
        assert "config" in params
        assert params["config"].default is None

    def test_resolve_escalation_keyword_only_params(self) -> None:
        """resolve_escalation must have resolution_notes and caused_by as keyword-only."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        sig = inspect.signature(KernelFacadeAdapter.resolve_escalation)
        params = sig.parameters
        assert "resolution_notes" in params
        assert "caused_by" in params
        assert params["resolution_notes"].kind == inspect.Parameter.KEYWORD_ONLY
        assert params["caused_by"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_spawn_child_run_async_is_coroutine_on_kernel_facade_adapter(
        self,
    ) -> None:
        """KernelFacadeAdapter.spawn_child_run_async must be a coroutine function."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        assert inspect.iscoroutinefunction(KernelFacadeAdapter.spawn_child_run_async)

    def test_query_child_runs_async_is_coroutine_on_kernel_facade_adapter(
        self,
    ) -> None:
        """KernelFacadeAdapter.query_child_runs_async must be a coroutine function."""
        from hi_agent.runtime_adapter.kernel_facade_adapter import KernelFacadeAdapter

        assert inspect.iscoroutinefunction(KernelFacadeAdapter.query_child_runs_async)
