#!/usr/bin/env python3
"""Migrate KG data from JSON backend to SQLite backend.

Finds all LongTermMemoryGraph JSON files under the data directory,
reports node/edge counts, and optionally migrates them to the
SqliteKnowledgeGraphBackend.

Usage:
  python scripts/migrate_kg_json_to_sqlite.py --dry-run   # report counts only
  python scripts/migrate_kg_json_to_sqlite.py              # commit mode: migrate + rename .bak

In commit mode, the source JSON is renamed to ``<name>.bak`` after a
successful migration. The SQLite file is written alongside the JSON file
inside the same L3/<profile_id>[/<project_id>]/ directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _find_graph_json_files(data_dir: Path) -> list[Path]:
    """Return all graph.json files under data_dir's L3 hierarchy."""
    return sorted(data_dir.rglob("graph.json"))


def _parse_profile_project(json_path: Path, data_dir: Path) -> tuple[str, str]:
    """Derive (profile_id, project_id) from json_path relative to data_dir."""
    try:
        rel = json_path.parent.relative_to(data_dir / "L3")
        parts = rel.parts
        profile_id = parts[0] if parts else "unknown"
        project_id = parts[1] if len(parts) > 1 else ""
    except ValueError:
        profile_id = json_path.parent.name
        project_id = ""
    return profile_id, project_id


def _count_records(json_path: Path) -> tuple[int, int]:
    """Return (node_count, edge_count) from a graph JSON file."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        nodes = len(data.get("nodes", {}))
        edges = len(data.get("edges", []))
        return nodes, edges
    except (json.JSONDecodeError, OSError):
        return 0, 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate KG data from JSON backend to SQLite backend."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts only; do not write any files.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(ROOT / "data"),
        help="Root data directory (default: <repo-root>/data).",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"[migrate] data-dir does not exist: {data_dir}")
        sys.exit(0)

    json_files = _find_graph_json_files(data_dir)
    if not json_files:
        print(f"[migrate] No graph.json files found under {data_dir}")
        sys.exit(0)

    total_nodes = 0
    total_edges = 0
    total_migrated = 0

    for json_path in json_files:
        profile_id, project_id = _parse_profile_project(json_path, data_dir)
        nodes, edges = _count_records(json_path)
        total_nodes += nodes
        total_edges += edges

        if args.dry_run:
            print(
                f"[dry-run] {json_path.relative_to(data_dir)}: "
                f"{nodes} nodes, {edges} edges  "
                f"(profile={profile_id!r}, project={project_id!r})"
            )
        else:
            from hi_agent.memory.sqlite_kg_backend import SqliteKnowledgeGraphBackend

            backend = SqliteKnowledgeGraphBackend(
                data_dir=json_path.parent,
                profile_id=profile_id,
                project_id=project_id,
            )
            migrated = backend.migrate_from_json(json_path)
            total_migrated += migrated

            # Rename source JSON to .bak (keeps it safe; does not delete).
            bak_path = json_path.with_suffix(".bak")
            json_path.rename(bak_path)

            print(
                f"[migrate] {json_path.relative_to(data_dir)}: "
                f"migrated {migrated} records → "
                f"{json_path.parent / 'knowledge_graph.sqlite'}; "
                f"original backed up as {bak_path.name}"
            )

    if args.dry_run:
        print(
            f"\n[dry-run] Total: {total_nodes} nodes, {total_edges} edges across "
            f"{len(json_files)} file(s). No files written."
        )
    else:
        print(
            f"\n[migrate] Done. Migrated {total_migrated} records across "
            f"{len(json_files)} file(s)."
        )


if __name__ == "__main__":
    main()
