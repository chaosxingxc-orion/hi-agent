"""hi-agent artifacts migrate-tenant subcommand.

Assigns a tenant_id (and optionally a project_id) to legacy tenantless
artifacts stored in a durable JSONL ledger file.

Usage:
    hi-agent artifacts migrate-tenant \
        --tenant-id research-team-1 \
        --data-dir /var/hi_agent \
        --dry-run
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_data_dir(args) -> Path:
    """Resolve ledger data directory from CLI arg or HI_AGENT_DATA_DIR env."""
    data_dir_arg = getattr(args, "data_dir", None)
    if data_dir_arg:
        return Path(data_dir_arg).resolve()
    env_dir = os.environ.get("HI_AGENT_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir).resolve()
    print(
        "error: --data-dir is required (or set HI_AGENT_DATA_DIR)",
        file=sys.stderr,
    )
    sys.exit(1)


def run_migrate_tenant(args) -> None:
    """Migrate tenantless artifacts to a specified tenant_id.

    Args:
        args: Parsed CLI arguments with ``tenant_id``, ``project_id``,
              ``data_dir``, and ``dry_run`` fields.
    """
    tenant_id: str = args.tenant_id.strip()
    if not tenant_id:
        print("error: --tenant-id must be non-empty", file=sys.stderr)
        sys.exit(1)

    project_id: str = getattr(args, "project_id", None) or ""
    dry_run: bool = getattr(args, "dry_run", False)

    data_dir = _resolve_data_dir(args)
    ledger_path = data_dir / "artifacts.jsonl"

    if not ledger_path.exists():
        print(f"No ledger file found at {ledger_path} — nothing to migrate.")
        return

    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    updated_lines: list[str] = []
    update_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            updated_lines.append(line)
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            logger.warning("migrate-tenant: skipping corrupt line: %s", exc)
            updated_lines.append(line)
            continue

        existing_tenant = record.get("tenant_id", "")
        if not existing_tenant:
            record["tenant_id"] = tenant_id
            if project_id and not record.get("project_id"):
                record["project_id"] = project_id
            updated_lines.append(json.dumps(record, default=str))
            update_count += 1
        else:
            updated_lines.append(line)

    if dry_run:
        print(f"Dry run: {update_count} artifact(s) would be updated.")
        return

    if update_count == 0:
        print("No tenantless artifacts found — nothing to update.")
        return

    # Write atomically: write to .tmp then replace
    tmp_path = ledger_path.with_suffix(".jsonl.migrating")
    tmp_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    tmp_path.replace(ledger_path)
    print(f"Updated {update_count} artifact(s) with tenant_id={tenant_id!r}.")
