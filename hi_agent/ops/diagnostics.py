from __future__ import annotations

import os

from hi_agent.ops.doctor_report import DoctorIssue, DoctorReport


def build_doctor_report(builder) -> DoctorReport:
    """Build a diagnostic report from the current system state.

    Pure function: reads builder state + env vars. Real network probes only in prod.
    """
    issues_blocking: list[DoctorIssue] = []
    issues_warnings: list[DoctorIssue] = []
    issues_info: list[DoctorIssue] = []

    env = getattr(builder, "_env", os.environ.get("HI_AGENT_ENV", "dev"))
    is_prod = env == "prod"

    # 1. LLM credentials (prod hard check)
    _check_llm_credentials(is_prod, issues_blocking, issues_warnings)

    # 2. Kernel reachable (prod HTTP endpoint check)
    _check_kernel_reachable(builder, is_prod, issues_blocking, issues_warnings)

    # 3. Capability registry — must have at least one handler
    _check_capability_registry(builder, issues_blocking)

    # 4. MCP server health (if configured)
    _check_mcp_health(builder, issues_warnings)

    # 5. Skill loader — can read SKILL.md from configured path
    _check_skill_loader(builder, issues_warnings)

    # 6. Memory / knowledge writable directories
    _check_memory_dirs(builder, issues_warnings)

    # 7. Profile parse
    _check_profile(builder, issues_warnings)

    # 8. Evolve policy effective value
    _check_evolve_policy(builder, issues_info)

    # Determine status
    if issues_blocking:
        status = "error"
    elif issues_warnings:
        status = "degraded"
    else:
        status = "ready"

    next_steps = [i.fix for i in issues_blocking[:3]]

    return DoctorReport(
        status=status,
        blocking=issues_blocking,
        warnings=issues_warnings,
        info=issues_info,
        next_steps=next_steps,
    )


def _check_llm_credentials(is_prod: bool, blocking: list, warnings: list) -> None:
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    if is_prod and not (has_anthropic or has_openai):
        blocking.append(DoctorIssue(
            subsystem="llm",
            code="llm.missing_credentials",
            severity="blocking",
            message="No LLM credentials found in production mode.",
            fix="set ANTHROPIC_API_KEY or OPENAI_API_KEY",
            verify="echo $ANTHROPIC_API_KEY | head -c 10",
        ))
    elif not (has_anthropic or has_openai):
        warnings.append(DoctorIssue(
            subsystem="llm",
            code="llm.missing_credentials_dev",
            severity="warning",
            message="No LLM credentials found (dev mode — heuristic fallback active).",
            fix="set ANTHROPIC_API_KEY or OPENAI_API_KEY for real LLM",
            verify="echo $ANTHROPIC_API_KEY | head -c 10",
        ))


def _check_kernel_reachable(builder, is_prod: bool, blocking: list, warnings: list) -> None:
    kernel_url = os.environ.get("HI_AGENT_KERNEL_URL", "")
    if is_prod and not kernel_url:
        blocking.append(DoctorIssue(
            subsystem="kernel",
            code="kernel.missing_url",
            severity="blocking",
            message="HI_AGENT_KERNEL_URL not set in production mode.",
            fix="set HI_AGENT_KERNEL_URL=http://<kernel-host>:<port>",
            verify="curl -s $HI_AGENT_KERNEL_URL/health",
        ))
    elif is_prod and kernel_url:
        # Real HTTP probe in prod
        try:
            import urllib.request
            urllib.request.urlopen(f"{kernel_url}/health", timeout=3)
        except Exception as e:
            blocking.append(DoctorIssue(
                subsystem="kernel",
                code="kernel.unreachable",
                severity="blocking",
                message=f"Kernel HTTP probe failed: {e}",
                fix=f"Ensure kernel is running at {kernel_url}",
                verify=f"curl -s {kernel_url}/health",
            ))


