from __future__ import annotations

import os

from hi_agent.ops.doctor_report import DoctorIssue, DoctorReport


def build_doctor_report(builder, server=None) -> DoctorReport:
    """Build a diagnostic report from the current system state.

    Pure function: reads builder state + env vars. Real network probes only in prod.

    Args:
        builder: SystemBuilder instance (or minimal stub for tests).
        server: Optional AgentServer instance. When provided, posture checks
            can inspect live durable-backend state (Fix 7).
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

    # 9. Posture-aware checks (including durable backend state when server is known)
    _check_posture(issues_blocking, issues_warnings, issues_info, server=server)

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
        blocking.append(
            DoctorIssue(
                subsystem="llm",
                code="llm.missing_credentials",
                severity="blocking",
                message="No LLM credentials found in production mode.",
                fix="set ANTHROPIC_API_KEY or OPENAI_API_KEY",
                verify="echo $ANTHROPIC_API_KEY | head -c 10",
            )
        )
    elif not (has_anthropic or has_openai):
        warnings.append(
            DoctorIssue(
                subsystem="llm",
                code="llm.missing_credentials_dev",
                severity="warning",
                message="No LLM credentials found (dev mode — heuristic fallback active).",
                fix="set ANTHROPIC_API_KEY or OPENAI_API_KEY for real LLM",
                verify="echo $ANTHROPIC_API_KEY | head -c 10",
            )
        )


def _check_kernel_reachable(builder, is_prod: bool, blocking: list, warnings: list) -> None:
    # P2-10 bugfix: align with TraceConfig.from_env() which reads
    # HI_AGENT_KERNEL_BASE_URL (not HI_AGENT_KERNEL_URL). Fall back to the
    # legacy name for backwards compatibility with stale deploy scripts.
    kernel_url = os.environ.get("HI_AGENT_KERNEL_BASE_URL") or os.environ.get(
        "HI_AGENT_KERNEL_URL", ""
    )
    # Normalize: "local" sentinel means in-process LocalFSM, not an HTTP URL.
    if kernel_url.lower() == "local":
        kernel_url = ""
    if is_prod and not kernel_url:
        blocking.append(
            DoctorIssue(
                subsystem="kernel",
                code="kernel.missing_url",
                severity="blocking",
                message="HI_AGENT_KERNEL_URL not set in production mode.",
                fix="set HI_AGENT_KERNEL_URL=http://<kernel-host>:<port>",
                verify="curl -s $HI_AGENT_KERNEL_URL/health",
            )
        )
    elif is_prod and kernel_url:
        # Real HTTP probe in prod
        try:
            import urllib.request

            urllib.request.urlopen(f"{kernel_url}/health", timeout=3)
        except Exception as e:
            blocking.append(
                DoctorIssue(
                    subsystem="kernel",
                    code="kernel.unreachable",
                    severity="blocking",
                    message=f"Kernel HTTP probe failed: {e}",
                    fix=f"Ensure kernel is running at {kernel_url}",
                    verify=f"curl -s {kernel_url}/health",
                )
            )


def _check_capability_registry(builder, blocking: list) -> None:
    try:
        registry = getattr(builder, "_capability_registry", None) or getattr(
            builder, "capability_registry", None
        )
        if registry is None:
            registry = getattr(builder, "_invoker", None)
            registry = getattr(registry, "registry", None) if registry else None
        if registry is not None:
            caps = (
                getattr(registry, "_handlers", None)
                or getattr(registry, "_capabilities", None)
                or {}
            )
            if not caps:
                blocking.append(
                    DoctorIssue(
                        subsystem="capability",
                        code="capability.empty_registry",
                        severity="blocking",
                        message="Capability registry has no registered handlers.",
                        fix="Call register_default_capabilities(registry) in SystemBuilder",
                        verify="python -m hi_agent doctor",
                    )
                )
    except Exception:  # rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests
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
                warnings.append(
                    DoctorIssue(
                        subsystem="mcp",
                        code="mcp.server_error",
                        severity="warning",
                        message=f"MCP server {server_id!r} reported error: {stderr[:200]}",
                        fix=f"Check MCP server {server_id} configuration and restart",
                        verify=(
                            "hi-agent doctor --json | jq "
                            "'.warnings[] | select(.code==\"mcp.server_error\")'"
                        ),
                    )
                )
    except Exception:  # rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests
        pass


def _check_skill_loader(builder, warnings: list) -> None:
    try:
        skill_loader = getattr(builder, "_skill_loader", None)
        if skill_loader is not None:
            skill_path = getattr(skill_loader, "skill_path", None) or getattr(
                skill_loader, "_path", None
            )
            if skill_path and not __import__("os").path.exists(str(skill_path)):
                warnings.append(
                    DoctorIssue(
                        subsystem="skills",
                        code="skills.skill_md_missing",
                        severity="warning",
                        message=f"SKILL.md not found at {skill_path}",
                        fix=f"Create {skill_path} or configure a valid skill path",
                        verify=f"ls {skill_path}",
                    )
                )
    except Exception:  # rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests
        pass


def _check_memory_dirs(builder, warnings: list) -> None:
    try:
        memory_path = getattr(builder, "_memory_path", None) or ".hi_agent"
        if not os.access(str(memory_path), os.W_OK):
            warnings.append(
                DoctorIssue(
                    subsystem="memory",
                    code="memory.dir_not_writable",
                    severity="warning",
                    message=f"Memory directory {memory_path!r} is not writable.",
                    # SA-8 (self-audit 2026-04-21): HI_AGENT_MEMORY_PATH was
                    # referenced here as a remediation hint but no code reads
                    # it. Point operators at the actual knob (episodic_storage_dir
                    # via config file / HI_AGENT_EPISODIC_STORAGE_DIR).
                    fix=(
                        f"chmod u+w {memory_path} or set "
                        "HI_AGENT_EPISODIC_STORAGE_DIR to a writable directory"
                    ),
                    verify=f"ls -la {memory_path}",
                )
            )
    except Exception:  # rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests
        pass


def _check_profile(builder, warnings: list) -> None:
    try:
        config = getattr(builder, "_config", None) or getattr(builder, "config", None)
        if config is not None:
            profile_id = getattr(config, "profile_id", None)
            if profile_id and profile_id != "default":
                # Just note current profile
                pass
    except Exception:  # rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests
        pass


def _check_evolve_policy(builder, info: list) -> None:
    try:
        config = getattr(builder, "_config", None) or getattr(builder, "config", None)
        if config is not None:
            evolve_mode = getattr(config, "evolve_mode", "auto")
            info.append(
                DoctorIssue(
                    subsystem="evolve",
                    code="evolve.policy_info",
                    severity="info",
                    message=f"Evolve policy: mode={evolve_mode!r}",
                    fix="Set HI_AGENT_EVOLVE_MODE=on|off|auto to change",
                    verify=(
                        "python -m hi_agent doctor --json | jq "
                        "'.info[] | select(.subsystem==\"evolve\")'"
                    ),
                )
            )
    except Exception:  # rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests
        pass


def _check_posture(blocking: list, warnings: list, info: list, server=None) -> None:
    """Posture-aware checks (DX-3).

    Checks:
    1. HI_AGENT_POSTURE is set and parseable.
    2. Under research/prod: HI_AGENT_DATA_DIR must be set (blocking).
    3. Under research/prod: project_id enforcement is active.
    4. Under research/prod: profile_id enforcement is active.
    5. T3 gate freshness: docs/delivery/ newest JSON < 7 days old.
    6. Under research/prod: durable backends (run_store) must be constructed (Fix 7).

    Args:
        blocking: Accumulator for blocking DoctorIssue entries.
        warnings: Accumulator for warning DoctorIssue entries.
        info: Accumulator for info DoctorIssue entries.
        server: Optional AgentServer instance for live backend introspection.
    """
    from hi_agent.config.posture import Posture

    # --- 1. Posture set and valid ---
    raw_posture = os.environ.get("HI_AGENT_POSTURE", "")
    posture: Posture
    if not raw_posture:
        info.append(
            DoctorIssue(
                subsystem="posture",
                code="posture.not_set",
                severity="info",
                message="HI_AGENT_POSTURE is not set; defaulting to 'dev'.",
                fix="Set HI_AGENT_POSTURE=dev|research|prod",
                verify="echo $HI_AGENT_POSTURE",
            )
        )
        posture = Posture.DEV
    else:
        try:
            posture = Posture(raw_posture.strip().lower())
            info.append(
                DoctorIssue(
                    subsystem="posture",
                    code="posture.active",
                    severity="info",
                    message=f"Active posture: {posture.value!r}",
                    fix="",
                    verify="echo $HI_AGENT_POSTURE",
                )
            )
        except ValueError:
            valid = [p.value for p in Posture]
            blocking.append(
                DoctorIssue(
                    subsystem="posture",
                    code="posture.invalid",
                    severity="blocking",
                    message=(
                        f"HI_AGENT_POSTURE={raw_posture!r} is not valid. "
                        f"Valid values: {valid}"
                    ),
                    fix=f"Set HI_AGENT_POSTURE to one of {valid}",
                    verify="echo $HI_AGENT_POSTURE",
                )
            )
            return

    if not posture.requires_durable_backend:
        # Dev posture — skip remaining checks
        return

    # --- 2. HI_AGENT_DATA_DIR required under research/prod ---
    data_dir = os.environ.get("HI_AGENT_DATA_DIR", "")
    if not data_dir:
        blocking.append(
            DoctorIssue(
                subsystem="posture",
                code="posture.data_dir_missing",
                severity="blocking",
                message=(
                    f"HI_AGENT_DATA_DIR is required under {posture.value!r} posture "
                    "for durable queue and ledger backends."
                ),
                fix="export HI_AGENT_DATA_DIR=/var/hi_agent (or any writable directory)",
                verify="echo $HI_AGENT_DATA_DIR",
            )
        )
    else:
        info.append(
            DoctorIssue(
                subsystem="posture",
                code="posture.data_dir_ok",
                severity="info",
                message=f"HI_AGENT_DATA_DIR={data_dir!r}",
                fix="",
                verify="ls $HI_AGENT_DATA_DIR",
            )
        )

    # --- 3. project_id enforcement ---
    if posture.requires_project_id:
        proj_required = os.environ.get("HI_AGENT_PROJECT_ID_REQUIRED", "")
        if not proj_required:
            warnings.append(
                DoctorIssue(
                    subsystem="posture",
                    code="posture.project_id_not_enforced",
                    severity="warning",
                    message=(
                        f"Under {posture.value!r} posture, project_id enforcement is "
                        "recommended. Set HI_AGENT_PROJECT_ID_REQUIRED=1 to enforce."
                    ),
                    fix="export HI_AGENT_PROJECT_ID_REQUIRED=1",
                    verify="echo $HI_AGENT_PROJECT_ID_REQUIRED",
                )
            )

    # --- 4. profile_id enforcement ---
    if posture.requires_profile_id:
        prof_required = os.environ.get("HI_AGENT_PROFILE_ID_REQUIRED", "")
        if not prof_required:
            warnings.append(
                DoctorIssue(
                    subsystem="posture",
                    code="posture.profile_id_not_enforced",
                    severity="warning",
                    message=(
                        f"Under {posture.value!r} posture, profile_id enforcement is "
                        "recommended. Set HI_AGENT_PROFILE_ID_REQUIRED=1 to enforce."
                    ),
                    fix="export HI_AGENT_PROFILE_ID_REQUIRED=1",
                    verify="echo $HI_AGENT_PROFILE_ID_REQUIRED",
                )
            )

    # --- 5. T3 gate freshness ---
    _check_t3_gate_freshness(warnings, info)

    # --- 6. Durable backend state (Fix 7) ---
    # When a live server is available, verify that critical durable stores were
    # actually constructed. Under strict posture a None run_store means the
    # server silently degraded — surface this as a blocking issue.
    if server is not None:
        run_store = getattr(server, "_run_store", None)
        if run_store is None:
            blocking.append(
                DoctorIssue(
                    subsystem="posture",
                    code="posture.durable_backend_missing",
                    severity="blocking",
                    message=(
                        f"Under {posture.value!r} posture the run_store durable backend "
                        "is None. The server silently degraded at startup."
                    ),
                    fix="Set HI_AGENT_DATA_DIR to a writable directory and restart.",
                    verify="echo $HI_AGENT_DATA_DIR",
                )
            )
        else:
            info.append(
                DoctorIssue(
                    subsystem="posture",
                    code="posture.durable_backend_ok",
                    severity="info",
                    message="Durable run_store backend is constructed and wired.",
                    fix="",
                    verify="",
                )
            )


def _check_t3_gate_freshness(warnings: list, info: list) -> None:
    """Check that the most recent T3 gate record is < 7 days old."""
    import time
    from pathlib import Path

    delivery_dir = Path(__file__).parent.parent.parent / "docs" / "delivery"
    if not delivery_dir.exists():
        warnings.append(
            DoctorIssue(
                subsystem="t3_gate",
                code="t3_gate.no_delivery_dir",
                severity="warning",
                message="docs/delivery/ directory not found; T3 gate has never been recorded.",
                fix="Run the Rule 8 operator-shape gate and record in docs/delivery/",
                verify="ls docs/delivery/",
            )
        )
        return

    json_files = sorted(delivery_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not json_files:
        warnings.append(
            DoctorIssue(
                subsystem="t3_gate",
                code="t3_gate.no_records",
                severity="warning",
                message="No T3 gate records found in docs/delivery/.",
                fix="Run the Rule 8 operator-shape gate and record in docs/delivery/",
                verify="ls docs/delivery/*.json",
            )
        )
        return

    newest = json_files[-1]
    age_seconds = time.time() - newest.stat().st_mtime
    age_days = age_seconds / 86400

    if age_days > 7:
        warnings.append(
            DoctorIssue(
                subsystem="t3_gate",
                code="t3_gate.stale",
                severity="warning",
                message=(
                    f"Most recent T3 gate record ({newest.name}) is "
                    f"{age_days:.1f} days old (>7). Re-run the Rule 8 gate."
                ),
                fix="Run the Rule 8 operator-shape gate and record in docs/delivery/",
                verify=f"ls -la docs/delivery/{newest.name}",
            )
        )
    else:
        info.append(
            DoctorIssue(
                subsystem="t3_gate",
                code="t3_gate.fresh",
                severity="info",
                message=(
                    f"T3 gate record {newest.name!r} is {age_days:.1f} days old (ok)."
                ),
                fix="",
                verify=f"ls -la docs/delivery/{newest.name}",
            )
        )
