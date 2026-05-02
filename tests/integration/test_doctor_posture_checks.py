"""Integration tests for posture-aware doctor checks (DX-3).

Layer 2 (Integration): real components wired together.
No MagicMock on the subsystem under test.
"""

from __future__ import annotations

from hi_agent.operator_tools.diagnostics import build_doctor_report


class _MinimalBuilder:
    """Minimal stub builder — provides no subsystems except env var reads.

    Legitimate stub: the diagnostics subsystem under test reads env vars
    directly; the builder is only used for optional subsystem introspection
    that returns None/empty gracefully.
    """


def test_doctor_posture_research_without_data_dir_is_blocking(monkeypatch) -> None:
    """Under research posture, missing HI_AGENT_DATA_DIR produces a blocking check."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)

    report = build_doctor_report(_MinimalBuilder())

    blocking_codes = {issue.code for issue in report.blocking}
    assert "posture.data_dir_missing" in blocking_codes, (
        f"Expected 'posture.data_dir_missing' in blocking codes, got: {blocking_codes}"
    )


def test_doctor_posture_dev_data_dir_not_blocking(monkeypatch) -> None:
    """Under dev posture, missing HI_AGENT_DATA_DIR is NOT blocking."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "dev")
    monkeypatch.delenv("HI_AGENT_DATA_DIR", raising=False)

    report = build_doctor_report(_MinimalBuilder())

    blocking_codes = {issue.code for issue in report.blocking}
    assert "posture.data_dir_missing" not in blocking_codes


def test_doctor_posture_research_with_data_dir_no_blocking_on_data_dir(
    monkeypatch, tmp_path
) -> None:
    """Under research posture with HI_AGENT_DATA_DIR set, no data_dir blocking check."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "research")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))

    report = build_doctor_report(_MinimalBuilder())

    blocking_codes = {issue.code for issue in report.blocking}
    assert "posture.data_dir_missing" not in blocking_codes


def test_doctor_posture_invalid_is_blocking(monkeypatch) -> None:
    """An invalid HI_AGENT_POSTURE value produces a blocking check."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "invalid_value")

    report = build_doctor_report(_MinimalBuilder())

    blocking_codes = {issue.code for issue in report.blocking}
    assert "posture.invalid" in blocking_codes


def test_doctor_posture_not_set_produces_info(monkeypatch) -> None:
    """When HI_AGENT_POSTURE is not set, an info entry notes the default."""
    monkeypatch.delenv("HI_AGENT_POSTURE", raising=False)

    report = build_doctor_report(_MinimalBuilder())

    info_codes = {issue.code for issue in report.info}
    assert "posture.not_set" in info_codes


def test_doctor_posture_prod_warns_on_project_id_not_enforced(monkeypatch, tmp_path) -> None:
    """Under prod posture, missing HI_AGENT_PROJECT_ID_REQUIRED produces a warning."""
    monkeypatch.setenv("HI_AGENT_POSTURE", "prod")
    monkeypatch.setenv("HI_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HI_AGENT_PROJECT_ID_REQUIRED", raising=False)

    report = build_doctor_report(_MinimalBuilder())

    warning_codes = {issue.code for issue in report.warnings}
    assert "posture.project_id_not_enforced" in warning_codes
