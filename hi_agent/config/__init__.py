"""Centralized configuration system for TRACE subsystems."""

from hi_agent.config.trace_config import TraceConfig
from hi_agent.config.builder import SystemBuilder

__all__ = [
    "SystemBuilder",
    "TraceConfig",
]
