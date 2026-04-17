"""Command-line interface for hi-agent.

Usage::

    python -m hi_agent serve [--host HOST] [--port PORT]
    python -m hi_agent run --goal "..." [--task-family FAMILY] [--risk-level LEVEL]
    python -m hi_agent status [--run-id RUN_ID]
    python -m hi_agent health
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


_DEFAULT_API_TIMEOUT_SECONDS = 15.0


def _resolve_api_timeout() -> float:
    """Return a safe API timeout from the environment.

    Invalid, missing, or non-positive values fall back to the default so the
    CLI stays usable even when the environment is misconfigured.
    """
    raw_value = os.getenv("HI_AGENT_API_TIMEOUT_SECONDS")
    if raw_value is None or raw_value == "":
        return _DEFAULT_API_TIMEOUT_SECONDS

    try:
        timeout = float(raw_value)
    except ValueError:
        print(
            (
                "Warning: invalid HI_AGENT_API_TIMEOUT_SECONDS="
                f"{raw_value!r}; using default {_DEFAULT_API_TIMEOUT_SECONDS:.0f}s"
            ),
            file=sys.stderr,
        )
        return _DEFAULT_API_TIMEOUT_SECONDS

    if timeout <= 0:
        print(
            (
                "Warning: HI_AGENT_API_TIMEOUT_SECONDS must be positive; "
                f"got {raw_value!r}. Using default "
                f"{_DEFAULT_API_TIMEOUT_SECONDS:.0f}s"
            ),
            file=sys.stderr,
        )
        return _DEFAULT_API_TIMEOUT_SECONDS

    return timeout


def _api_request(
    method: str,
    url: str,
    body: dict | None = None,
    *,
    timeout_seconds: float | None = None,
) -> tuple[int, dict]:
    """Make a JSON HTTP request using stdlib.

    Args:
        method: HTTP method.
        url: Full URL.
        body: Optional JSON-serializable body.
        timeout_seconds: Request timeout. If omitted, reads from
            ``HI_AGENT_API_TIMEOUT_SECONDS`` (default: 15).

    Returns:
        Tuple of (status_code, parsed_json_body).
    """
    data = json.dumps(body).encode("utf-8") if body else None
    timeout = timeout_seconds
    if timeout is None:
        timeout = _resolve_api_timeout()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _decode_response_body(resp.read())
    except urllib.error.HTTPError as exc:
        payload = _decode_response_body(exc.read())
        if "error" not in payload:
            payload["error"] = "http_error"
        payload.setdefault("status_code", exc.code)
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"error": f"connection_failed: {exc.reason}"}


def _decode_response_body(raw: bytes) -> dict:
    """Decode an HTTP response body into a dictionary.

    Tries JSON first. If the body is empty or not valid JSON, returns a
    structured fallback dict so CLI commands can always render safely.

    Args:
        raw: Raw response bytes from urllib.

    Returns:
        Parsed JSON object, or a fallback dict containing error metadata.
    """
    if not raw:
        return {"error": "empty_response_body"}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
    except json.JSONDecodeError:
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return {"error": "empty_response_body"}
        preview = text[:500]
        return {"error": "non_json_response", "raw_body": preview}


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start the API server."""
    import os

    from hi_agent.config.trace_config import TraceConfig
    from hi_agent.server.app import AgentServer

    # Default to dev mode so the server works out of the box without API keys
    # or real kernel endpoints.  Use --prod to require real credentials.
    if getattr(args, "prod", False):
        os.environ.setdefault("HI_AGENT_ENV", "prod")
        print(
            "[hi-agent] Starting in PROD mode.\n"
            "  Formal E2E prerequisites: real API key + real agent-kernel endpoint.\n"
            "  Without these, POST /runs will return 503."
        )
    else:
        os.environ.setdefault("HI_AGENT_ENV", "dev")
        print(
            "[hi-agent] Starting in DEV mode (default).\n"
            "  Smoke path is available: POST /runs → GET /runs/{id} → artifacts.\n"
            "  Note: dev mode uses heuristic fallback — NOT formal production E2E.\n"
            "  For formal E2E, use `serve --prod` with real API key + kernel endpoint."
        )

    config = TraceConfig(server_host=args.host, server_port=args.port)
    server = AgentServer(host=args.host, port=args.port, config=config)
    server.start()


