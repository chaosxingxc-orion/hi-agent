from unittest.mock import MagicMock
from hi_agent.ops.release_gate import build_release_gate_report, GateResult, ReleaseGateReport


def _make_builder(env="dev"):
    builder = MagicMock()
    builder._env = env
    config = MagicMock()
    config.evolve_mode = "auto"
    builder._config = config
    builder.config = config
    builder._mcp_status = {}
    builder._skill_loader = None
    builder._readiness_snapshot = {"ready": True}
    registry = MagicMock()
    registry._handlers = {"plan": MagicMock()}
    builder._capability_registry = registry
    return builder


def test_report_has_six_gates():
    report = build_release_gate_report(_make_builder())
    assert len(report.gates) == 6


def test_prod_e2e_always_skipped():
    report = build_release_gate_report(_make_builder())
    prod_e2e = next(g for g in report.gates if g.name == "prod_e2e_recent")
    assert prod_e2e.status == "skipped"


def test_runtime_mode_always_info():
    report = build_release_gate_report(_make_builder())
    rt = next(g for g in report.gates if g.name == "current_runtime_mode")
    assert rt.status == "info"


def test_pass_true_when_no_failures():
    report = build_release_gate_report(_make_builder())
    # info + skipped do not block pass
    assert report.passed is True


def test_to_dict_shape():
    report = build_release_gate_report(_make_builder())
    d = report.to_dict()
    assert set(d.keys()) == {"pass", "gates", "pass_gates", "skipped_gates", "failed_gates", "last_checked_at"}
    assert isinstance(d["pass"], bool)
    assert isinstance(d["gates"], list)


def test_failed_gate_makes_pass_false():
    report = ReleaseGateReport(gates=[
        GateResult("readiness", "pass", "ready"),
        GateResult("doctor", "fail", "blocking: x"),
    ])
    assert report.passed is False
    assert report.failed_gates == 1


def test_skipped_gate_does_not_block_pass():
    report = ReleaseGateReport(gates=[
        GateResult("readiness", "pass", "ready"),
        GateResult("prod_e2e_recent", "skipped", "no nightly yet"),
    ])
    assert report.passed is True
