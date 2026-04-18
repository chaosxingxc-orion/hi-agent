import hashlib
import re
from pathlib import Path
from typing import NamedTuple


class WorkspaceKey(NamedTuple):
    tenant_id: str
    user_id: str
    session_id: str
    team_id: str = ""


def _safe_slug(value: str, max_len: int = 64) -> str:
    """Normalize an ID to a safe filesystem path component.

    Hashes values that contain path separators or null bytes to prevent
    directory traversal attacks.
    """
    if re.search(r"[/\\\x00.]", value):
        return hashlib.sha256(value.encode()).hexdigest()[:32]
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", value)
    return slug[:max_len]


class WorkspacePathHelper:
    @staticmethod
    def private(base: str | Path, key: WorkspaceKey, *parts: str) -> Path:
        """Return path scoped to (tenant, user, session)."""
        p = (
            Path(base)
            / "workspaces"
            / _safe_slug(key.tenant_id)
            / "users"
            / _safe_slug(key.user_id)
            / "sessions"
            / _safe_slug(key.session_id)
        )
        return p.joinpath(*parts) if parts else p

    @staticmethod
    def team(base: str | Path, key: WorkspaceKey, *parts: str) -> Path:
        """Return path scoped to (tenant, team). Falls back to tenant_id."""
        team = _safe_slug(key.team_id) if key.team_id else _safe_slug(key.tenant_id)
        p = Path(base) / "workspaces" / _safe_slug(key.tenant_id) / "teams" / team
        return p.joinpath(*parts) if parts else p