def _cmd_run(args: argparse.Namespace) -> None:
    """Execute a task -- locally via SystemBuilder, or via the API server."""
    if getattr(args, "local", False):
        # Local execution: build executor directly, no server needed.
        # --local implies dev mode so heuristic fallback and in-process kernel
        # are allowed even when no API key or real kernel endpoint is set.
        os.environ.setdefault("HI_AGENT_ENV", "dev")

        import json as _json
        import uuid
        from hi_agent.config.builder import SystemBuilder
        from hi_agent.config.stack import ConfigStack
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.contracts import TaskContract

        config_file = getattr(args, "config", None) or os.getenv("HI_AGENT_CONFIG_FILE")
        profile = getattr(args, "profile", None)
        config_patch_str = getattr(args, "config_patch", None)
        config_patch = _json.loads(config_patch_str) if config_patch_str else None

        # Resolve evolve_mode: CLI flags > HI_AGENT_EVOLVE_MODE env var > config default
        _evolve_mode_override: str | None = None
        if getattr(args, "enable_evolve", False):
            _evolve_mode_override = "on"
        elif getattr(args, "disable_evolve", False):
            _evolve_mode_override = "off"
        else:
            _env_evolve = os.getenv("HI_AGENT_EVOLVE_MODE")
            if _env_evolve in ("on", "off", "auto"):
                _evolve_mode_override = _env_evolve
        if _evolve_mode_override is not None:
            config_patch = dict(config_patch or {})
            config_patch["evolve_mode"] = _evolve_mode_override

        try:
            stack = ConfigStack(base_config_path=config_file, profile=profile)
            config = stack.resolve()
            builder = SystemBuilder(config=config, config_stack=stack)
            profile_id = getattr(args, "profile_id", None)
            import json as _json2
            constraints_raw = getattr(args, "constraints", None)
            constraints = _json2.loads(constraints_raw) if constraints_raw else []
            acceptance_criteria_raw = getattr(args, "acceptance_criteria", None)
            acceptance_criteria = _json2.loads(acceptance_criteria_raw) if acceptance_criteria_raw else []
            input_refs_raw = getattr(args, "input_refs", None)
            input_refs = _json2.loads(input_refs_raw) if input_refs_raw else []
            environment_scope_raw = getattr(args, "environment_scope", None)
            environment_scope = _json2.loads(environment_scope_raw) if environment_scope_raw else []
            _contract_kwargs: dict = {
                "task_id": uuid.uuid4().hex[:12],
                "goal": args.goal,
                "task_family": args.task_family,
                "risk_level": args.risk_level,
                "profile_id": profile_id,
                "constraints": constraints,
                "acceptance_criteria": acceptance_criteria,
                "input_refs": input_refs,
                "environment_scope": environment_scope,
            }
            if getattr(args, "deadline", None) is not None:
                _contract_kwargs["deadline"] = args.deadline
            if getattr(args, "priority", None) is not None:
                _contract_kwargs["priority"] = args.priority
            if getattr(args, "decomposition_strategy", None) is not None:
                _contract_kwargs["decomposition_strategy"] = args.decomposition_strategy
            if getattr(args, "parent_task_id", None) is not None:
                _contract_kwargs["parent_task_id"] = args.parent_task_id
            budget_raw = getattr(args, "budget", None)
            if budget_raw is not None:
                from hi_agent.contracts.task import TaskBudget  # noqa: PLC0415
                budget_data = _json2.loads(budget_raw)
                _contract_kwargs["budget"] = TaskBudget(
                    max_llm_calls=budget_data.get("max_llm_calls", 100),
                    max_wall_clock_seconds=budget_data.get("max_wall_clock_seconds", 3600),
                    max_actions=budget_data.get("max_actions", 50),
                    max_cost_cents=budget_data.get("max_cost_cents", 1000),
                )
            contract = TaskContract(**_contract_kwargs)
            executor = builder.build_executor(contract, config_patch=config_patch)
            result = executor.execute()
        except Exception as exc:
            print(
                f"Error: local run failed — {exc}\n"
                "Tip: check HI_AGENT_ENV, API keys, or run with --json for details.",
                file=sys.stderr,
            )
            if args.json:
                print(json.dumps({"error": str(exc)}, indent=2))
            sys.exit(1)

        if args.json:
            # Serialize structured RunResult if available, else fall back to str.
            try:
                result_data = result.to_dict()
            except AttributeError:
                result_data = {"result": str(result)}
            print(json.dumps(result_data, indent=2))
        else:
            status = str(result)
            stage_count = len(getattr(result, "stages", []))
            artifact_count = len(getattr(result, "artifacts", []))
            print(
                f"Run {status}: {stage_count} stage(s) completed, "
                f"{artifact_count} artifact(s) produced."
            )
        return

    # Remote execution: submit to API server.
    base = f"http://{args.api_host}:{args.api_port}"
    body: dict = {
        "goal": args.goal,
        "task_family": args.task_family,
        "risk_level": args.risk_level,
    }
    profile_id = getattr(args, "profile_id", None)
    if profile_id:
        body["profile_id"] = profile_id
    status, data = _api_request("POST", f"{base}/runs", body)
    if args.json:
        print(json.dumps(data, indent=2))
        if status != 201:
            sys.exit(1)
    else:
        if status == 201:
            print(f"Run created: {data.get('run_id')} (state={data.get('state')})")
        else:
            print(f"Error ({status}): {data}", file=sys.stderr)
            sys.exit(1)


