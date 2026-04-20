from hi_agent.contracts.execution_provenance import ExecutionProvenance


def test_kernel_mode_propagates_through_runtime_context():
    """kernel_mode from runtime_context flows into ExecutionProvenance."""
    prov = ExecutionProvenance.build_from_stages(
        stage_summaries=[],
        runtime_context={
            "runtime_mode": "dev-smoke",
            "mcp_transport": "not_wired",
            "kernel_mode": "local-fsm",
        },
    )
    assert prov.kernel_mode == "local-fsm"


def test_kernel_mode_http_propagates():
    prov = ExecutionProvenance.build_from_stages(
        stage_summaries=[],
        runtime_context={
            "runtime_mode": "prod-real",
            "mcp_transport": "stdio",
            "kernel_mode": "http",
        },
    )
    assert prov.kernel_mode == "http"


def test_kernel_mode_defaults_to_unknown_when_absent():
    prov = ExecutionProvenance.build_from_stages(
        stage_summaries=[],
        runtime_context={"runtime_mode": "dev-smoke", "mcp_transport": "not_wired"},
        # no "kernel_mode" key
    )
    assert prov.kernel_mode == "unknown"


def test_local_fsm_adapter_mode_property():
    """KernelFacadeAdapter (local) must expose mode='local-fsm'."""
    from hi_agent.runtime_adapter import KernelFacadeAdapter
    adapter = KernelFacadeAdapter.__new__(KernelFacadeAdapter)
    assert adapter.mode == "local-fsm"
