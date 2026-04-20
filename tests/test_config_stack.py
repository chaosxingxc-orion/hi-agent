# tests/test_config_stack.py
from hi_agent.config.stack import ConfigStack
from hi_agent.config.trace_config import TraceConfig


def test_resolve_returns_trace_config():
    stack = ConfigStack()
    cfg = stack.resolve()
    assert isinstance(cfg, TraceConfig)


def test_defaults_layer_used_when_no_files():
    stack = ConfigStack()
    cfg = stack.resolve()
    assert cfg.server_port == 8080  # TraceConfig default


def test_base_file_overrides_defaults(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"server_port": 9000}')
    stack = ConfigStack(base_config_path=str(cfg_file))
    cfg = stack.resolve()
    assert cfg.server_port == 9000


def test_profile_overrides_base_file(tmp_path):
    base = tmp_path / "config.json"
    base.write_text('{"server_port": 9000, "max_stages": 5}')
    profile = tmp_path / "config.prod.json"
    profile.write_text('{"server_port": 443}')  # only override port

    stack = ConfigStack(base_config_path=str(base), profile="prod")
    cfg = stack.resolve()
    assert cfg.server_port == 443
    assert cfg.max_stages == 5  # from base, not overridden


def test_env_overrides_profile(tmp_path, monkeypatch):
    base = tmp_path / "config.json"
    base.write_text('{"server_port": 9000}')
    monkeypatch.setenv("HI_AGENT_SERVER_PORT", "7777")

    stack = ConfigStack(base_config_path=str(base))
    cfg = stack.resolve()
    assert cfg.server_port == 7777


def test_run_patch_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HI_AGENT_SERVER_PORT", "7777")
    stack = ConfigStack()
    cfg = stack.resolve(run_patch={"server_port": 5555})
    assert cfg.server_port == 5555


def test_run_patch_does_not_mutate_global(tmp_path):
    stack = ConfigStack()
    global_cfg = stack.resolve()
    run_cfg = stack.resolve(run_patch={"server_port": 5555})
    assert global_cfg.server_port != 5555
    assert run_cfg.server_port == 5555


def test_resolve_caches_global_config():
    stack = ConfigStack()
    cfg1 = stack.resolve()
    cfg2 = stack.resolve()
    assert cfg1 is cfg2  # same object — cached


def test_run_patch_creates_fresh_instance():
    stack = ConfigStack()
    global_cfg = stack.resolve()
    run_cfg = stack.resolve(run_patch={"max_stages": 99})
    assert global_cfg is not run_cfg  # not cached
    assert run_cfg.max_stages == 99


def test_invalidate_clears_cache(tmp_path):
    base = tmp_path / "config.json"
    base.write_text('{"server_port": 9000}')
    stack = ConfigStack(base_config_path=str(base))
    cfg1 = stack.resolve()
    assert cfg1.server_port == 9000

    base.write_text('{"server_port": 8888}')
    stack.invalidate()
    cfg2 = stack.resolve()
    assert cfg2.server_port == 8888
    assert cfg1 is not cfg2


def test_profile_from_env(tmp_path, monkeypatch):
    base = tmp_path / "config.json"
    base.write_text("{}")
    (tmp_path / "config.dev.json").write_text('{"max_stages": 99}')
    monkeypatch.setenv("HI_AGENT_PROFILE", "dev")

    stack = ConfigStack(base_config_path=str(base))
    cfg = stack.resolve()
    assert cfg.max_stages == 99