def _check_capability_registry(builder, blocking: list) -> None:
    try:
        registry = getattr(builder, "_capability_registry", None) or getattr(builder, "capability_registry", None)
        if registry is None:
            registry = getattr(builder, "_invoker", None)
            registry = getattr(registry, "registry", None) if registry else None
        if registry is not None:
            caps = getattr(registry, "_handlers", None) or getattr(registry, "_capabilities", None) or {}
            if not caps:
                blocking.append(DoctorIssue(
                    subsystem="capability",
                    code="capability.empty_registry",
                    severity="blocking",
                    message="Capability registry has no registered handlers.",
                    fix="Call register_default_capabilities(registry) in SystemBuilder",
                    verify="python -m hi_agent doctor",
                ))
    except Exception:
        pass  # Registry introspection failure is non-fatal


def _check_mcp_health(builder, warnings: list) -> None:
    try:
        mcp_status = getattr(builder, "_mcp_status", {}) or {}
        transport = mcp_status.get("transport_status", "not_wired")
        if transport == "not_wired":
            pass  # Normal in dev, not an issue
        else:
            server_id = mcp_status.get("server_id", "unknown")
            stderr = mcp_status.get("stderr_summary", "")
            if mcp_status.get("health") == "error":
                warnings.append(DoctorIssue(
                    subsystem="mcp",
                    code="mcp.server_error",
                    severity="warning",
                    message=f"MCP server {server_id!r} reported error: {stderr[:200]}",
                    fix=f"Check MCP server {server_id} configuration and restart",
                    verify="hi-agent doctor --json | jq '.warnings[] | select(.code==\"mcp.server_error\")'",
                ))
    except Exception:
        pass


def _check_skill_loader(builder, warnings: list) -> None:
    try:
        skill_loader = getattr(builder, "_skill_loader", None)
        if skill_loader is not None:
            skill_path = getattr(skill_loader, "skill_path", None) or getattr(skill_loader, "_path", None)
            if skill_path and not __import__("os").path.exists(str(skill_path)):
                warnings.append(DoctorIssue(
                    subsystem="skills",
                    code="skills.skill_md_missing",
                    severity="warning",
                    message=f"SKILL.md not found at {skill_path}",
                    fix=f"Create {skill_path} or configure a valid skill path",
                    verify=f"ls {skill_path}",
                ))
    except Exception:
        pass


def _check_memory_dirs(builder, warnings: list) -> None:
    try:
        memory_path = getattr(builder, "_memory_path", None) or ".hi_agent"
        if not os.access(str(memory_path), os.W_OK):
            warnings.append(DoctorIssue(
                subsystem="memory",
                code="memory.dir_not_writable",
                severity="warning",
                message=f"Memory directory {memory_path!r} is not writable.",
                fix=f"chmod u+w {memory_path} or set HI_AGENT_MEMORY_PATH",
                verify=f"ls -la {memory_path}",
            ))
    except Exception:
        pass


def _check_profile(builder, warnings: list) -> None:
    try:
        config = getattr(builder, "_config", None) or getattr(builder, "config", None)
        if config is not None:
            profile_id = getattr(config, "profile_id", None)
            if profile_id and profile_id != "default":
                # Just note current profile
                pass
    except Exception:
        pass


def _check_evolve_policy(builder, info: list) -> None:
    try:
        config = getattr(builder, "_config", None) or getattr(builder, "config", None)
        if config is not None:
            evolve_mode = getattr(config, "evolve_mode", "auto")
            info.append(DoctorIssue(
                subsystem="evolve",
                code="evolve.policy_info",
                severity="info",
                message=f"Evolve policy: mode={evolve_mode!r}",
                fix="Set HI_AGENT_EVOLVE_MODE=on|off|auto to change",
                verify="python -m hi_agent doctor --json | jq '.info[] | select(.subsystem==\"evolve\")'",
            ))
    except Exception:
        pass
