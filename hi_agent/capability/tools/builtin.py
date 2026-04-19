"""Real builtin tool handlers — no LLM, no mocks, real I/O."""
from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from hi_agent.capability.registry import CapabilityDescriptor, CapabilityRegistry, CapabilitySpec
from hi_agent.security.path_policy import PathPolicyViolation, safe_resolve
from hi_agent.security.url_policy import URLPolicy, URLPolicyViolation


def file_read_handler(payload: dict) -> dict:
    """Read a file from disk.

    payload: {path: str, base_dir: str = ".", encoding: str = "utf-8"}
    returns: {success: bool, content: str, size: int, error: str | None}
    """
    path = payload.get("path", "")
    encoding = payload.get("encoding", "utf-8")
    if not path:
        return {"success": False, "content": "", "size": 0, "error": "path is required"}
    try:
        base_dir = Path(payload.get("base_dir", ".")).resolve()
        p = safe_resolve(base_dir, path)
        content = p.read_text(encoding=encoding)
        return {"success": True, "content": content, "size": len(content), "error": None}
    except PathPolicyViolation as exc:
        return {"success": False, "content": "", "size": 0, "error": f"Path policy violation: {exc}"}
    except Exception as exc:
        return {"success": False, "content": "", "size": 0, "error": str(exc)}


def file_write_handler(payload: dict) -> dict:
    """Write content to a file.

    payload: {path: str, content: str, base_dir: str = ".", encoding: str = "utf-8"}
    returns: {success: bool, bytes_written: int, error: str | None}
    """
    path = payload.get("path", "")
    content = payload.get("content", "")
    encoding = payload.get("encoding", "utf-8")
    if not path:
        return {"success": False, "bytes_written": 0, "error": "path is required"}
    try:
        base_dir = Path(payload.get("base_dir", ".")).resolve()
        p = safe_resolve(base_dir, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return {"success": True, "bytes_written": len(content.encode(encoding)), "error": None}
    except PathPolicyViolation as exc:
        return {"success": False, "bytes_written": 0, "error": f"Path policy violation: {exc}"}
    except Exception as exc:
        return {"success": False, "bytes_written": 0, "error": str(exc)}


def web_fetch_handler(payload: dict) -> dict:
    """Fetch a URL using stdlib urllib (no extra dependencies).

    payload: {url: str, timeout: float = 15.0}
    returns: {success: bool, content: str, status_code: int, error: str | None}

    URLPolicy is enforced unconditionally regardless of whether this handler is
    called via GovernedToolExecutor or a bare invoker.

    A fresh opener is built per call so that changes to proxy-related env vars
    (``no_proxy`` / ``NO_PROXY``) take effect immediately rather than being
    frozen from module-import time.
    """
    url = payload.get("url", "")
    timeout = float(payload.get("timeout", 15.0))
    if not url:
        return {"success": False, "content": "", "status_code": 0, "error": "url is required"}
    try:
        URLPolicy().validate(url)
    except URLPolicyViolation as e:
        return {"success": False, "error": f"URL policy violation: {e}", "status_code": 0, "content": ""}
    try:
        # Build a fresh opener each call so env-var proxy settings are current.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler())
        req = urllib.request.Request(url, headers={"User-Agent": "hi-agent/1.0"})
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            content = raw.decode("utf-8", errors="replace")
            return {"success": True, "content": content, "status_code": resp.status, "error": None}
    except urllib.error.HTTPError as exc:
        return {"success": False, "content": "", "status_code": exc.code, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "content": "", "status_code": 0, "error": str(exc)}


def shell_exec_handler(payload: dict) -> dict:
    """Execute a shell command via subprocess.

    payload: {command: str, timeout: float = 30.0, cwd: str | None = None}
    returns: {success: bool, stdout: str, stderr: str, returncode: int, error: str | None}

    Security: command must be a string (not list). Shell=True with string input.
    """
    command = payload.get("command", "")
    timeout = float(payload.get("timeout", 30.0))
    cwd = payload.get("cwd", None)
    if not command:
        return {"success": False, "stdout": "", "stderr": "", "returncode": -1, "error": "command is required"}
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
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
            prod_enabled_default=True,
            requires_approval=False,
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
        ),
    ),
]


def register_builtin_tools(registry: CapabilityRegistry, *, profile: str = "dev-smoke") -> None:
    """Register real builtin tool handlers into the registry.

    Args:
        registry: Target capability registry.
        profile: Runtime profile.  When ``profile`` is not a dev/smoke mode
            (i.e. ``"dev-smoke"`` or ``"dev"``), ``shell_exec`` is omitted
            because it is not safe for production deployment.
    """
    _dev_profiles = {"dev-smoke", "dev"}
    for spec in _BUILTIN_TOOLS:
        if spec.name == "shell_exec" and profile not in _dev_profiles:
            continue
        registry.register(spec)
