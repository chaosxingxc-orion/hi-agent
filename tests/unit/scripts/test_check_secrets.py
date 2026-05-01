"""Unit tests for check_secrets.py UUID detection in docs/releases JSON."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_secrets.py"


def _load_module() -> object:
    if not _SCRIPT_PATH.exists():
        pytest.skip("check_secrets.py not found")
    spec = importlib.util.spec_from_file_location("check_secrets", _SCRIPT_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # expiry_wave: Wave 29
    return mod


# ── importability ──────────────────────────────────────────────────────────────

def test_script_is_importable() -> None:
    _load_module()


def test_script_exposes_main() -> None:
    mod = _load_module()
    assert callable(getattr(mod, "main", None))


def test_check_releases_file_exists() -> None:
    mod = _load_module()
    assert callable(getattr(mod, "check_releases_file", None)), (
        "check_secrets.py must expose check_releases_file()"
    )


# ── UUID-in-secret-context detection ──────────────────────────────────────────

def test_uuid_in_api_key_context_flagged(tmp_path: Path) -> None:
    """'Rotate Volces API key <uuid>' in a releases JSON is flagged."""
    mod = _load_module()
    check_fn = getattr(mod, "check_releases_file")
    f = tmp_path / "signoff.json"
    f.write_text(
        json.dumps({"reminder": "Rotate Volces API key f103e564-61c5-462c-9d4a-95ec035c56f0 NOW"}),
        encoding="utf-8",
    )
    getattr(mod, "findings").clear()
    check_fn(f)
    findings = getattr(mod, "findings")
    assert any(item["kind"] == "uuid_in_secret_context" for item in findings), (
        "UUID adjacent to 'API key' must be flagged"
    )


def test_volces_provider_uuid_flagged(tmp_path: Path) -> None:
    """UUID alongside 'volces' keyword is flagged."""
    mod = _load_module()
    check_fn = getattr(mod, "check_releases_file")
    f = tmp_path / "evidence.json"
    f.write_text(
        '{"note": "volces provider key f103e564-61c5-462c-9d4a-95ec035c56f0"}',
        encoding="utf-8",
    )
    getattr(mod, "findings").clear()
    check_fn(f)
    assert any(item["kind"] == "uuid_in_secret_context" for item in getattr(mod, "findings"))


def test_run_id_uuid_not_flagged(tmp_path: Path) -> None:
    """UUID in a run_id field (no secret-adjacent keyword) is NOT flagged."""
    mod = _load_module()
    check_fn = getattr(mod, "check_releases_file")
    f = tmp_path / "run_evidence.json"
    f.write_text(
        json.dumps({"run_id": "f103e564-61c5-462c-9d4a-95ec035c56f0"}),
        encoding="utf-8",
    )
    getattr(mod, "findings").clear()
    check_fn(f)
    assert not getattr(mod, "findings"), "run_id UUID must not be flagged"


def test_redacted_placeholder_not_flagged(tmp_path: Path) -> None:
    """After redaction, <rotated-and-redacted> placeholder produces no findings."""
    mod = _load_module()
    check_fn = getattr(mod, "check_releases_file")
    f = tmp_path / "signoff.json"
    f.write_text(
        json.dumps({"reminder": "Rotate Volces API key <rotated-and-redacted> NOW"}),
        encoding="utf-8",
    )
    getattr(mod, "findings").clear()
    check_fn(f)
    assert not getattr(mod, "findings"), "Redacted placeholder must not trigger findings"


def test_sha_not_uuid_not_flagged(tmp_path: Path) -> None:
    """A 40-char hex SHA (not UUID format) is not flagged even with key context."""
    mod = _load_module()
    check_fn = getattr(mod, "check_releases_file")
    f = tmp_path / "manifest.json"
    f.write_text(
        '{"secret_head": "d4acba2fd6cdf7ff69a82ac30cb7b021e802c704"}',
        encoding="utf-8",
    )
    getattr(mod, "findings").clear()
    check_fn(f)
    assert not getattr(mod, "findings"), "40-char SHA is not UUID format and must not be flagged"


def test_wave27_signoff_clean_after_redaction() -> None:
    """The actual wave27-signoff.json must pass after the W28 redaction."""
    mod = _load_module()
    check_fn = getattr(mod, "check_releases_file")
    signoff = REPO_ROOT / "docs" / "releases" / "wave27-signoff.json"
    if not signoff.exists():
        pytest.skip("wave27-signoff.json not found")
    getattr(mod, "findings").clear()
    check_fn(signoff)
    assert not getattr(mod, "findings"), (
        "wave27-signoff.json must have no UUID findings after W28 redaction"
    )
