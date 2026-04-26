"""HTTP route handler for GET /manifest.

Extracted from hi_agent/server/app.py (H1 Hardening Track 3).

Enhancements over the inline version:
- version pulled from importlib.metadata.version("hi-agent"), fallback "dev"
- endpoints derived dynamically from request.app.routes (no hardcoded list)
- capabilities include a `parameters` JSON schema per capability
- /manifest.profiles[] includes the hi_agent_global profile when registered
- /manifest endpoint includes itself in the endpoints list
"""

from __future__ import annotations

import contextlib
import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from hi_agent.contracts.extension_manifest import get_extension_registry
from hi_agent.server.tenant_context import require_tenant_context

logger = logging.getLogger(__name__)


def _get_package_version() -> str:
    """Return the installed package version, or 'dev' if not installed."""
    try:
        return _pkg_version("hi-agent")
    except PackageNotFoundError:
        return "dev"


def _derive_endpoints(request: Request) -> list[str]:
    """Build the endpoint list dynamically from the Starlette route table.

    Each Route contributes one entry per HTTP method: "METHOD /path".
    Non-Route objects (Mount, WebSocket, etc.) are skipped gracefully.
    """
    endpoints: list[str] = []
    try:
        for route in request.app.routes:
            if not isinstance(route, Route):
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path is None:
                continue
            if methods:
                for method in sorted(methods):
                    endpoints.append(f"{method} {path}")
            else:
                endpoints.append(path)
    except Exception as exc:
        logger.warning("manifest: endpoint derivation from route table failed: %s", exc)
    return endpoints