def _cmd_status(args: argparse.Namespace) -> None:
    """Query run status."""
    base = f"http://{args.api_host}:{args.api_port}"
    if args.run_id:
        status, data = _api_request("GET", f"{base}/runs/{args.run_id}")
    else:
        status, data = _api_request("GET", f"{base}/runs")
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        if status >= 400:
            print(f"Error ({status}): {data}", file=sys.stderr)
        else:
            if args.run_id:
                print(
                    f"Run status: {data.get('run_id', args.run_id)} "
                    f"(state={data.get('state', 'unknown')})"
                )
            else:
                print(f"Runs: {data}")
    if status >= 400:
        sys.exit(1)


def _cmd_health(args: argparse.Namespace) -> None:
    """Check server health."""
    base = f"http://{args.api_host}:{args.api_port}"
    status, data = _api_request("GET", f"{base}/health")
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        if status >= 400:
            print(f"Error ({status}): {data}", file=sys.stderr)
        else:
            print(f"Health: {data}")
    if status != 200:
        sys.exit(1)


def _cmd_readiness(args: argparse.Namespace) -> None:
    """Show platform readiness — models, skills, capabilities, MCP, plugins."""
    if getattr(args, "local", False):
        # Local readiness check without a running server.
        os.environ.setdefault("HI_AGENT_ENV", "dev")
        try:
            from hi_agent.config.builder import SystemBuilder  # noqa: PLC0415
            from hi_agent.config.stack import ConfigStack  # noqa: PLC0415

            config_file = getattr(args, "config", None) or os.getenv("HI_AGENT_CONFIG_FILE")
            profile = getattr(args, "profile", None)
            stack = ConfigStack(base_config_path=config_file, profile=profile)
            config = stack.resolve()
            builder = SystemBuilder(config=config, config_stack=stack)
            snapshot = builder.readiness()
        except Exception as exc:
            snapshot = {"ready": False, "health": "error", "error": str(exc)}

        if getattr(args, "json", False):
            print(json.dumps(snapshot, indent=2))
        else:
            ready_str = "READY" if snapshot.get("ready") else "NOT READY"
            health = snapshot.get("health", "unknown")
            print(f"Platform: {ready_str} (health={health})")
            for key in ("models", "skills", "capabilities", "mcp_servers", "plugins"):
                items = snapshot.get(key, [])
                print(f"  {key}: {len(items)} configured")
            subsystems = snapshot.get("subsystems", {})
            for name, info in subsystems.items():
                status = info.get("status", "unknown")
                print(f"  subsystem/{name}: {status}")
        if not snapshot.get("ready"):
            sys.exit(1)
        return

    # Remote: query /ready endpoint
    base = f"http://{args.api_host}:{args.api_port}"
    status, data = _api_request("GET", f"{base}/ready")
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        ready = data.get("ready", False) if isinstance(data, dict) else False
        print(f"Platform: {'READY' if ready else 'NOT READY'}")
    if status not in (200, 503):
        sys.exit(1)
    if status == 503:
        sys.exit(1)


