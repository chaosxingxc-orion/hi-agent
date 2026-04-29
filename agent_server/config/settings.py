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
    return AgentServerSettings(
        host=os.environ.get("AGENT_SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("AGENT_SERVER_PORT", "8080")),
    )
