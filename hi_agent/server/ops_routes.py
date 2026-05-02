"""Ops HTTP route handlers: /doctor, /diagnostics, /ops/release-gate,
/ops/slo, /ops/alerts, /ops/runbook, /ops/dashboard."""

from __future__ import annotations

import logging
import os

from starlette.requests import Request
from starlette.responses import JSONResponse

from hi_agent.operator_tools.diagnostics import build_doctor_report
from hi_agent.operator_tools.release_gate import build_release_gate_report

logger = logging.getLogger(__name__)


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
    # API keys are read from config/llm_config.json, not env vars.
    from hi_agent.config.json_config_loader import get_provider_api_key

    creds = {
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "volces_api_key_configured": bool(get_provider_api_key("volces")),
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


async def handle_ops_slo(request: Request) -> JSONResponse:
    """GET /ops/slo -- return current SLO snapshot from the running SLO monitor.

    Returns the most-recent snapshot evaluated by SLOMonitor, or a static
    unavailable payload when no metrics data exists yet.  Always HTTP 200.
    """
    server = request.app.state.agent_server
    slo_monitor = getattr(server, "slo_monitor", None)
    if slo_monitor is None:
        return JSONResponse({"status": "unavailable", "reason": "slo_monitor not configured"})
    try:
        snapshot = slo_monitor.check_now()
        if snapshot is None:
            return JSONResponse({"status": "unavailable", "reason": "no run data yet"})
        return JSONResponse(
            {
                "status": "ok",
                "data": {
                    "run_success_rate": snapshot.run_success_rate,
                    "latency_p95_ms": snapshot.latency_p95_ms,
                    "success_target": snapshot.success_target,
                    "latency_target_ms": snapshot.latency_target_ms,
                    "success_target_met": snapshot.success_target_met,
                    "latency_target_met": snapshot.latency_target_met,
                },
            }
        )
    except Exception as exc:
        logger.warning("handle_ops_slo error: %s", exc)
        return JSONResponse({"status": "unavailable", "reason": str(exc)})


async def handle_ops_alerts(request: Request) -> JSONResponse:
    """GET /ops/alerts -- return current operational alert states.

    Reads live metrics from the metrics_collector to build operational signals,
    then evaluates alert rules.  Always HTTP 200.
    """
    from hi_agent.management.alerts import evaluate_operational_alerts

    server = request.app.state.agent_server
    mc = getattr(server, "metrics_collector", None)
    try:
        signals: dict = {}
        if mc is not None:
            snap = mc.snapshot()
            # Derive pressure signals from metric snapshot.
            reconcile = snap.get("reconcile_operations_total", {})
            failed_reconcile = sum(
                v
                for k, v in reconcile.items()
                if isinstance(v, (int, float)) and "failed" in k
            )
            gate_pending = snap.get("human_gate_pending_total", {})
            pending_gates = int(
                sum(v for v in gate_pending.values() if isinstance(v, (int, float)))
            )
            signals = {
                "has_temporal_risk": False,
                "has_reconcile_pressure": failed_reconcile > 0,
                "has_gate_pressure": pending_gates > 0,
            }
        alerts = evaluate_operational_alerts(signals)
        return JSONResponse({"status": "ok", "data": alerts})
    except Exception as exc:
        logger.warning("handle_ops_alerts error: %s", exc)
        return JSONResponse({"status": "unavailable", "reason": str(exc)})


async def handle_ops_runbook(request: Request) -> JSONResponse:
    """GET /ops/runbook -- return a default runbook for the current system state.

    Builds a runbook from a low-severity baseline unless query param severity
    overrides it (low/medium/high).  Always HTTP 200.
    """
    from hi_agent.management.runbook import build_incident_runbook

    severity = request.query_params.get("severity", "low")
    if severity not in {"low", "medium", "high"}:
        severity = "low"
    try:
        report = {"severity": severity, "service": "hi-agent", "recommendations": []}
        runbook = build_incident_runbook(report)
        return JSONResponse({"status": "ok", "data": runbook})
    except Exception as exc:
        logger.warning("handle_ops_runbook error: %s", exc)
        return JSONResponse({"status": "unavailable", "reason": str(exc)})


async def handle_ops_dashboard(request: Request) -> JSONResponse:
    """GET /ops/dashboard -- return aggregated operational dashboard payload.

    Combines readiness, operational signals, and temporal health into a single
    dashboard summary.  Always HTTP 200.
    """
    from hi_agent.management.operational_dashboard import build_operational_dashboard_payload

    server = request.app.state.agent_server
    try:
        builder = getattr(server, "_builder", None)
        readiness: dict = {}
        if builder is not None:
            try:
                readiness = builder.readiness()
            except Exception as _exc:
                logger.warning("handle_ops_dashboard: builder.readiness() failed: %s", _exc)
        mc = getattr(server, "metrics_collector", None)
        signals: dict = {"overall_pressure": False, "has_temporal_risk": False}
        if mc is not None:
            try:
                snap = mc.snapshot()
                reconcile = snap.get("reconcile_operations_total", {})
                failed_reconcile = sum(
                    v
                    for k, v in reconcile.items()
                    if isinstance(v, (int, float)) and "failed" in k
                )
                signals["overall_pressure"] = failed_reconcile > 0
            except Exception as _exc:
                logger.warning("handle_ops_dashboard: metrics snapshot failed: %s", _exc)
        payload = build_operational_dashboard_payload(
            readiness_report=readiness,
            operational_signals=signals,
        )
        return JSONResponse({"status": "ok", "data": payload})
    except Exception as exc:
        logger.warning("handle_ops_dashboard error: %s", exc)
        return JSONResponse({"status": "unavailable", "reason": str(exc)})
