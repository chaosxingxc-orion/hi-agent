"""Backward-compat shim: DefaultSkillRuntimeFactory moved to hi_agent.skills.

The implementation now lives in ``hi_agent.skills.runtime_factory``.
This module re-exports it to preserve existing import paths.
"""

from __future__ import annotations

from hi_agent.skills.runtime_factory import DefaultSkillRuntimeFactory

__all__ = ["DefaultSkillRuntimeFactory"]
