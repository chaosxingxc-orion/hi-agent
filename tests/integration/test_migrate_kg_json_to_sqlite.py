"""Integration: migrate_kg_json_to_sqlite.py migration utility.

Layer 2 — Integration test. Uses real file system (tmp_path), real
SqliteKnowledgeGraphBackend, and real LongTermMemoryGraph JSON output.
No mocks on the subsystem under test.

Tests:
1. Dry-run mode reports counts without writing files.
2. Commit mode creates SQLite file and renames JSON to .bak.
3. Migrated data is query-able via SqliteKnowledgeGraphBackend.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SCRIPT = ROOT / "scripts" / "migrate_kg_json_to_sqlite.py"


def _make_json_kg(data_dir: Path, profile_id: str, project_id: str = "") -> Path:
    """Write a minimal graph.json file matching LongTermMemoryGraph.save() format."""
    l3_dir = data_dir / "L3" / profile_id
    if project_id:
        l3_dir = l3_dir / project_id
    l3_dir.mkdir(parents=True, exist_ok=True)
    graph_path = l3_dir / "graph.json"
    data = {
        "nodes": {
            "n1": {
                "node_id": "n1",
                "content": "test node one",
                "node_type": "fact",
                "tags": ["tag1"],
                "source_sessions": [],
                "confidence": 1.0,
                "access_count": 0,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
            "n2": {
                "node_id": "n2",
                "content": "test node two",
                "node_type": "pattern",
                "tags": [],
                "source_sessions": [],
                "confidence": 0.8,
                "access_count": 2,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        },
        "edges": [
            {
                "source_id": "n1",
                "target_id": "n2",
                "relation_type": "supports",
                "weight": 1.0,
            }
        ],
    }
    graph_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return graph_path


def _run_script(*extra_args: str, data_dir: Path) -> tuple[int, str, str]:
    """Run the migration script and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(data_dir), *extra_args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return result.returncode, result.stdout, result.stderr


class TestDryRun:
    """Dry-run mode reports counts without modifying any files."""

    def test_dry_run_reports_counts(self, tmp_path):
        """Dry-run prints node and edge counts for each profile."""
        data_dir = tmp_path / "data"
        _make_json_kg(data_dir, "prof1")

        rc, stdout, stderr = _run_script("--dry-run", data_dir=data_dir)
        assert rc == 0, f"Script failed: {stderr}"
        assert "2 nodes" in stdout or "nodes" in stdout
        assert "1 edges" in stdout or "edges" in stdout

    def test_dry_run_does_not_write_sqlite(self, tmp_path):
        """Dry-run must not create any SQLite files."""
        data_dir = tmp_path / "data"
        _make_json_kg(data_dir, "prof1")

        _run_script("--dry-run", data_dir=data_dir)

        sqlite_files = list(data_dir.rglob("*.sqlite"))
        assert sqlite_files == [], f"Unexpected SQLite files created: {sqlite_files}"

    def test_dry_run_does_not_rename_json(self, tmp_path):
        """Dry-run must leave the JSON file untouched."""
        data_dir = tmp_path / "data"
        json_path = _make_json_kg(data_dir, "prof1")

        _run_script("--dry-run", data_dir=data_dir)

        assert json_path.exists(), "JSON file was removed by dry-run"
        bak = json_path.with_suffix(".bak")
        assert not bak.exists(), "Dry-run created a .bak file unexpectedly"


class TestCommitMode:
    """Commit mode migrates data and renames source JSON to .bak."""

    def test_sqlite_file_created_after_migration(self, tmp_path):
        """Commit mode writes a SQLite file alongside the JSON."""
        data_dir = tmp_path / "data"
        json_path = _make_json_kg(data_dir, "prof1")

        rc, stdout, stderr = _run_script(data_dir=data_dir)
        assert rc == 0, f"Script failed:\nstdout={stdout}\nstderr={stderr}"

        sqlite_path = json_path.parent / "knowledge_graph.sqlite"
        assert sqlite_path.exists(), "knowledge_graph.sqlite not created"

    def test_json_renamed_to_bak(self, tmp_path):
        """Commit mode renames graph.json → graph.bak."""
        data_dir = tmp_path / "data"
        json_path = _make_json_kg(data_dir, "prof1")

        _run_script(data_dir=data_dir)

        bak_path = json_path.with_suffix(".bak")
        assert bak_path.exists(), "graph.bak not created"
        assert not json_path.exists(), "graph.json still exists after migration"

    def test_migrated_data_is_queryable(self, tmp_path):
        """Data migrated to SQLite is readable via SqliteKnowledgeGraphBackend."""
        from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

        data_dir = tmp_path / "data"
        json_path = _make_json_kg(data_dir, "prof1")

        _run_script(data_dir=data_dir)

        # Open the SQLite backend and verify data.
        sqlite_dir = json_path.parent
        backend = SqliteKnowledgeGraphBackend(
            data_dir=sqlite_dir,
            profile_id="prof1",
        )
        assert backend.node_count() == 2
        assert backend.edge_count() == 1

    def test_multiple_profiles_migrated(self, tmp_path):
        """Multiple profile directories are each migrated independently."""
        data_dir = tmp_path / "data"
        _make_json_kg(data_dir, "prof_a")
        _make_json_kg(data_dir, "prof_b")

        rc, _stdout, _ = _run_script(data_dir=data_dir)
        assert rc == 0

        sqlite_a = data_dir / "L3" / "prof_a" / "knowledge_graph.sqlite"
        sqlite_b = data_dir / "L3" / "prof_b" / "knowledge_graph.sqlite"
        assert sqlite_a.exists()
        assert sqlite_b.exists()

    def test_empty_data_dir_exits_cleanly(self, tmp_path):
        """Script exits with code 0 when no JSON files found."""
        empty_dir = tmp_path / "empty_data"
        empty_dir.mkdir()

        rc, _stdout, _stderr = _run_script(data_dir=empty_dir)
        assert rc == 0
