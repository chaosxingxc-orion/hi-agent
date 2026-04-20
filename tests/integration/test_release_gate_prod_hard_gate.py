"""Tests for release gate prod-real hard gate (HI-W12-002)."""

import datetime
import json
from pathlib import Path

from hi_agent.ops.release_gate import ProdE2EResult, check_prod_e2e_recent


def _write_episode(directory: Path, filename: str, runtime_mode: str, age_hours: float) -> None:
    """Write a synthetic episode JSON file to the given directory."""
    ts = datetime.datetime.utcnow() - datetime.timedelta(hours=age_hours)
    episode = {
        "run_id": f"run-{filename}",
        "runtime_mode": runtime_mode,
        "completed_at": ts.isoformat() + "Z",
        "goal": "smoke test",
    }
    (directory / filename).write_text(json.dumps(episode), encoding="utf-8")


class TestProdE2ERecentGate:
    def test_gate_passes_when_recent_prod_run_exists(self, tmp_path):
        """Gate passes when episodic store has a prod-real run < 24h ago."""
        _write_episode(tmp_path, "ep-001.json", "prod-real", age_hours=2.0)

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        assert result.passed is True
        assert "prod-real" in result.reason or "2." in result.reason
        assert result.details["prod_run_count"] == 1
        assert result.details["age_hours"] < 24

    def test_gate_fails_when_no_prod_run_exists(self, tmp_path):
        """Gate fails when no episodic entries exist."""
        # Empty directory — no JSON files at all
        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        assert result.passed is False
        assert "no episodes" in result.reason

    def test_gate_fails_when_only_non_prod_runs_exist(self, tmp_path):
        """Gate fails when episodic store has entries but none are prod-real."""
        _write_episode(tmp_path, "ep-dev.json", "dev-smoke", age_hours=1.0)
        _write_episode(tmp_path, "ep-local.json", "local-real", age_hours=3.0)

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        assert result.passed is False
        assert "no prod-real" in result.reason
        assert result.details["total_episodes"] == 2

    def test_gate_fails_when_prod_run_too_old(self, tmp_path):
        """Gate fails when latest prod run is > 24h old."""
        _write_episode(tmp_path, "ep-old.json", "prod-real", age_hours=30.0)

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        assert result.passed is False
        assert "30." in result.reason or "max allowed" in result.reason
        assert result.details["age_hours"] > 24
        assert result.details["max_age_hours"] == 24

    def test_gate_passes_with_custom_max_age(self, tmp_path):
        """Gate respects custom max_age_hours parameter."""
        # 10h old run — fails 8h window, passes 12h window
        _write_episode(tmp_path, "ep-recent.json", "prod-real", age_hours=10.0)

        result_fail = check_prod_e2e_recent(max_age_hours=8, episodic_dir=str(tmp_path))
        result_pass = check_prod_e2e_recent(max_age_hours=12, episodic_dir=str(tmp_path))

        assert result_fail.passed is False
        assert result_fail.details["max_age_hours"] == 8

        assert result_pass.passed is True
        assert result_pass.details["max_age_hours"] == 12

    def test_gate_result_has_required_fields(self, tmp_path):
        """ProdE2EResult has passed, reason, details fields."""
        _write_episode(tmp_path, "ep.json", "prod-real", age_hours=1.0)

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        assert isinstance(result, ProdE2EResult)
        assert hasattr(result, "passed")
        assert hasattr(result, "reason")
        assert hasattr(result, "details")
        assert isinstance(result.passed, bool)
        assert isinstance(result.reason, str)
        assert isinstance(result.details, dict)

    def test_gate_fails_when_episodic_dir_missing(self, tmp_path):
        """Gate fails clearly when episodic directory does not exist."""
        nonexistent = str(tmp_path / "no_such_dir")

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=nonexistent)

        assert result.passed is False
        assert "episodic store not found" in result.reason

    def test_gate_picks_most_recent_prod_run(self, tmp_path):
        """Gate uses the most recent prod-real run to evaluate age."""
        # Old prod run (40h) + fresh prod run (1h) — gate should pass
        _write_episode(tmp_path, "ep-old.json", "prod-real", age_hours=40.0)
        _write_episode(tmp_path, "ep-new.json", "prod-real", age_hours=1.0)

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        assert result.passed is True
        assert result.details["prod_run_count"] == 2
        assert result.details["age_hours"] < 2  # the 1h-old run was selected

    def test_gate_uses_execution_provenance_runtime_mode(self, tmp_path):
        """Gate recognises runtime_mode nested under execution_provenance."""
        ts = datetime.datetime.utcnow() - datetime.timedelta(hours=0.5)
        episode = {
            "run_id": "run-nested",
            "execution_provenance": {"runtime_mode": "prod-real"},
            "completed_at": ts.isoformat() + "Z",
        }
        (tmp_path / "ep-nested.json").write_text(json.dumps(episode), encoding="utf-8")

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        assert result.passed is True

    def test_gate_skips_malformed_episode_files(self, tmp_path):
        """Gate tolerates malformed JSON without crashing."""
        (tmp_path / "bad.json").write_text("{invalid json!!", encoding="utf-8")
        _write_episode(tmp_path, "good.json", "prod-real", age_hours=1.0)

        result = check_prod_e2e_recent(max_age_hours=24, episodic_dir=str(tmp_path))

        # Good file was still found; bad file was silently skipped
        assert result.passed is True
