"""Single source of truth for "what wave are we in".

Source of truth: docs/current-wave.txt (authoritative; bumped when a wave starts).
Other places that name the wave (allowlists.yaml#current_wave, manifest.wave,
closure notice "Wave: N" line) MUST agree with this file. Drift is detected by
validate_wave_consistency.

The legacy scripts/_current_wave.py is kept as a thin re-export shim so older
imports continue to work.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WAVE_FILE = _REPO_ROOT / "docs" / "current-wave.txt"

_WAVE_LABEL_RE = re.compile(r"^\s*(?:[Ww]ave\s+)?(\d+)\s*$")


def parse_wave(label: object) -> int:
    """Parse "Wave N", "N", or int N into wave-number int. Negative or garbage → ValueError."""
    if isinstance(label, bool):  # bool is a subclass of int — exclude
        raise ValueError(f"Wave label cannot be bool: {label!r}")
    if isinstance(label, int):
        if label < 0:
            raise ValueError(f"Wave number must be non-negative, got {label}")
        return label
    if not isinstance(label, str):
        raise ValueError(f"Wave label must be str or int, got {type(label).__name__}")
    text = label.strip()
    if not text:
        raise ValueError("Empty wave label")
    m = _WAVE_LABEL_RE.match(text)
    if not m:
        raise ValueError(f"Cannot parse wave label: {label!r}")
    n = int(m.group(1))
    if n < 0:
        raise ValueError(f"Wave number must be non-negative, got {n}")
    return n


def format_wave(n: int) -> str:
    """Format int N as 'Wave N'. Negative → ValueError."""
    if n < 0:
        raise ValueError(f"Wave number must be non-negative, got {n}")
    return f"Wave {n}"


def current_wave() -> str:
    """Return the current wave label as written in docs/current-wave.txt.

    Falls back to 'unknown' if the file cannot be read.
    """
    try:
        return _WAVE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def current_wave_number() -> int:
    """Return the current wave as int, or 0 if unparseable."""
    try:
        return parse_wave(current_wave())
    except ValueError:
        return 0


def is_expired(expiry_wave: object) -> bool:
    """Return True if expiry_wave <= current wave number.

    Garbage input returns False (preserves _current_wave.is_expired semantics).
    """
    try:
        return parse_wave(expiry_wave) <= current_wave_number()
    except ValueError:
        return False


def validate_wave_consistency(**sources: object) -> list[str]:
    """Check all named wave sources resolve to the same int.

    Returns list of inconsistency messages (empty if all agree). Each kwarg name
    becomes a source label in any error message.

    None values are reported as 'missing'. Unparseable values are reported as
    parse errors. Mismatched parsed values are reported as drift.
    """
    msgs: list[str] = []
    parsed: dict[str, int] = {}

    for name, raw in sources.items():
        if raw is None:
            msgs.append(f"{name}: source missing (None)")
            continue
        try:
            parsed[name] = parse_wave(raw)
        except ValueError as exc:
            msgs.append(f"{name}: cannot parse {raw!r} ({exc})")

    if len(parsed) >= 2:
        values = set(parsed.values())
        if len(values) > 1:
            grouping = ", ".join(f"{n}={v}" for n, v in sorted(parsed.items()))
            msgs.append(f"wave drift: {grouping}")

    return msgs
