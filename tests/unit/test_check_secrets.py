"""Tests for scripts/check_secrets.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_check_secrets():
    """Load check_secrets module from scripts directory."""
    script_path = Path("scripts/check_secrets.py")
    if not script_path.exists():
        pytest.skip("scripts/check_secrets.py not found")
    spec = importlib.util.spec_from_file_location("check_secrets", script_path)
    if spec is None or spec.loader is None:
        pytest.skip("Cannot load check_secrets module")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  expiry_wave: Wave 29
    return mod


def test_empty_api_key_passes(tmp_path):
    """A config with empty api_key passes the check."""
    mod = _load_check_secrets()

    config = tmp_path / "llm_config.json"
    config.write_text(json.dumps({"api_key": "", "model": "gpt-4"}), encoding="utf-8")

    mod.findings.clear()
    mod.check_json_config(config)
    assert len(mod.findings) == 0, f"Expected no findings for empty key, got: {mod.findings}"


def test_nonempty_key_detected(tmp_path):
    """A config with a real-looking api_key is detected."""
    mod = _load_check_secrets()

    # Synthetic non-real UUID used only as a test fixture
    config = tmp_path / "llm_config.json"
    config.write_text(
        json.dumps({"api_key": "00000000-0000-0000-0000-000000000001"}), encoding="utf-8"
    )

    mod.findings.clear()
    mod.check_json_config(config)
    assert len(mod.findings) > 0, "Expected finding for non-empty api_key"


def test_nested_api_key_detected(tmp_path):
    """A nested config structure with non-empty api_key is detected."""
    mod = _load_check_secrets()

    config = tmp_path / "llm_config.json"
    data = {
        "providers": {
            "volces": {"api_key": "fake-key-for-testing-only-not-real-12345"}
        }
    }
    config.write_text(json.dumps(data), encoding="utf-8")

    mod.findings.clear()
    mod.check_json_config(config)
    assert len(mod.findings) > 0, "Expected finding for nested non-empty api_key"


def test_uuid_in_suspicious_context_detected(tmp_path):
    """UUID-like value in a 'api_key' context in a markdown file is detected."""
    mod = _load_check_secrets()

    md_file = tmp_path / "notice.md"
    md_file.write_text("api_key: 12345678-abcd-1234-abcd-123456789012\n", encoding="utf-8")

    mod.findings.clear()
    mod.check_md_file(md_file)
    assert len(mod.findings) > 0, "Expected finding for UUID in api_key context"


def test_placeholder_in_md_not_flagged(tmp_path):
    """A line with 'example' placeholder and UUID is not flagged."""
    mod = _load_check_secrets()

    md_file = tmp_path / "notice.md"
    md_file.write_text("api_key: example 12345678-abcd-1234-abcd-123456789012\n", encoding="utf-8")

    mod.findings.clear()
    mod.check_md_file(md_file)
    assert len(mod.findings) == 0, f"Expected no findings for placeholder line, got: {mod.findings}"


def test_malformed_json_does_not_crash(tmp_path):
    """Malformed JSON config is silently skipped."""
    mod = _load_check_secrets()

    config = tmp_path / "bad.json"
    config.write_text("{not valid json", encoding="utf-8")

    mod.findings.clear()
    mod.check_json_config(config)
    # Should not raise; findings may be empty
    assert isinstance(mod.findings, list)
