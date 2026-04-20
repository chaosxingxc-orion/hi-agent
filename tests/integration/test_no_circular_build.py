def test_capability_plane_built_after_llm(tmp_path):
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.trace_config import TraceConfig

    cfg = TraceConfig()
    cfg.episodic_storage_dir = str(tmp_path / "episodes")
    sb = SystemBuilder(cfg)
    reg = sb.build_capability_registry()
    assert reg is not None
    cpb = sb._get_capability_plane_builder()
    assert hasattr(cpb, "_llm_gateway")
