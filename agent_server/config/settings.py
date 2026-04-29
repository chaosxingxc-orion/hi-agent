"""Runtime settings for agent_server."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentServerSettings:
    """Runtime settings resolved from environment."""

    host: str = "0.0.0.0"
    port: int = 8080
    api_version: str = "v1"


def load_settings() -> AgentServerSettings:
    """Load settings from environment variables."""
    port_str = os.environ.get("AGENT_SERVER_PORT", "8080")
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(f"AGENT_SERVER_PORT must be an integer, got: {port_str!r}") from exc
    if not (1 <= port <= 65535):
        raise ValueError(f"AGENT_SERVER_PORT must be in [1, 65535], got: {port}")
    return AgentServerSettings(
        host=os.environ.get("AGENT_SERVER_HOST", "0.0.0.0"),
        port=port,
        api_version=os.environ.get("AGENT_SERVER_API_VERSION", "v1"),
    )
