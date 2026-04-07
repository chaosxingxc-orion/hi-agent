"""Real adapter to agent-kernel's KernelFacade.

Supports two modes:
- direct: Import and use KernelFacade in-process (development)
- http: Call agent-kernel via HTTP API (production)

Zero external dependencies -- HTTP mode uses stdlib urllib.request.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any

from hi_agent.contracts import StageState
from hi_agent.contracts.requests import ApprovalRequest, HumanGateRequest
from hi_agent.runtime_adapter.errors import RuntimeAdapterBackendError


class KernelFacadeClient:
    """Adapter bridging hi-agent's RuntimeAdapter protocol to agent-kernel's KernelFacade.

    In direct mode, wraps a KernelFacade instance (or any compatible object).
    In http mode, makes HTTP calls to agent-kernel's REST server.
    """

    def __init__(
        self,
        mode: str = "direct",
        facade: Any | None = None,
        base_url: str = "http://localhost:9090",
        timeout_seconds: int = 30,
    ) -> None:
        """Initialize the adapter.

        Args:
            mode: ``"direct"`` for in-process calls, ``"http"`` for REST.
            facade: A KernelFacade instance for direct mode.  Ignored in
                http mode.
            base_url: Base URL of the agent-kernel HTTP server.  Only used
                in http mode.
            timeout_seconds: HTTP request timeout in seconds.
        """
        if mode not in ("direct", "http"):
            raise ValueError(f"mode must be 'direct' or 'http', got '{mode}'")
        self._mode = mode
        self._facade = facade
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

        if mode == "direct" and facade is None:
            facade = self._try_import_facade()
            if facade is None:
                raise ImportError(
                    "agent-kernel is not importable. Install it or provide "
                    "a facade instance explicitly. For HTTP mode, use "
                    "mode='http' instead."
                )
            self._facade = facade

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def open_stage(self, stage_id: str) -> None:
        """Open stage in runtime."""
        if self._mode == "direct":
            self._direct_call("open_stage", stage_id)
        else:
            self._http_post("/stages/open", {"stage_id": stage_id})

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        """Update stage lifecycle state in runtime."""
        target_value = target.value if isinstance(target, StageState) else str(target)
        if self._mode == "direct":
            self._direct_call("mark_stage_state", stage_id, target_value)
        else:
            self._http_post(
                "/stages/mark_state",
                {"stage_id": stage_id, "target": target_value},
            )

    # ------------------------------------------------------------------
    # Task view
    # ------------------------------------------------------------------

    def record_task_view(self, task_view_id: str, content: dict[str, Any]) -> str:
        """Persist task view payload and return stored task view ID."""
        if self._mode == "direct":
            result = self._direct_call("record_task_view", task_view_id, content)
            return result if isinstance(result, str) else task_view_id
        else:
            resp = self._http_post(
                "/task_views/record",
                {"task_view_id": task_view_id, "content": content},
            )
            return resp.get("task_view_id", task_view_id)

    def bind_task_view_to_decision(
        self, task_view_id: str, decision_ref: str
    ) -> None:
        """Persist immutable binding between task-view and decision reference."""
        if self._mode == "direct":
            self._direct_call(
                "bind_task_view_to_decision", task_view_id, decision_ref
            )
        else:
            self._http_post(
                "/task_views/bind_decision",
                {"task_view_id": task_view_id, "decision_ref": decision_ref},
            )

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(self, task_id: str) -> str:
        """Start a run for task and return run ID."""
        if self._mode == "direct":
            result = self._direct_call("start_run", task_id)
            if isinstance(result, str):
                return result
            # KernelFacade returns StartRunResponse; extract run_id.
            if hasattr(result, "run_id"):
                return result.run_id
            raise RuntimeAdapterBackendError(
                "start_run",
                cause=ValueError("start_run did not return a run_id"),
            )
        else:
            resp = self._http_post("/runs/start", {"task_id": task_id})
            return resp["run_id"]

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Return run lifecycle snapshot."""
        if self._mode == "direct":
            result = self._direct_call("query_run", run_id)
            if isinstance(result, dict):
                return result
            if hasattr(result, "__dict__"):
                return dict(result.__dict__)
            raise RuntimeAdapterBackendError(
                "query_run",
                cause=ValueError("query_run did not return a dict"),
            )
        else:
            return self._http_get(f"/runs/{run_id}")

    def cancel_run(self, run_id: str, reason: str) -> None:
        """Cancel run with reason."""
        if self._mode == "direct":
            self._direct_call("cancel_run", run_id, reason)
        else:
            self._http_post(
                f"/runs/{run_id}/cancel", {"reason": reason}
            )

    def resume_run(self, run_id: str) -> None:
        """Resume a suspended or cancelled run."""
        if self._mode == "direct":
            self._direct_call("resume_run", run_id)
        else:
            self._http_post(f"/runs/{run_id}/resume", {})

    def signal_run(
        self, run_id: str, signal: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Push an external signal to a run."""
        if self._mode == "direct":
            self._direct_call("signal_run", run_id, signal, payload or {})
        else:
            self._http_post(
                f"/runs/{run_id}/signal",
                {"signal": signal, "payload": payload or {}},
            )

    # ------------------------------------------------------------------
    # Trace runtime
    # ------------------------------------------------------------------

    def query_trace_runtime(self, run_id: str) -> dict[str, Any]:
        """Return trace runtime snapshot for diagnostics/reconcile."""
        if self._mode == "direct":
            result = self._direct_call("query_trace_runtime", run_id)
            if isinstance(result, dict):
                return result
            if hasattr(result, "__dict__"):
                return dict(result.__dict__)
            raise RuntimeAdapterBackendError(
                "query_trace_runtime",
                cause=ValueError("query_trace_runtime did not return a dict"),
            )
        else:
            return self._http_get(f"/runs/{run_id}/trace")

    async def stream_run_events(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield run events as an async stream."""
        if self._mode == "direct":
            method = getattr(self._facade, "stream_run_events", None)
            if not callable(method):
                raise RuntimeAdapterBackendError(
                    "stream_run_events",
                    cause=NotImplementedError(
                        "facade does not implement 'stream_run_events'"
                    ),
                )
            async for event in method(run_id):
                if isinstance(event, dict):
                    yield event
                elif hasattr(event, "__dict__"):
                    yield dict(event.__dict__)
                else:
                    yield {"event": str(event)}
        else:
            # HTTP mode: single GET request, return events as a list.
            # True streaming would require SSE; for now we fetch all events.
            resp = self._http_get(f"/runs/{run_id}/events")
            events = resp.get("events", []) if isinstance(resp, dict) else resp
            for event in events:
                yield event

    # ------------------------------------------------------------------
    # Branch lifecycle
    # ------------------------------------------------------------------

    def open_branch(self, run_id: str, stage_id: str, branch_id: str) -> None:
        """Create branch lifecycle record."""
        if self._mode == "direct":
            self._direct_call("open_branch", run_id, stage_id, branch_id)
        else:
            self._http_post(
                "/branches/open",
                {
                    "run_id": run_id,
                    "stage_id": stage_id,
                    "branch_id": branch_id,
                },
            )

    def mark_branch_state(
        self,
        run_id: str,
        stage_id: str,
        branch_id: str,
        state: str,
        failure_code: str | None = None,
    ) -> None:
        """Update branch lifecycle state."""
        if self._mode == "direct":
            self._direct_call(
                "mark_branch_state", run_id, stage_id, branch_id, state, failure_code
            )
        else:
            body: dict[str, Any] = {
                "run_id": run_id,
                "stage_id": stage_id,
                "branch_id": branch_id,
                "state": state,
            }
            if failure_code is not None:
                body["failure_code"] = failure_code
            self._http_post("/branches/mark_state", body)

    # ------------------------------------------------------------------
    # Human gate
    # ------------------------------------------------------------------

    def open_human_gate(self, request: HumanGateRequest) -> None:
        """Open a human gate and block until resolved or timed out."""
        if self._mode == "direct":
            self._direct_call("open_human_gate", request)
        else:
            self._http_post(
                "/gates/open",
                {
                    "run_id": request.run_id,
                    "gate_type": request.gate_type,
                    "gate_ref": request.gate_ref,
                    "context": request.context,
                    "timeout_s": request.timeout_s,
                },
            )

    def submit_approval(self, request: ApprovalRequest) -> None:
        """Submit an approval or rejection for a pending human gate."""
        if self._mode == "direct":
            self._direct_call("submit_approval", request)
        else:
            self._http_post(
                "/gates/approve",
                {
                    "gate_ref": request.gate_ref,
                    "decision": request.decision,
                    "reviewer_id": getattr(request, "reviewer_id", None),
                    "comment": getattr(request, "comment", None),
                },
            )

    # ------------------------------------------------------------------
    # Plan & manifest
    # ------------------------------------------------------------------

    def get_manifest(self) -> dict[str, Any]:
        """Return runtime capabilities/metadata."""
        if self._mode == "direct":
            result = self._direct_call("get_manifest")
            if isinstance(result, dict):
                return result
            if hasattr(result, "__dict__"):
                return dict(result.__dict__)
            return {}
        else:
            return self._http_get("/manifest")

    def submit_plan(self, run_id: str, plan: dict[str, Any]) -> None:
        """Persist execution plan for run."""
        if self._mode == "direct":
            self._direct_call("submit_plan", run_id, plan)
        else:
            self._http_post(
                f"/runs/{run_id}/plan", {"plan": plan}
            )

    # ------------------------------------------------------------------
    # Internal: direct mode helpers
    # ------------------------------------------------------------------

    def _direct_call(self, method_name: str, *args: Any) -> Any:
        """Invoke a method on the facade with error wrapping.

        Handles both sync and async facade methods transparently.
        """
        import asyncio

        method = getattr(self._facade, method_name, None)
        if not callable(method):
            raise RuntimeAdapterBackendError(
                method_name,
                cause=NotImplementedError(
                    f"facade does not implement '{method_name}'"
                ),
            )
        try:
            result = method(*args)
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None and loop.is_running():
                    return None
                return asyncio.run(result)
            return result
        except RuntimeAdapterBackendError:
            raise
        except Exception as exc:
            raise RuntimeAdapterBackendError(
                method_name, cause=exc
            ) from exc

    @staticmethod
    def _try_import_facade() -> Any:
        """Try to import and instantiate a local KernelFacade.

        Returns None if agent-kernel is not importable.
        """
        try:
            from agent_kernel.runtime.kernel_runtime import (
                KernelRuntime,
                KernelRuntimeConfig,
            )
            from agent_kernel.substrate.local.adaptor import (
                LocalSubstrateConfig,
            )
        except ImportError:
            return None

        import asyncio

        config = KernelRuntimeConfig(
            substrate=LocalSubstrateConfig(),
            event_log_backend="in_memory",
        )
        runtime = asyncio.run(KernelRuntime.start(config))
        return runtime.facade

    # ------------------------------------------------------------------
    # Internal: HTTP mode helpers
    # ------------------------------------------------------------------

    def _http_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to agent-kernel HTTP server."""
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            raise RuntimeAdapterBackendError(
                path, cause=exc
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeAdapterBackendError(
                path, cause=exc
            ) from exc

    def _http_get(self, path: str) -> dict[str, Any]:
        """GET JSON from agent-kernel HTTP server."""
        url = f"{self._base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            raise RuntimeAdapterBackendError(
                path, cause=exc
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeAdapterBackendError(
                path, cause=exc
            ) from exc
