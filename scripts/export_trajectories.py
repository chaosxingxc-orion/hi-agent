"""CLI tool: export agent run sessions to JSONL for RL training.

Usage
-----
    python scripts/export_trajectories.py \\
        --sessions-dir path/to/sessions \\
        --output path/to/output.jsonl \\
        [--min-quality 0.7] \\
        [--min-turns 3] \\
        [--max-turns 500] \\
        [--require-reward]

The tool scans *sessions-dir* for ``*.json`` files, treats each as a raw
session / checkpoint dict, applies the specified filter, and writes passing
records to *output* as JSONL (one record per line).

A summary is printed to stdout on completion.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is importable even when the script is invoked
# directly from the command line (without an editable install).
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from hi_agent.observability.trajectory_exporter import (
    ExportStats,
    TrajectoryExporter,
    TrajectoryFilter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
_logger = logging.getLogger("export_trajectories")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_trajectories",
        description="Export hi-agent run sessions to JSONL for RL training.",
    )
    parser.add_argument(
        "--sessions-dir",
        required=True,
        metavar="PATH",
        help="Directory containing *.json session / checkpoint files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="PATH",
        help="Output JSONL file path (created or overwritten).",
    )
    parser.add_argument(
        "--min-quality",
        type=float,
        default=0.0,
        metavar="FLOAT",
        help=(
            "Minimum quality_score required (0.0-1.0). "
            "Default: 0.0 (no filter)."
        ),
    )
    parser.add_argument(
        "--min-turns",
        type=int,
        default=1,
        metavar="INT",
        help="Minimum number of conversation turns. Default: 1.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=1000,
        metavar="INT",
        help="Maximum number of conversation turns. Default: 1000.",
    )
    parser.add_argument(
        "--require-reward",
        action="store_true",
        default=False,
        help="Reject sessions that have no reward annotation.",
    )
    parser.add_argument(
        "--allowed-statuses",
        nargs="*",
        default=["completed"],
        metavar="STATUS",
        help=(
            "Whitelist of run statuses. Default: completed. "
            "Pass multiple values separated by spaces."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Session loading
# ---------------------------------------------------------------------------


def _load_sessions(sessions_dir: str) -> list[dict]:
    """Load all *.json files in sessions_dir as session dicts.

    Files that cannot be parsed as JSON are skipped with a warning.

    Args:
        sessions_dir: Directory path to scan.

    Returns:
        List of raw session dicts.
    """
    dir_path = Path(sessions_dir)
    if not dir_path.is_dir():
        _logger.error("sessions-dir does not exist or is not a directory: %s", sessions_dir)
        return []

    sessions: list[dict] = []
    json_files = sorted(dir_path.glob("*.json"))
    _logger.info("Found %d .json file(s) in %s", len(json_files), sessions_dir)

    for json_file in json_files:
        try:
            with json_file.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                sessions.append(data)
            elif isinstance(data, list):
                # Support files that contain a list of session dicts
                for item in data:
                    if isinstance(item, dict):
                        sessions.append(item)
            else:
                _logger.warning("Skipping %s — unexpected JSON type %s", json_file.name, type(data))
        except json.JSONDecodeError as exc:
            _logger.warning("Skipping %s — JSON parse error: %s", json_file.name, exc)
        except OSError as exc:
            _logger.warning("Skipping %s — IO error: %s", json_file.name, exc)

    return sessions


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------


def _print_stats(stats: ExportStats) -> None:
    """Print a human-readable export summary to stdout."""
    print()
    print("=" * 50)
    print("  Export Summary")
    print("=" * 50)
    print(f"  Total sessions scanned : {stats.total_sessions}")
    print(f"  Exported               : {stats.exported}")
    print(f"  Filtered out           : {stats.filtered_out}")
    print(f"  Errors                 : {stats.errors}")
    print(f"  Output file            : {stats.output_path}")
    print("=" * 50)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the export pipeline.

    Args:
        argv: Argument list (defaults to sys.argv).

    Returns:
        Exit code (0 = success, non-zero = error).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Build filter
    tfilter = TrajectoryFilter(
        min_quality=args.min_quality,
        min_turns=args.min_turns,
        max_turns=args.max_turns,
        require_reward=args.require_reward,
        allowed_statuses=args.allowed_statuses,
    )

    # Load sessions
    sessions = _load_sessions(args.sessions_dir)
    if not sessions:
        _logger.warning("No sessions found. Nothing to export.")
        stats = ExportStats(
            total_sessions=0,
            output_path=args.output,
        )
        _print_stats(stats)
        return 0

    # Export
    exporter = TrajectoryExporter(filter=tfilter)
    _logger.info(
        "Exporting %d session(s) → %s (min_quality=%.2f, min_turns=%d)",
        len(sessions),
        args.output,
        args.min_quality,
        args.min_turns,
    )
    stats = exporter.export_batch(sessions, args.output)

    # Report
    _print_stats(stats)

    if stats.errors > 0:
        _logger.warning("%d session(s) encountered errors during parsing.", stats.errors)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
