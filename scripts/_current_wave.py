"""Single source of truth for the current development wave."""
from __future__ import annotations

import pathlib

_WAVE_FILE = pathlib.Path(__file__).parent.parent / "docs" / "current-wave.txt"


def current_wave() -> str:
    """Return the current wave string, e.g. 'Wave 11'."""
    return _WAVE_FILE.read_text(encoding="utf-8").strip()


def wave_number(wave_str: str) -> int:
    """Parse 'Wave 11' -> 11. Raises ValueError on bad format."""
    parts = wave_str.strip().split()
    if len(parts) != 2 or parts[0] != "Wave":
        raise ValueError(f"Expected 'Wave N', got: {wave_str!r}")
    return int(parts[1])


def is_expired(expiry_wave: str) -> bool:
    """Return True if expiry_wave <= current wave (i.e., deadline has passed)."""
    try:
        return wave_number(expiry_wave) <= wave_number(current_wave())
    except ValueError:
        return False  # unknown format, don't fail-close
