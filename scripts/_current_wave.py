"""Backward-compat shim for the wave helper.

The canonical implementation lives in scripts/_governance/wave.py.
This module re-exports the historical API so existing callers keep working.
New code should import from scripts._governance.wave directly.
"""
from __future__ import annotations

from _governance.wave import (
    current_wave,
    is_expired,
)
from _governance.wave import (
    parse_wave as _parse_wave,
)


def wave_number(wave_str: str) -> int:
    """Parse 'Wave 11' -> 11. Raises ValueError on bad format.

    Preserved for backward compatibility; new code should use
    scripts._governance.wave.parse_wave directly.
    """
    return _parse_wave(wave_str)


__all__ = ["current_wave", "is_expired", "wave_number"]
