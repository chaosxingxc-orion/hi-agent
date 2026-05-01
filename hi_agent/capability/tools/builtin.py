"""Real builtin tool handlers — no LLM, no mocks, real I/O."""

from __future__ import annotations

import logging as _logging
import os
import shlex
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry, CapabilitySpec
from hi_agent.security.path_policy import PathPolicyViolation, safe_resolve
from hi_agent.security.url_policy import URLPolicy, URLPolicyViolation


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string (P-1 Provenance timestamp)."""
    return datetime.now(UTC).isoformat()

from hi_agent.observability.metric_counter import Counter

_handler_logger = _logging.getLogger(__name__)
_builtin_errors_total = Counter("hi_agent_builtin_tools_errors_total")


def file_read_handler(payload: dict, *, workspace_root: Path | None = None) -> dict:
    """Read a file from disk.

    payload: {path: str, encoding: str = "utf-8"}
    workspace_root: Caller-supplied workspace base directory.  When None, falls
        back to the current working directory.  ``base_dir`` in the payload is
        ignored and a warning is emitted if present.

    returns: {success: bool, content: str, size: int, error: str | None}
    """
    if "base_dir" in payload:
        _handler_logger.warning(
            "file_read: ignoring payload base_dir='%s'; using workspace context",
            payload["base_dir"],
        )
    path = payload.get("path", "")
    encoding = payload.get("encoding", "utf-8")
    if not path:
        return {"success": False, "content": "", "size": 0, "error": "path is required"}
    try:
        base_dir = workspace_root or Path(".").resolve()
        p = safe_resolve(base_dir, path)
        content = p.read_text(encoding=encoding)
        # P-1: attach Provenance describing the on-disk source of the content.
        provenance = {
            "url": p.resolve().as_uri(),
            "title": p.name,
            "source_type": "file",
            "retrieved_at": _now_iso(),
        }
        return {
            "success": True,
            "content": content,
            "size": len(content),
            "error": None,
            "provenance": provenance,
        }
    except PathPolicyViolation as exc:
        return {
            "success": False,
            "content": "",
            "size": 0,
            "error": f"Path policy violation: {exc}",
        }
    except Exception as exc:
        _builtin_errors_total.inc()
        _handler_logger.warning("builtin.file_read_error error=%s", exc)
        return {"success": False, "content": "", "size": 0, "error": str(exc)}


def file_write_handler(payload: dict, *, workspace_root: Path | None = None) -> dict:
    """Write content to a file.

    payload: {path: str, content: str, encoding: str = "utf-8"}
    workspace_root: Caller-supplied workspace base directory.  When None, falls
        back to the current working directory.  ``base_dir`` in the payload is
        ignored and a warning is emitted if present.

    returns: {success: bool, bytes_written: int, error: str | None}
    """
    if "base_dir" in payload:
        _handler_logger.warning(
            "file_write: ignoring payload base_dir='%s'; using workspace context",
            payload["base_dir"],
        )
    path = payload.get("path", "")
    content = payload.get("content", "")
    encoding = payload.get("encoding", "utf-8")
    if not path:
        return {"success": False, "bytes_written": 0, "error": "path is required"}
    try:
        base_dir = workspace_root or Path(".").resolve()
        p = safe_resolve(base_dir, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return {"success": True, "bytes_written": len(content.encode(encoding)), "error": None}
    except PathPolicyViolation as exc:
        return {"success": False, "bytes_written": 0, "error": f"Path policy violation: {exc}"}
    except Exception as exc:
        _builtin_errors_total.inc()
        _handler_logger.warning("builtin.file_write_error error=%s", exc)
        return {"success": False, "bytes_written": 0, "error": str(exc)}


def web_fetch_handler(payload: dict) -> dict:
    """Fetch a URL using stdlib urllib (no extra dependencies).

    payload: {url: str, timeout: float = 15.0}
    returns: {success: bool, content: str, status_code: int, error: str | None}

    URLPolicy is enforced unconditionally regardless of whether this handler is
    called via GovernedToolExecutor or a bare invoker.  Redirects are re-validated
    through URLPolicy to prevent SSRF via open-redirect chains.

    A fresh opener is built per call so that changes to proxy-related env vars
    (``no_proxy`` / ``NO_PROXY``) take effect immediately rather than being
    frozen from module-import time.
    """
    url = payload.get("url", "")
    timeout = float(payload.get("timeout", 15.0))
    if not url:
        return {"success": False, "content": "", "status_code": 0, "error": "url is required"}
    _policy = URLPolicy()
    try:
        _policy.validate(url)
    except URLPolicyViolation as e:
        return {
            "success": False,
            "error": f"URL policy violation: {e}",
            "status_code": 0,
            "content": "",
        }
    try:

        class _NoUnsafeRedirect(urllib.request.HTTPRedirectHandler):
            """Block redirects to URLs that fail URLPolicy validation."""

            def redirect_request(
                self,
                req: urllib.request.Request,
                fp: object,
                code: int,
                msg: str,
                headers: object,
                newurl: str,
            ) -> urllib.request.Request | None:
                try:
                    _policy.validate(newurl)
                except URLPolicyViolation as exc:
                    raise urllib.error.URLError(f"Redirect blocked by URL policy: {exc}") from exc
                return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]  expiry_wave: Wave 28

        # Build a fresh opener each call so env-var proxy settings are current.
        # ProxyHandler({}) disables system proxy to prevent proxy-based SSRF.
        opener = urllib.request.build_opener(
            _NoUnsafeRedirect(),
            urllib.request.ProxyHandler({}),
        )
        req = urllib.request.Request(url, headers={"User-Agent": "hi-agent/1.0"})
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            content = raw.decode("utf-8", errors="replace")
            final_url = getattr(resp, "url", None) or url
            # P-1: attach Provenance describing the fetched web source.
            provenance = {
                "url": final_url,
                "title": "",
                "source_type": "web",
                "retrieved_at": _now_iso(),
            }
            return {
                "success": True,
                "content": content,
                "status_code": resp.status,
                "error": None,
                "provenance": provenance,
            }
    except urllib.error.HTTPError as exc:
        return {"success": False, "content": "", "status_code": exc.code, "error": str(exc)}
    except Exception as exc:
        _builtin_errors_total.inc()
        _handler_logger.warning("builtin.web_fetch_error error=%s", exc)
        return {"success": False, "content": "", "status_code": 0, "error": str(exc)}


def shell_exec_handler(payload: dict) -> dict:
    """Execute a shell command via subprocess.

    payload: {command: str | list, timeout: int = 30, cwd: str = "."}
    returns: {success: bool, stdout: str, stderr: str, returncode: int, error: str | None}

    Security: uses shell=False with an argv list to prevent shell injection.
    """
    command = payload.get("command", "")
    timeout = min(int(payload.get("timeout", 30)), 120)
    cwd_raw = payload.get("cwd", ".")

    argv = shlex.split(command) if isinstance(command, str) else [str(a) for a in command]
    if not argv:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": "empty command",
        }

    base_cwd = Path(".").resolve()
    try:
        safe_cwd = safe_resolve(base_cwd, cwd_raw) if cwd_raw != "." else base_cwd
    except (ValueError, PermissionError) as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": f"invalid cwd: {e}",
        }

    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=safe_cwd,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "error": f"command timed out after {timeout}s",
        }
    except Exception as exc:
        _builtin_errors_total.inc()
        _handler_logger.warning("builtin.shell_exec_error error=%s", exc)
        return {"success": False, "stdout": "", "stderr": "", "returncode": -1, "error": str(exc)}


_BUILTIN_TOOLS = [
    CapabilitySpec(
        name="file_read",
        handler=file_read_handler,
        description="Read a file from disk and return its content.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path"},
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["path"],
        },
        descriptor=CapabilityDescriptor(
            name="file_read",
            risk_class="filesystem_read",
            side_effect_class="filesystem_read",
            prod_enabled_default=True,
            requires_approval=False,
            maturity_level="L3",
        ),
    ),
    CapabilitySpec(
        name="file_write",
        handler=file_write_handler,
        description="Write content to a file, creating parent directories if needed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "encoding": {"type": "string", "default": "utf-8"},
            },
            "required": ["path", "content"],
        },
        descriptor=CapabilityDescriptor(
            name="file_write",
            risk_class="filesystem_write",
            side_effect_class="filesystem_write",
            prod_enabled_default=True,
            requires_approval=True,
            maturity_level="L3",
        ),
    ),
    CapabilitySpec(
        name="web_fetch",
        handler=web_fetch_handler,
        description="Fetch a URL and return its text content.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "timeout": {"type": "number", "default": 15.0},
            },
            "required": ["url"],
        },
        descriptor=CapabilityDescriptor(
            name="web_fetch",
            risk_class="network",
            side_effect_class="network_read",
            # SA-5 (self-audit 2026-04-21): network calls are exfil-class actions.
            # prod_enabled_default stays True so the capability is discoverable,
            # but requires_approval=True gates every invocation through the
            # harness governance pipeline. Operators that want unattended
            # fetches can opt out via profile policy.
            prod_enabled_default=True,
            requires_approval=True,
            maturity_level="L2",
        ),
    ),
    CapabilitySpec(
        name="shell_exec",
        handler=shell_exec_handler,
        description="Execute a shell command and return stdout, stderr, and exit code.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number", "default": 30.0},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
        },
        descriptor=CapabilityDescriptor(
            name="shell_exec",
            risk_class="shell",
            side_effect_class="shell_exec",
            prod_enabled_default=False,
            requires_approval=True,
            maturity_level="L2",
            available_in_prod=False,
        ),
    ),
]


def get_builtin_capabilities() -> list[CapabilitySpec]:
    """Return the list of all builtin CapabilitySpec objects (unfiltered).

    Unlike register_builtin_tools(), this does not apply profile or env-var
    gates — callers receive the full list for introspection purposes.
    """
    return list(_BUILTIN_TOOLS)


def register_builtin_tools(registry: CapabilityRegistry, *, profile: str = "dev-smoke") -> None:
    """Register real builtin tool handlers into the registry.

    Args:
        registry: Target capability registry.
        profile: Runtime profile.  When ``profile`` is not a dev/smoke mode
            (i.e. ``"dev-smoke"`` or ``"dev"``), ``shell_exec`` is omitted
            because it is not safe for production deployment.

    Security: ``shell_exec`` is additionally gated behind the env var
    ``HI_AGENT_ENABLE_SHELL_EXEC=true`` even in dev profiles.
    """
    _dev_profiles = {"dev-smoke", "dev"}
    _shell_exec_enabled = os.getenv("HI_AGENT_ENABLE_SHELL_EXEC", "").lower() == "true"
    for spec in _BUILTIN_TOOLS:
        if spec.name == "shell_exec" and (profile not in _dev_profiles or not _shell_exec_enabled):
            continue
        registry.register(spec)


# Alias used by some callers (register_builtin_capabilities is the legacy name).
register_builtin_capabilities = register_builtin_tools
