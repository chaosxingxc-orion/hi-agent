"""Shared test fixtures for hi-agent."""
import sys
import pathlib

# Make agent-kernel importable without installing it
_AGENT_KERNEL = pathlib.Path(__file__).parent.parent.parent / "agent-kernel"
if _AGENT_KERNEL.exists() and str(_AGENT_KERNEL) not in sys.path:
    sys.path.insert(0, str(_AGENT_KERNEL))
