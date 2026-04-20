# tests/test_config_profile.py
from hi_agent.config.profile import deep_merge, load_profile_file, profile_path_for


def test_deep_merge_scalars():
    base = {"a": 1, "b": 2}
    override = {"b": 99, "c": 3}
    result = deep_merge(base, override)
    assert result == {"a": 1, "b": 99, "c": 3}


def test_deep_merge_nested_dicts():
    base = {"x": {"a": 1, "b": 2}}
    override = {"x": {"b": 99, "c": 3}}
    result = deep_merge(base, override)
    assert result == {"x": {"a": 1, "b": 99, "c": 3}}


def test_deep_merge_does_not_mutate_base():
    base = {"a": 1}
    override = {"a": 2}
    deep_merge(base, override)
    assert base["a"] == 1  # original unchanged


def test_deep_merge_override_wins_for_scalars():
    result = deep_merge({"port": 8080}, {"port": 9090})
    assert result["port"] == 9090


def test_profile_path_for_base_file(tmp_path):
    base = str(tmp_path / "config.json")
    assert profile_path_for(base, "prod") == str(tmp_path / "config.prod.json")


def test_profile_path_for_none_base():
    assert profile_path_for(None, "prod") is None


def test_load_profile_file_exists(tmp_path):
    p = tmp_path / "config.dev.json"
    p.write_text('{"server_port": 9000}')
    result = load_profile_file(str(tmp_path / "config.json"), "dev")
    assert result == {"server_port": 9000}


def test_load_profile_file_missing(tmp_path):
    result = load_profile_file(str(tmp_path / "config.json"), "staging")
    assert result == {}