async def handle_manifest(request: Request) -> JSONResponse:
    """Return dynamic system capabilities manifest."""
    try:
        require_tenant_context()
    except RuntimeError:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    server = request.app.state.agent_server
    capabilities: list[str] = []
    capability_views: list[dict] = []
    capability_params: dict[str, object] = {}
    skills: list[dict] = []
    models: list[dict] = []
    profiles: list[dict] = []
    mcp_servers: list[dict] = []

    # --- Capabilities from live CapabilityInvoker/Registry ---
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None:
            invoker = builder.build_invoker()
            if invoker is not None:
                registry = getattr(invoker, "registry", None) or getattr(
                    invoker, "_registry", None
                )
                if registry is not None and hasattr(registry, "list_names"):
                    capabilities = list(registry.list_names())
                if registry is not None and hasattr(registry, "list_with_views"):
                    try:
                        capability_views = [
                            {
                                "name": name,
                                "status": status,
                                "toolset_id": getattr(desc, "toolset_id", "default")
                                if desc
                                else "default",
                                "required_env": list(getattr(desc, "required_env", {}).keys())
                                if desc
                                else [],
                                "effect_class": getattr(desc, "effect_class", "unknown_effect")
                                if desc
                                else "unknown_effect",
                                "output_budget_tokens": getattr(desc, "output_budget_tokens", 0)
                                if desc
                                else 0,
                                "availability_reason": reason,
                                # DX-4: full CapabilityDescriptor surface (getattr fallback for
                                # CO-6 canonical unification compatibility)
                                "risk_class": getattr(desc, "risk_class", "unknown")
                                if desc
                                else "unknown",
                                "requires_approval": getattr(desc, "requires_approval", False)
                                if desc
                                else False,
                                "provenance_required": getattr(desc, "provenance_required", False)
                                if desc
                                else False,
                                "source_reference_policy": getattr(
                                    desc, "source_reference_policy", "optional"
                                )
                                if desc
                                else "optional",
                                "reproducibility_level": getattr(
                                    desc, "reproducibility_level", "stochastic"
                                )
                                if desc
                                else "stochastic",
                                "license_policy": list(
                                    getattr(desc, "license_policy", ()) or ()
                                )
                                if desc
                                else [],
                            }
                            for name, desc, status, reason in registry.list_with_views()
                        ]
                    except Exception as _views_exc:
                        logger.warning(
                            "manifest: capability_views enumeration failed: %s", _views_exc
                        )
                # Pull parameters schema per capability — same data as GET /tools
                if registry is not None and hasattr(registry, "list_names") and hasattr(
                    registry, "get"
                ):
                    for cap_name in capabilities:
                        try:
                            spec = registry.get(cap_name)
                            if spec is not None:
                                capability_params[cap_name] = getattr(spec, "parameters", {})
                        except Exception as _param_exc:
                            logger.warning(
                                "manifest: parameters lookup failed for %r: %s",
                                cap_name,
                                _param_exc,
                            )
    except Exception as _cap_exc:
        logger.warning("manifest: capability enumeration failed: %s", _cap_exc)

    # --- Skills ---
    try:
        builder = getattr(server, "_builder", None)
        skill_loader = None
        if builder is not None and hasattr(builder, "build_skill_loader"):
            skill_loader = builder.build_skill_loader()
        if skill_loader is None:
            skill_loader = getattr(server, "skill_loader", None)
        if skill_loader is not None:
            if hasattr(skill_loader, "discover"):
                skill_loader.discover()
            if hasattr(skill_loader, "list_skills"):
                skills = [
                    {
                        "name": getattr(s, "name", str(s)),
                        "source": getattr(s, "source", "unknown"),
                    }
                    for s in skill_loader.list_skills()
                ]
    except Exception as _skill_exc:
        logger.warning("manifest: skill enumeration failed: %s", _skill_exc)

    # --- Profiles from ProfileRegistry (includes hi_agent_global when registered) ---
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None and hasattr(builder, "build_profile_registry"):
            reg = builder.build_profile_registry()
            if reg is not None and hasattr(reg, "list_profiles"):
                for p in reg.list_profiles():
                    profiles.append(
                        {
                            "profile_id": p.profile_id,
                            "display_name": p.display_name,
                            "stage_count": len(p.stage_actions),
                            "has_evaluator": p.evaluator_factory is not None,
                        }
                    )
        # Ensure hi_agent_global descriptor is always present in the list.
        # This is a filesystem-level virtual profile (not a ProfileSpec in the
        # registry), but downstream depends on seeing it in the profiles list.
        _global_id = "hi_agent_global"
        if not any(p["profile_id"] == _global_id for p in profiles):
            try:
                from hi_agent.profile.manager import GLOBAL_PROFILE_ID

                profiles.append(
                    {
                        "profile_id": GLOBAL_PROFILE_ID,
                        "display_name": "hi_agent_global",
                        "stage_count": 0,
                        "has_evaluator": False,
                    }
                )
            except Exception as _global_exc:
                logger.warning(
                    "manifest: hi_agent_global profile descriptor unavailable: %s", _global_exc
                )
    except Exception as _prof_exc:
        logger.warning("manifest: profile enumeration failed: %s", _prof_exc)

    # --- MCP servers with availability status ---
    try:
        mcp_server_obj = getattr(server, "mcp_server", None)
        if mcp_server_obj is not None:
            mcp_registry = getattr(mcp_server_obj, "_registry", None)
            if mcp_registry is not None and hasattr(mcp_registry, "list_servers"):
                for srv in mcp_registry.list_servers():
                    binding = getattr(mcp_server_obj, "_binding", None)
                    unavailable = set(getattr(binding, "_unavailable", []))
                    tools = srv.get("tools", [])
                    server_id = srv["server_id"]
                    mcp_servers.append(
                        {
                            "server_id": server_id,
                            "status": srv.get("status", "unknown"),
                            "tools": [
                                {
                                    "name": t,
                                    "available": f"mcp.{server_id}.{t}" not in unavailable,
                                }
                                for t in tools
                            ],
                        }
                    )
    except Exception as _mcp_exc:
        logger.warning("manifest: MCP server enumeration failed: %s", _mcp_exc)

    # --- Active stage list from stage graph ---
    stages: list[str] = []
    try:
        stage_graph = getattr(server, "stage_graph", None)
        if stage_graph is not None:
            transitions = getattr(stage_graph, "transitions", {})
            stages = sorted(transitions.keys())
    except Exception as _stage_exc:
        logger.warning("manifest: stage graph enumeration failed: %s", _stage_exc)

    # --- Models from live tier router ---
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None:
            tier_router = getattr(builder, "_tier_router", None)
            if tier_router is not None:
                registry = getattr(tier_router, "_registry", None)
                if registry is not None and hasattr(registry, "list_models"):
                    models = [
                        {
                            "name": m if isinstance(m, str) else getattr(m, "name", str(m)),
                            "status": "configured",
                        }
                        for m in registry.list_models()
                    ]
    except Exception as _model_exc:
        logger.warning("manifest: model enumeration failed: %s", _model_exc)

    # --- Plugins from live plugin loader singleton (with discovery) ---
    plugins: list[dict] = []
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None and hasattr(builder, "build_skill_loader"):
            plugin_loader = getattr(builder, "_plugin_loader", None)
            if plugin_loader is None:
                from hi_agent.plugin.loader import PluginLoader

                plugin_loader = PluginLoader()
                plugin_loader.load_all()
                builder._plugin_loader = plugin_loader
            if hasattr(plugin_loader, "list_loaded"):
                plugins = plugin_loader.list_loaded()
    except Exception as _plugin_exc:
        logger.warning("manifest: plugin enumeration failed: %s", _plugin_exc)

    # --- Active profile from config ---
    active_profile: str | None = None
    try:
        builder = getattr(server, "_builder", None)
        if builder is not None:
            cfg = getattr(builder, "_config", None)
            if cfg is not None:
                active_profile = getattr(cfg, "active_profile", None) or getattr(
                    cfg, "profile", None
                )
    except Exception as _active_prof_exc:
        logger.warning("manifest: active profile lookup failed: %s", _active_prof_exc)

    # --- Runtime mode, environment, and evolve policy ---
    evolve_policy: dict = {}
    runtime_mode: str = "dev-smoke"
    manifest_env: str = "dev"
    manifest_llm_mode: str = "unknown"
    manifest_llm_provider: str = "not_configured"
    manifest_llm_backend: str = "none"
    manifest_kernel_mode: str = "local-fsm"
    manifest_execution_mode: str = "local"
    provenance_contract_version: str = "unknown"
    try:
        import os as _os_ep

        from hi_agent.config.evolve_policy import resolve_evolve_effective as _rep
        from hi_agent.contracts.execution_provenance import CONTRACT_VERSION
        from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode as _rrm

        provenance_contract_version = CONTRACT_VERSION
        _builder = getattr(server, "_builder", None)
        _ev_mode = "auto"
        if _builder is not None:
            _cfg = getattr(_builder, "_config", None)
            if _cfg is not None:
                _ev_mode = getattr(_cfg, "evolve_mode", "auto")
        manifest_env = _os_ep.environ.get("HI_AGENT_ENV", "dev").lower()
        _readiness_snap: dict = {}
        if _builder is not None:
            with contextlib.suppress(Exception):
                _readiness_snap = _builder.readiness()
        runtime_mode = _rrm(manifest_env, _readiness_snap)
        manifest_llm_mode = _readiness_snap.get("llm_mode", "unknown")
        manifest_llm_provider = _readiness_snap.get("llm_provider", "not_configured")
        manifest_llm_backend = _readiness_snap.get("llm_backend", "none")
        manifest_kernel_mode = _readiness_snap.get("kernel_mode", "local-fsm")
        manifest_execution_mode = _readiness_snap.get("execution_mode", "local")
        if _readiness_snap.get("models"):
            models = list(_readiness_snap.get("models", models))
        _ev_enabled, _ev_source = _rep(_ev_mode, runtime_mode)
        evolve_policy = {"mode": _ev_mode, "effective": _ev_enabled, "source": _ev_source}
    except Exception as _ep_exc:
        logger.warning("manifest: runtime_mode/evolve_policy lookup failed: %s", _ep_exc)

    # --- Extensions from global ExtensionRegistry (posture-filtered) ---
    extensions: list[dict] = []
    try:
        import os as _os_ext

        _posture_name = _os_ext.environ.get("HI_AGENT_POSTURE", "dev").strip().lower()
        _ext_registry = get_extension_registry()
        extensions = [
            m.to_manifest_dict() for m in _ext_registry.list_for_posture(_posture_name)
        ]
    except Exception as _ext_exc:
        logger.warning("manifest: extension registry enumeration failed: %s", _ext_exc)

    # Build capabilities list with parameters schema attached
    capabilities_with_params: list[dict] = [
        {
            "name": name,
            "parameters": capability_params.get(name, {}),
        }
        for name in capabilities
    ]

    # Derive endpoints dynamically from the route table
    endpoints = _derive_endpoints(request)

    return JSONResponse(
        {
            "name": "hi-agent",
            "version": _get_package_version(),
            "framework": "TRACE",
            "stages": stages,
            "capabilities": capabilities,
            "capabilities_with_params": capabilities_with_params,
            "capability_views": capability_views,
            "capability_contract_version": "2026-04-17",
            "profiles": profiles,
            "skills": skills,
            "models": models,
            "mcp_servers": mcp_servers,
            "plugins": plugins,
            "evolve_policy": evolve_policy,
            "endpoints": endpoints,
            "active_profile": active_profile,
            "runtime_mode": runtime_mode,
            "environment": manifest_env,
            "llm_mode": manifest_llm_mode,
            "llm_provider": manifest_llm_provider,
            "llm_backend": manifest_llm_backend,
            "kernel_mode": manifest_kernel_mode,
            "execution_mode": manifest_execution_mode,
            "provenance_contract_version": provenance_contract_version,
            "extensions": extensions,
            "contract_field_status": {
                "goal": "ACTIVE",
                "task_family": "ACTIVE",
                "risk_level": "ACTIVE",
                "constraints": "ACTIVE",
                "acceptance_criteria": "ACTIVE",
                "budget": "ACTIVE",
                "deadline": "ACTIVE",
                "profile_id": "ACTIVE",
                "decomposition_strategy": "ACTIVE",
                "priority": "QUEUE_ONLY",
                "environment_scope": "PASSTHROUGH",
                "input_refs": "PASSTHROUGH",
                "parent_task_id": "PASSTHROUGH",
            },
            "e2e_contract": {
                "dev_smoke_path": {
                    "status": "available",
                    "description": (
                        "Default service mode runs in dev/fallback mode. "
                        "POST /runs → GET /runs/{id} → GET /runs/{id}/artifacts is functional. "
                        "This is a smoke path using heuristic fallback — not production E2E."
                    ),
                },
                "production_e2e": {
                    "status": "requires_prerequisites",
                    "prerequisites": [
                        "OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable",
                        "kernel_base_url set to a real agent-kernel HTTP endpoint",
                        "HI_AGENT_ENV=prod",
                    ],
                    "description": (
                        "Formal production E2E is not available in default (dev) mode. "
                        "Set HI_AGENT_ENV=prod and provide real credentials + kernel endpoint."
                    ),
                },
                "mcp_provider": {
                    "status": "infrastructure_only",
                    "description": (
                        "External MCP server transport (stdio/SSE/HTTP) is not yet implemented. "
                        "Platform tools are accessible as MCP-compatible endpoints, but "
                        "external server registration and invocation forwarding are deferred."
                    ),
                },
            },
        }
    )


MANIFEST_ROUTES = [Route("/manifest", handle_manifest, methods=["GET"])]
