"""Unit tests verifying multistatus (exit 0/1/2) behaviour for gate scripts.

Tests cover:
  - check_conftest_fallback_scope.py: exit 2 when conftest missing, 0 when clean, 1 when violation.
  - check_sqlite_pragma.py: exit 2 when source files absent, 0 when WAL present, 1 when missing.
  - check_allowlist_discipline.py: exit 2 when allowlists.yaml absent, 0 when clean.
  - check_secrets.py: exit 0 when no findings, 1 when findings present.
"""
from __future__ import annotations

import importlib.util
import json
import textwrap
import types
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"


def _load_script(name: str) -> types.ModuleType:
    """Load a script module by filename without executing __main__."""
    path = SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec and spec.loader, f"Cannot load {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # expiry_wave: permanent
    return mod


# ---------------------------------------------------------------------------
# check_conftest_fallback_scope
# ---------------------------------------------------------------------------

class TestConftestFallbackMultistatus:
    """Tests for check_conftest_fallback_scope.py multistatus."""

    def test_exit_2_when_conftest_missing(self, tmp_path: Path, capsys) -> None:
        """Exit 2 (not_applicable) when tests/conftest.py does not exist."""
        mod = _load_script("check_conftest_fallback_scope.py")
        fake_root = tmp_path
        (fake_root / "tests").mkdir()
        # conftest.py intentionally absent

        with patch.object(mod, "CONFTEST", fake_root / "tests" / "conftest.py"):
            result = mod.main([])

        assert result == 2, f"expected exit 2, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "not_applicable"

    def test_exit_0_when_clean(self, tmp_path: Path, capsys) -> None:
        """Exit 0 (pass) when conftest.py has no unconditional HEURISTIC_FALLBACK."""
        mod = _load_script("check_conftest_fallback_scope.py")
        conftest = tmp_path / "conftest.py"
        conftest.write_text(
            textwrap.dedent("""\
                import pytest

                @pytest.fixture(autouse=True)
                def setup():
                    if some_condition:
                        os.environ['HI_AGENT_HEURISTIC_FALLBACK'] = '1'
            """),
            encoding="utf-8",
        )
        with patch.object(mod, "CONFTEST", conftest):
            result = mod.main([])

        assert result == 0, f"expected exit 0, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "pass"

    def test_exit_1_when_violation(self, tmp_path: Path, capsys) -> None:
        """Exit 1 (fail) when conftest.py sets HEURISTIC_FALLBACK unconditionally."""
        mod = _load_script("check_conftest_fallback_scope.py")
        conftest = tmp_path / "conftest.py"
        conftest.write_text(
            textwrap.dedent("""\
                import os
                os.environ['HI_AGENT_HEURISTIC_FALLBACK'] = '1'
            """),
            encoding="utf-8",
        )
        with patch.object(mod, "CONFTEST", conftest):
            result = mod.main([])

        assert result == 1, f"expected exit 1, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "fail"
        assert data["violations"]


# ---------------------------------------------------------------------------
# check_sqlite_pragma
# ---------------------------------------------------------------------------

class TestSqlitePragmaMultistatus:
    """Tests for check_sqlite_pragma.py multistatus."""

    def test_exit_2_when_source_files_absent(self, tmp_path: Path, capsys) -> None:
        """Exit 2 (not_applicable) when all checked source files are absent."""
        mod = _load_script("check_sqlite_pragma.py")
        # Patch ROOT to a temp dir where no source files exist.
        with patch.object(mod, "ROOT", tmp_path):
            result = mod.main([])

        assert result == 2, f"expected exit 2, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "not_applicable"

    def test_exit_0_when_wal_present(self, tmp_path: Path, capsys) -> None:
        """Exit 0 (pass) when all source files contain WAL pragma."""
        mod = _load_script("check_sqlite_pragma.py")
        hi_agent_server = tmp_path / "hi_agent" / "server"
        hi_agent_server.mkdir(parents=True)
        for fname in ["event_store.py", "run_store.py"]:
            (hi_agent_server / fname).write_text(
                "PRAGMA journal_mode=WAL;\n", encoding="utf-8"
            )
        with patch.object(mod, "ROOT", tmp_path):
            result = mod.main([])

        assert result == 0, f"expected exit 0, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "pass"

    def test_exit_1_when_wal_missing(self, tmp_path: Path, capsys) -> None:
        """Exit 1 (fail) when WAL pragma is absent from a source file."""
        mod = _load_script("check_sqlite_pragma.py")
        hi_agent_server = tmp_path / "hi_agent" / "server"
        hi_agent_server.mkdir(parents=True)
        for fname in ["event_store.py", "run_store.py"]:
            # Content must NOT contain the string "WAL" to trigger the fail path.
            (hi_agent_server / fname).write_text(
                "# journal mode not configured\n", encoding="utf-8"
            )
        with patch.object(mod, "ROOT", tmp_path):
            result = mod.main([])

        assert result == 1, f"expected exit 1, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "fail"
        assert data["issues"]


# ---------------------------------------------------------------------------
# check_allowlist_discipline
# ---------------------------------------------------------------------------

class TestAllowlistDisciplineMultistatus:
    """Tests for check_allowlist_discipline.py multistatus."""

    def test_exit_2_when_allowlists_yaml_absent(self, tmp_path: Path, capsys) -> None:
        """Exit 2 (not_applicable) when allowlists.yaml does not exist."""
        mod = _load_script("check_allowlist_discipline.py")
        fake_yaml = tmp_path / "docs" / "governance" / "allowlists.yaml"
        with patch.object(mod, "ALLOWLISTS_FILE", fake_yaml):
            result = mod.main(["--json"])

        assert result == 2, f"expected exit 2, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "not_applicable"

    def test_exit_0_when_clean_allowlist(self, tmp_path: Path, capsys) -> None:
        """Exit 0 (pass) when allowlists.yaml is valid with no expired entries."""
        mod = _load_script("check_allowlist_discipline.py")
        gov_dir = tmp_path / "docs" / "governance"
        gov_dir.mkdir(parents=True)
        yaml_path = gov_dir / "allowlists.yaml"
        # Write a minimal valid allowlist.yaml with one entry far in the future.
        yaml_path.write_text(
            textwrap.dedent("""\
                current_wave: 1
                entries:
                  - allowlist: test_allowlist
                    entry: some_test_entry
                    owner: test_owner
                    risk: low
                    reason: test reason
                    expiry_wave: 99
                    replacement_test: tests/unit/test_example.py::test_foo
                    added_at: "W1"
            """),
            encoding="utf-8",
        )
        with patch.object(mod, "ALLOWLISTS_FILE", yaml_path):
            result = mod.main(["--json"])

        assert result == 0, f"expected exit 0, got {result}"
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["status"] == "pass"
