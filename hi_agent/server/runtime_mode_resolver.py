"""Single source of truth for runtime_mode — HI-W1-D3-001."""
from typing import Literal


def resolve_runtime_mode(
    env: str,
    readiness: dict,
) -> Literal["dev-smoke", "local-real", "prod-real"]:
    """Single source of truth for runtime_mode.

    Consumers: RunResult.execution_provenance (D3, wired), /manifest (D4, pending),
    /ready (D4, pending). All three must converge on this function — never compute
    runtime_mode independently once wired.

    Args:
        env: Environment string, e.g. "prod", "dev", "local".
        readiness: Dict with optional keys "llm_mode" and "kernel_mode".

    Returns:
        "prod-real"   — when env == "prod"
        "local-real"  — when llm_mode=="real" AND kernel_mode=="http"
        "dev-smoke"   — all other cases
    """
    if env == "prod":
        return "prod-real"
    if (
        readiness.get("llm_mode") == "real"
        and readiness.get("kernel_mode") == "http"
    ):
        return "local-real"
    return "dev-smoke"
