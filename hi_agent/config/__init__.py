"""Centralized configuration system for TRACE subsystems."""

from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig

__all__ = [
    "SystemBuilder",
    "TraceConfig",
]
