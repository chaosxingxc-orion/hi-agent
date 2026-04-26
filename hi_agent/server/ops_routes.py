"""Ops HTTP route handlers: /doctor, /diagnostics, /ops/release-gate."""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.ops.diagnostics import build_doctor_report
from hi_agent.ops.release_gate import build_release_gate_report


async def handle_doctor(request: Request) -> JSONResponse:
    """GET /doctor — return structured diagnostic report."""
    server = request.app.state.agent_server
    builder = getattr(server, "_builder", None)
    if builder is None:
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder(config=getattr(server, "_config", None))
    report = build_doctor_report(builder, server=server)
    status_code = 200 if report.status == "ready" else 503
    return JSONResponse(report.to_dict(), status_code=status_code)


async def handle_release_gate(request: Request) -> JSONResponse:
    """GET /ops/release-gate — CI/CD gate check."""
    server = request.app.state.agent_server
    builder = getattr(server, "_builder", None)
    if builder is None:
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder(config=getattr(server, "_config", None))
    report = build_release_gate_report(builder)
    status_code = 200 if report.passed else 503
    return JSONResponse(report.to_dict(), status_code=status_code)


async def handle_diagnostics(request: Request) -> JSONResponse:
    """GET /diagnostics — compact self-serve runtime fingerprint.

    Designed for downstream deploy triage: one request tells an integrator
    exactly which env surfaces hi-agent actually read, whether credentials are
    present, which kernel/LLM mode is configured, and whether the lazy kernel
    adapter has been built yet (and with what result).

    Always returns 200 — this is a diagnostic dump, not a gate.
    """
    server = request.app.state.agent_server
    builder = getattr(server, "_builder", None)
    cfg = getattr(server, "_config", None)

    env = os.environ.get("HI_AGENT_ENV", "dev").lower()

    # Credential presence (no values — just booleans).
    creds = {
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "VOLCE_API_KEY": bool(os.environ.get("VOLCE_API_KEY")),
    }

    # The single env surfaces that affect runtime_mode and kernel routing.
    env_surface = {
        "HI_AGENT_ENV": os.environ.get("HI_AGENT_ENV", ""),
        "HI_AGENT_KERNEL_BASE_URL": os.environ.get("HI_AGENT_KERNEL_BASE_URL", ""),
        "HI_AGENT_LLM_MODE": os.environ.get("HI_AGENT_LLM_MODE", ""),
        "HI_AGENT_KERNEL_MODE": os.environ.get("HI_AGENT_KERNEL_MODE", ""),
        "HI_AGENT_CONFIG_FILE": os.environ.get("HI_AGENT_CONFIG_FILE", ""),
        "HI_AGENT_PROFILE": os.environ.get("HI_AGENT_PROFILE", ""),
        "HI_AGENT_ALLOW_HEURISTIC_FALLBACK": os.environ.get(
            "HI_AGENT_ALLOW_HEURISTIC_FALLBACK", ""
        ),
    }

    # Resolved config (after env + file + profile layering).
    resolved = {
        "kernel_base_url": getattr(cfg, "kernel_base_url", "") if cfg else "",
        "openai_base_url": getattr(cfg, "openai_base_url", "") if cfg else "",
        "anthropic_base_url": getattr(cfg, "anthropic_base_url", "") if cfg else "",
        "default_model": getattr(cfg, "default_model", "") if cfg else "",
        "llm_default_provider": getattr(cfg, "llm_default_provider", "") if cfg else "",
        "compat_sync_llm": getattr(cfg, "compat_sync_llm", None) if cfg else None,
    }

    # runtime_mode derivation — share the single source of truth.
    try:
        from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode

        readiness_snap = builder.readiness() if builder is not None else {}
        runtime_mode = resolve_runtime_mode(env, readiness_snap)
    except Exception as exc:  # pragma: no cover
        runtime_mode = f"unknown ({exc})"

    # Kernel adapter: lazy → report configured_mode without forcing a build.
    kernel_info: dict = {"built": False}
    if builder is not None:
        cached_kernel = getattr(builder, "_kernel", None)
        if cached_kernel is not None:
            kernel_info = {"built": True}
            if hasattr(cached_kernel, "get_health"):
                try:
                    kernel_info["health"] = cached_kernel.get_health()
                except Exception as exc:  # pragma: no cover
                    kernel_info["health_error"] = str(exc)
    _cfg_url = resolved["kernel_base_url"]
    kernel_info["configured_mode"] = (
        "http" if _cfg_url and _cfg_url.lower() != "local" else "local-fsm"
    )
    kernel_info["configured_base_url"] = _cfg_url

    return JSONResponse(
        {
            "env": env,
            "runtime_mode": runtime_mode,
            "credentials_present": creds,
            "env_surface": env_surface,
            "resolved_config": resolved,
            "kernel_adapter": kernel_info,
        }
    )