def _cmd_resume(args: argparse.Namespace) -> None:
    """Resume a run from a checkpoint file.

    Supports two modes:
    - ``--checkpoint <path>``: use the file directly.
    - ``--run-id <run_id>``: search for checkpoint in default storage dir.
    """
    import os

    checkpoint_path: str | None = getattr(args, "checkpoint", None)

    if not checkpoint_path:
        run_id = getattr(args, "run_id", None)
        if not run_id:
            print("Error: must specify --checkpoint or --run-id", file=sys.stderr)
            sys.exit(1)
        # Search common locations
        candidates = [
            os.path.join(".checkpoint", f"checkpoint_{run_id}.json"),
            os.path.join(".hi_agent", f"checkpoint_{run_id}.json"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                checkpoint_path = candidate
                break
        if not checkpoint_path:
            print(
                f"Error: checkpoint not found for run {run_id}",
                file=sys.stderr,
            )
            sys.exit(1)

    if not os.path.exists(checkpoint_path):
        print(
            f"Error: checkpoint file not found: {checkpoint_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    import json as _json
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.config.stack import ConfigStack
    from hi_agent.runner import RunExecutor

    config_file = getattr(args, "config", None) or os.getenv("HI_AGENT_CONFIG_FILE")
    profile = getattr(args, "profile", None)
    config_patch_str = getattr(args, "config_patch", None)
    config_patch = _json.loads(config_patch_str) if config_patch_str else None

    stack = ConfigStack(base_config_path=config_file, profile=profile)
    config = stack.resolve(run_patch=config_patch) if config_patch else stack.resolve()
    builder = SystemBuilder(config=config, config_stack=stack)
    kernel = builder.build_kernel()

    result = RunExecutor.resume_from_checkpoint(
        checkpoint_path,
        kernel,
        evolve_engine=builder.build_evolve_engine(),
        harness_executor=builder.build_harness(),
    )

    if getattr(args, "json", False):
        print(json.dumps({"result": str(result)}, indent=2))
    else:
        print(f"Resume completed: {result}")


def _cmd_tools(args: argparse.Namespace) -> None:
    """List and call registered tools via the API server."""
    base = f"http://{args.api_host}:{args.api_port}"
    if args.tools_action == "list":
        status, data = _api_request("GET", f"{base}/tools")
        if getattr(args, "json", False):
            print(json.dumps(data, indent=2))
        else:
            tools = data.get("tools", [])
            for t in tools:
                print(f"  {t['name']}: {t.get('description', '')}")
        if status >= 400:
            sys.exit(1)
    elif args.tools_action == "call":
        import json as _json
        arguments = _json.loads(args.args)
        status, data = _api_request(
            "POST", f"{base}/tools/call", {"name": args.name, "arguments": arguments}
        )
        if getattr(args, "json", False):
            print(json.dumps(data, indent=2))
        else:
            print(data)
        if status >= 400:
            sys.exit(1)
    else:
        print("Usage: hi_agent tools [list|call]")
        sys.exit(1)


def _run_doctor(args) -> None:
    """Run hi-agent doctor diagnostic."""
    from hi_agent.config.builder import SystemBuilder
    from hi_agent.ops.diagnostics import build_doctor_report

    builder = SystemBuilder()
    report = build_doctor_report(builder)

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_doctor_report(report)

    sys.exit(0 if report.status == "ready" else 1)


def _print_doctor_report(report) -> None:
    """Print doctor report in human-readable format."""
    STATUS_SYMBOLS = {"ready": "OK", "degraded": "WARN", "error": "FAIL"}
    symbol = STATUS_SYMBOLS.get(report.status, "?")
    print(f"\nhi-agent doctor -- {symbol} {report.status.upper()}\n")

    if report.blocking:
        print("BLOCKING ISSUES:")
        for issue in report.blocking:
            print(f"  [FAIL] [{issue.subsystem}] {issue.message}")
            print(f"    fix:    {issue.fix}")
            print(f"    verify: {issue.verify}")
        print()

    if report.warnings:
        print("WARNINGS:")
        for issue in report.warnings:
            print(f"  [WARN] [{issue.subsystem}] {issue.message}")
        print()

    if report.info:
        print("INFO:")
        for issue in report.info:
            print(f"  [INFO] [{issue.subsystem}] {issue.message}")
        print()

    if report.next_steps:
        print("NEXT STEPS:")
        for step in report.next_steps:
            print(f"  -> {step}")
        print()


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(description="hi-agent TRACE framework")
    parser.add_argument(
        "--api-host",
        default="127.0.0.1",
        help="API server host for client commands (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=8080,
        help="API server port for client commands (default: 8080)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.add_argument(
        "--prod",
        action="store_true",
        default=False,
        help=(
            "Enable prod mode (sets HI_AGENT_ENV=prod). "
            "Requires real API keys and a real agent-kernel HTTP endpoint. "
            "Without this flag the server defaults to dev mode (heuristic fallback, "
            "in-process kernel), which works out of the box without external dependencies."
        ),
    )

    # run
    run_parser = subparsers.add_parser("run", help="Execute a task")
    run_parser.add_argument("--goal", required=True)
    run_parser.add_argument("--task-family", default="quick_task")
    run_parser.add_argument("--risk-level", default="low")
    run_parser.add_argument("--json", action="store_true", help="Output as JSON")
    run_parser.add_argument(
        "--local",
        action="store_true",
        help="Execute locally via SystemBuilder (no server needed)",
    )
    run_parser.add_argument(
        "--profile",
        required=False,
        default=None,
        help="Config profile to activate (e.g. 'prod', 'dev'). "
             "Loads config.<profile>.json next to --config file.",
    )
    run_parser.add_argument(
        "--config",
        required=False,
        default=None,
        help="Path to base config JSON file. Defaults to HI_AGENT_CONFIG_FILE env var.",
    )
    run_parser.add_argument(
        "--config-patch",
        dest="config_patch",
        required=False,
        default=None,
        help="JSON string of per-run config overrides, e.g. '{\"max_stages\": 5}'.",
    )
    run_parser.add_argument(
        "--profile-id",
        dest="profile_id",
        required=False,
        default=None,
        help="Runtime profile ID to activate (e.g. 'rnd_agent'). "
             "Selects ProfileSpec from the platform ProfileRegistry.",
    )
    run_parser.add_argument(
        "--deadline",
        required=False,
        default=None,
        help="ISO-8601 deadline (e.g. '2099-01-01T00:00:00Z'). "
             "Stages started after this timestamp are aborted with execution_budget_exhausted.",
    )
    run_parser.add_argument(
        "--priority",
        type=int,
        required=False,
        default=None,
        help="Run priority for queue ordering (1=highest, 10=lowest). "
             "Lower integers are dequeued first.",
    )
    run_parser.add_argument(
        "--constraints",
        required=False,
        default=None,
        help="JSON array of constraint strings, e.g. '[\"no external calls\"]'.",
    )
    run_parser.add_argument(
        "--decomposition-strategy",
        dest="decomposition_strategy",
        required=False,
        default=None,
        help="Decomposition strategy hint (e.g. 'sequential', 'parallel'). "
             "Routing hint for TaskOrchestrator; does not change linear execution path.",
    )
    run_parser.add_argument(
        "--acceptance-criteria",
        dest="acceptance_criteria",
        required=False,
        default=None,
        help="JSON array of acceptance criteria, e.g. '[\"required_stage:S3_build\"]'. "
             "Supported patterns: required_stage:<id>, required_artifact:<id>.",
    )
    run_parser.add_argument(
        "--input-refs",
        dest="input_refs",
        required=False,
        default=None,
        help="JSON array of input artifact URIs/IDs, e.g. '[\"artifact://abc\"]'. "
             "PASSTHROUGH: stored and returned but not consumed by default TRACE pipeline.",
    )
    run_parser.add_argument(
        "--environment-scope",
        dest="environment_scope",
        required=False,
        default=None,
        help="JSON array of environment identifiers, e.g. '[\"staging\"]'. "
             "PASSTHROUGH: stored and returned but not consumed by default TRACE pipeline.",
    )
    run_parser.add_argument(
        "--parent-task-id",
        dest="parent_task_id",
        required=False,
        default=None,
        help="Parent task ID for sub-task hierarchy. "
             "PASSTHROUGH: stored and returned but not consumed by default TRACE pipeline.",
    )
    run_parser.add_argument(
        "--budget",
        required=False,
        default=None,
        help="JSON object for execution budget, e.g. "
             "'{\"max_llm_calls\": 10, \"max_wall_clock_seconds\": 300}'.",
    )
    _evolve_group = run_parser.add_mutually_exclusive_group()
    _evolve_group.add_argument(
        "--enable-evolve",
        dest="enable_evolve",
        action="store_true",
        default=False,
        help="Force evolve on (evolve_mode=on). Overrides HI_AGENT_EVOLVE_MODE.",
    )
    _evolve_group.add_argument(
        "--disable-evolve",
        dest="disable_evolve",
        action="store_true",
        default=False,
        help="Force evolve off (evolve_mode=off). Overrides HI_AGENT_EVOLVE_MODE.",
    )

    # doctor
    doctor_parser = subparsers.add_parser("doctor", help="Diagnose platform health")
    doctor_parser.add_argument("--json", action="store_true", help="Output JSON instead of human-readable")

    # status
    status_parser = subparsers.add_parser("status", help="Check run status")
    status_parser.add_argument("--run-id", required=False)
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # health
    health_parser = subparsers.add_parser("health", help="Check system health")
    health_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # readiness
    readiness_parser = subparsers.add_parser(
        "readiness", help="Show platform readiness: models, skills, capabilities, MCP, plugins"
    )
    readiness_parser.add_argument(
        "--local",
        action="store_true",
        help="Check readiness locally (no server needed)",
    )
    readiness_parser.add_argument("--json", action="store_true", help="Output as JSON")
    readiness_parser.add_argument(
        "--config",
        required=False,
        default=None,
        help="Path to config JSON file.",
    )
    readiness_parser.add_argument(
        "--profile",
        required=False,
        default=None,
        help="Config profile to activate.",
    )

    # tools
    tools_parser = subparsers.add_parser("tools", help="List and call registered tools")
    tools_sub = tools_parser.add_subparsers(dest="tools_action")

    tools_list_parser = tools_sub.add_parser("list", help="List registered tools")
    tools_list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    tools_call_parser = tools_sub.add_parser("call", help="Call a tool")
    tools_call_parser.add_argument("--name", required=True, help="Tool name")
    tools_call_parser.add_argument(
        "--args", default="{}", help="JSON arguments"
    )
    tools_call_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # resume
    resume_parser = subparsers.add_parser(
        "resume", help="Resume a run from checkpoint"
    )
    resume_parser.add_argument(
        "--checkpoint", required=False, help="Path to checkpoint file"
    )
    resume_parser.add_argument(
        "--run-id", required=False, help="Run ID to search for checkpoint"
    )
    resume_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    resume_parser.add_argument(
        "--profile",
        required=False,
        default=None,
        help="Config profile to activate (e.g. 'prod', 'dev'). "
             "Loads config.<profile>.json next to --config file.",
    )
    resume_parser.add_argument(
        "--config",
        required=False,
        default=None,
        help="Path to base config JSON file. Defaults to HI_AGENT_CONFIG_FILE env var.",
    )
    resume_parser.add_argument(
        "--config-patch",
        dest="config_patch",
        required=False,
        default=None,
        help="JSON string of per-run config overrides, e.g. '{\"max_stages\": 5}'.",
    )

    return parser


def main() -> None:
    """Entry point for the hi-agent CLI."""
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "serve": _cmd_serve,
        "run": _cmd_run,
        "status": _cmd_status,
        "health": _cmd_health,
        "resume": _cmd_resume,
        "readiness": _cmd_readiness,
        "tools": _cmd_tools,
        "doctor": _run_doctor,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
