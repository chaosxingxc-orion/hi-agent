"""Verify all chaos scenario modules can be imported and have the required interface.

These are Layer 1 smoke tests: no server is started, no network calls are made.
Each test loads the scenario module via importlib (scenarios dir added to sys.path
so the shared ``_helpers`` module resolves) and checks:
  - ``SCENARIO_NAME`` string attribute exists
  - ``run_scenario`` callable exists with the expected signature

Profile: smoke
"""
from __future__ import annotations

import importlib.util
import inspect
import pathlib
import sys

import pytest

_SCENARIOS_DIR = pathlib.Path(__file__).resolve().parent / "scenarios"


def _load_scenario(filename: str):
    """Load a scenario module, pre-registering _helpers so relative imports work."""
    # Ensure _helpers is available under its bare name before loading any scenario.
    if "_helpers" not in sys.modules:
        helpers_path = _SCENARIOS_DIR / "_helpers.py"
        spec_h = importlib.util.spec_from_file_location("_helpers", helpers_path)
        if spec_h is not None and spec_h.loader is not None:
            mod_h = importlib.util.module_from_spec(spec_h)
            sys.modules["_helpers"] = mod_h
            spec_h.loader.exec_module(mod_h)  # type: ignore[union-attr]  # expiry_wave: Wave 30

    scenario_path = _SCENARIOS_DIR / filename
    spec = importlib.util.spec_from_file_location(scenario_path.stem, scenario_path)
    assert spec is not None and spec.loader is not None, f"could not create spec for {filename}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # expiry_wave: Wave 30
    return mod


def _check_interface(mod) -> None:  # type: ignore[type-arg]  # expiry_wave: Wave 30
    """Assert SCENARIO_NAME and run_scenario(base_url, timeout) exist."""
    assert hasattr(mod, "SCENARIO_NAME"), f"{mod.__name__} missing SCENARIO_NAME"
    assert isinstance(mod.SCENARIO_NAME, str) and mod.SCENARIO_NAME, (
        f"{mod.__name__}.SCENARIO_NAME must be a non-empty string"
    )
    assert hasattr(mod, "run_scenario") and callable(mod.run_scenario), (
        f"{mod.__name__} missing callable run_scenario"
    )
    sig = inspect.signature(mod.run_scenario)
    params = list(sig.parameters)
    assert "base_url" in params, (
        f"{mod.__name__}.run_scenario must have 'base_url' parameter"
    )
    assert "timeout" in params, (
        f"{mod.__name__}.run_scenario must have 'timeout' parameter"
    )


@pytest.mark.smoke
def test_scenario_01_importable():
    """Scenario 01: worker_kill_during_run imports and exposes correct interface."""
    mod = _load_scenario("01_worker_kill_during_run.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "worker_kill_during_run"


@pytest.mark.smoke
def test_scenario_02_importable():
    """Scenario 02: restart_after_unfinished imports and exposes correct interface."""
    mod = _load_scenario("02_restart_after_unfinished.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "restart_after_unfinished"


@pytest.mark.smoke
def test_scenario_03_importable():
    """Scenario 03: db_lock_busy imports and exposes correct interface."""
    mod = _load_scenario("03_db_lock_busy.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "db_lock_busy"


@pytest.mark.smoke
def test_scenario_04_importable():
    """Scenario 04: queue_unavailable imports and exposes correct interface."""
    mod = _load_scenario("04_queue_unavailable.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "queue_unavailable"


@pytest.mark.smoke
def test_scenario_05_importable():
    """Scenario 05: llm_timeout imports and exposes correct interface."""
    mod = _load_scenario("05_llm_timeout.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "llm_timeout"


@pytest.mark.smoke
def test_scenario_06_importable():
    """Scenario 06: tool_mcp_crash imports and exposes correct interface."""
    mod = _load_scenario("06_tool_mcp_crash.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "tool_mcp_crash"


@pytest.mark.smoke
def test_scenario_07_importable():
    """Scenario 07: disk_full_artifact_write imports and exposes correct interface."""
    mod = _load_scenario("07_disk_full_artifact_write.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "disk_full_artifact_write"


@pytest.mark.smoke
def test_scenario_08_importable():
    """Scenario 08: lease_heartbeat_stall imports and exposes correct interface."""
    mod = _load_scenario("08_lease_heartbeat_stall.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "lease_heartbeat_stall"


@pytest.mark.smoke
def test_scenario_09_importable():
    """Scenario 09: clock_skew_stale_lease imports and exposes correct interface."""
    mod = _load_scenario("09_clock_skew_stale_lease.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "clock_skew_stale_lease"


@pytest.mark.smoke
def test_scenario_10_importable():
    """Scenario 10: graceful_drain_active_work imports and exposes correct interface."""
    mod = _load_scenario("10_graceful_drain_active_work.py")
    _check_interface(mod)
    assert mod.SCENARIO_NAME == "graceful_drain_active_work"


def test_all_scenarios_discoverable():
    """All numbered scenario files are covered by the collection tests above."""
    scenario_files = sorted(_SCENARIOS_DIR.glob("[0-9][0-9]_*.py"))
    assert len(scenario_files) >= 10, (
        f"Expected at least 10 scenario files, found {len(scenario_files)}: {scenario_files}"
    )
    # Each scenario file must have SCENARIO_NAME + run_scenario
    for sf in scenario_files:
        mod = _load_scenario(sf.name)
        _check_interface(mod)
