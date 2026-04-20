"""Unit tests for build_doctor_report — each check in isolation."""
import os
from unittest.mock import MagicMock

from hi_agent.ops.diagnostics import build_doctor_report


def _make_builder(env="dev", evolve_mode="auto"):
    builder = MagicMock()
    builder._env = env
    config = MagicMock()
    config.evolve_mode = evolve_mode
    config.profile_id = "default"
    builder._config = config
    builder.config = config
    builder._mcp_status = {}
    builder._skill_loader = None
    builder._capability_registry = MagicMock()
    builder._capability_registry._handlers = {"plan": MagicMock()}
    return builder


def test_dev_no_llm_key_is_warning_not_blocking(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    builder = _make_builder(env="dev")
    report = build_doctor_report(builder)
    assert report.status in ("ready", "degraded")
    blocking_codes = [i.code for i in report.blocking]
    assert "llm.missing_credentials" not in blocking_codes


def test_prod_no_llm_key_is_blocking(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("HI_AGENT_KERNEL_URL", "http://localhost:9999")  # prevent kernel block
    builder = _make_builder(env="prod")
    report = build_doctor_report(builder)
    blocking_codes = [i.code for i in report.blocking]
    assert "llm.missing_credentials" in blocking_codes


def test_prod_no_kernel_url_is_blocking(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("HI_AGENT_KERNEL_URL", raising=False)
    builder = _make_builder(env="prod")
    report = build_doctor_report(builder)
    blocking_codes = [i.code for i in report.blocking]
    assert "kernel.missing_url" in blocking_codes
    # Check fix message
    kernel_issue = next(i for i in report.blocking if i.code == "kernel.missing_url")
    assert "HI_AGENT_KERNEL_URL" in kernel_issue.fix


def test_dev_ready_when_no_issues(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    builder = _make_builder(env="dev")
    report = build_doctor_report(builder)
    # In dev with API key: should be ready or degraded (warnings ok)
    assert report.status in ("ready", "degraded")
    assert len(report.blocking) == 0


def test_evolve_policy_appears_in_info():
    builder = _make_builder(evolve_mode="on")
    report = build_doctor_report(builder)
    info_codes = [i.code for i in report.info]
    assert "evolve.policy_info" in info_codes
    evolve_issue = next(i for i in report.info if i.code == "evolve.policy_info")
    assert "on" in evolve_issue.message


def test_report_to_dict_has_all_keys():
    builder = _make_builder()
    report = build_doctor_report(builder)
    d = report.to_dict()
    assert set(d.keys()) == {"status", "blocking", "warnings", "info", "next_steps"}
    assert isinstance(d["blocking"], list)
    assert isinstance(d["warnings"], list)
    assert isinstance(d["info"], list)
    assert isinstance(d["next_steps"], list)


def test_blocking_status_is_error():
    builder = _make_builder(env="prod")
    # Force blocking by ensuring no LLM key and no kernel URL
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HI_AGENT_KERNEL_URL"):
        os.environ.pop(k, None)
    report = build_doctor_report(builder)
    assert report.status == "error"
    assert len(report.blocking) > 0
