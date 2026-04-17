"""Pure-function policy resolver for evolve_mode (HI-W1-D2-001)."""

from __future__ import annotations


def resolve_evolve_effective(mode: str, runtime_mode: str) -> tuple[bool, str]:
    """Resolve the effective evolve enabled flag and source label.

    Resolution table:
      on   + any        -> (True,  "explicit_on")
      off  + any        -> (False, "explicit_off")
      auto + dev-smoke  -> (True,  "auto_dev_on")
      auto + local-real -> (False, "auto_prod_off")
      auto + prod-real  -> (False, "auto_prod_off")

    Args:
        mode: Configured evolve_mode value ("on", "off", or "auto").
        runtime_mode: Current runtime mode string (e.g. "dev-smoke",
            "local-real", "prod-real").

    Returns:
        Tuple of (enabled: bool, source: str) where source describes why the
        decision was made — useful for audit logging and debugging.
    """
    if mode == "on":
        return True, "explicit_on"
    if mode == "off":
        return False, "explicit_off"
    # mode == "auto"
    if runtime_mode == "dev-smoke":
        return True, "auto_dev_on"
    return False, "auto_prod_off"
