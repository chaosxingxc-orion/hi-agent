from unittest.mock import MagicMock

from hi_agent.capability.adapters.descriptor_factory import CapabilityDescriptor
from hi_agent.capability.registry import CapabilityRegistry


def _make_spec(name, required_env=None, probe=None):
    desc = CapabilityDescriptor(
        name=name,
        required_env=required_env or {},
        availability_probe=probe,
    )
    spec = MagicMock()
    spec.descriptor = desc
    spec.name = name
    return spec


def _make_registry(*specs):
    registry = CapabilityRegistry()
    for spec in specs:
        registry._capabilities[spec.name] = spec
    return registry


def test_probe_available_when_no_requirements():
    registry = _make_registry(_make_spec("test_cap"))
    ok, reason = registry.probe_availability("test_cap")
    assert ok is True
    assert reason == ""


def test_probe_unavailable_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("FAKE_KEY_XYZ", raising=False)
    registry = _make_registry(_make_spec("llm_cap", required_env={"FAKE_KEY_XYZ": "test key"}))
    ok, reason = registry.probe_availability("llm_cap")
    assert ok is False
    assert "FAKE_KEY_XYZ" in reason


def test_probe_available_when_env_var_present(monkeypatch):
    monkeypatch.setenv("FAKE_KEY_XYZ", "sk-test")
    registry = _make_registry(_make_spec("llm_cap", required_env={"FAKE_KEY_XYZ": "test key"}))
    ok, _ = registry.probe_availability("llm_cap")
    assert ok is True


def test_probe_calls_availability_probe_callable():
    custom_probe = MagicMock(return_value=(False, "service down"))
    registry = _make_registry(_make_spec("service_cap", probe=custom_probe))
    ok, reason = registry.probe_availability("service_cap")
    assert ok is False
    assert reason == "service down"
    custom_probe.assert_called_once()


def test_probe_returns_false_for_unregistered():
    registry = CapabilityRegistry()
    ok, reason = registry.probe_availability("nonexistent")
    assert ok is False
    assert "not registered" in reason


def test_probe_handles_probe_exception_gracefully():
    def bad_probe():
        raise RuntimeError("boom")

    registry = _make_registry(_make_spec("cap", probe=bad_probe))
    ok, reason = registry.probe_availability("cap")
    assert ok is False
    assert "boom" in reason


def test_list_with_views_returns_tuples(monkeypatch):
    monkeypatch.delenv("MISSING_ENV_VAR", raising=False)
    spec1 = _make_spec("cap_a")
    spec2 = _make_spec("cap_b", required_env={"MISSING_ENV_VAR": "test"})
    registry = _make_registry(spec1, spec2)
    views = registry.list_with_views()
    assert len(views) == 2
    names = [v[0] for v in views]
    assert "cap_a" in names and "cap_b" in names
    # cap_a: available, cap_b: unavailable
    cap_a_view = next(v for v in views if v[0] == "cap_a")
    cap_b_view = next(v for v in views if v[0] == "cap_b")
    assert cap_a_view[2] == "available"
    assert cap_b_view[2] == "unavailable"
