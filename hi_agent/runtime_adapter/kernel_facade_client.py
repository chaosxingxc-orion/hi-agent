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

    def open_stage(self, run_id: str, stage_id: str) -> None:
        """Open stage in runtime."""
        if self._mode == "direct":
            self._direct_call("open_stage", stage_id, run_id)
        else:
            self._http_post(f"/runs/{run_id}/stages/{stage_id}/open", {})

    def mark_stage_state(self, run_id: str, stage_id: str, target: StageState) -> None:
        """Update stage lifecycle state in runtime."""
        target_value = target.value if isinstance(target, StageState) else str(target)
        if self._mode == "direct":
            self._direct_call("mark_stage_state", run_id, stage_id, target_value)
        else:
            self._http_put(
                f"/runs/{run_id}/stages/{stage_id}/state",
                {"state": target_value},
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
            run_id = content.get("run_id", "unknown") if isinstance(content, dict) else "unknown"
            resp = self._http_post(
                f"/runs/{run_id}/task-views",
                {"task_view_id": task_view_id, **content},
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
            self._http_put(
                f"/task-views/{task_view_id}/decision",
                {"decision_ref": decision_ref},
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
            resp = self._http_post(
                "/runs",
                {"run_kind": task_id, "input_json": {"task_id": task_id}},
            )
            return resp["run_id"]

    def query_run(self, run_id: str) -> dict[str, Any]:
        """Return run lifecycle snapshot."""
        if self._mode == "direct":
            result = self._direct_call("query_run", run_id)
            if isinstance(result, dict):
                return result
            import dataclasses  # noqa: PLC0415
            if dataclasses.is_dataclass(result) and not isinstance(result, type):
                return dataclasses.asdict(result)
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
                {"signal_type": signal, "signal_payload": payload or {}},
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
            import dataclasses  # noqa: PLC0415
            if dataclasses.is_dataclass(result) and not isinstance(result, type):
                return dataclasses.asdict(result)
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
            try:
                async for event in method(run_id):
                    if isinstance(event, dict):
                        yield event
                    elif hasattr(event, "__dict__"):
                        yield dict(event.__dict__)
                    else:
                        yield {"event": str(event)}
            except RuntimeAdapterBackendError:
                raise
            except Exception as exc:
                raise RuntimeAdapterBackendError("stream_run_events", cause=exc) from exc
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
                f"/runs/{run_id}/branches",
                {"stage_id": stage_id, "branch_id": branch_id},
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
            body: dict[str, Any] = {"state": state}
            if failure_code is not None:
                body["failure_code"] = failure_code
            self._http_put(f"/runs/{run_id}/branches/{branch_id}/state", body)

    # ------------------------------------------------------------------
    # Human gate
    # ------------------------------------------------------------------

    def open_human_gate(self, request: HumanGateRequest) -> None:
        """Open a human gate and block until resolved or timed out."""
        if self._mode == "direct":
            self._direct_call("open_human_gate", request)
        else:
            self._http_post(
                f"/runs/{request.run_id}/human-gates",
                {
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
            run_id = getattr(request, "run_id", None) or ""
            self._http_post(
                f"/runs/{run_id}/approval",
                {
                    "gate_ref": request.gate_ref,
                    "decision": request.decision,
                    "reviewer_id": getattr(request, "reviewer_id", None),
                    "comment": getattr(request, "comment", None),
                },
            )

    def resolve_escalation(
        self,
        run_id: str,
        *,
        resolution_notes: str | None = None,
        caused_by: str | None = None,
    ) -> None:
        """Resume a run stuck in waiting_external after human_escalation."""
        if self._mode == "direct":
            # keyword-only args: cannot route through _direct_call(); drive coroutine inline
            import asyncio  # noqa: PLC0415

            try:
                coro = self._facade.resolve_escalation(
                    run_id,
                    resolution_notes=resolution_notes,
                    caused_by=caused_by,
                )
                if asyncio.iscoroutine(coro):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop is not None and loop.is_running():
                        import threading  # noqa: PLC0415

                        holder: dict[str, Any] = {}

                        def _runner() -> None:
                            try:
                                holder["result"] = asyncio.run(coro)
                            except Exception as exc:  # noqa: BLE001
                                holder["error"] = exc

                        thread = threading.Thread(target=_runner, daemon=True)
                        thread.start()
                        thread.join()
                        if "error" in holder:
                            raise holder["error"]  # type: ignore[misc]
                    else:
                        asyncio.run(coro)
            except RuntimeAdapterBackendError:
                raise
            except Exception as exc:
                raise RuntimeAdapterBackendError("resolve_escalation", cause=exc) from exc
        else:
            body: dict[str, Any] = {}
            if resolution_notes:
                body["resolution_notes"] = resolution_notes
            if caused_by:
                body["caused_by"] = caused_by
            self._http_post(f"/runs/{run_id}/resolve-escalation", body)

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

    def query_run_postmortem(self, run_id: str) -> Any:
        """Call query_run_postmortem via HTTP client or direct facade."""
        if self._mode == "direct":
            return self._direct_call("query_run_postmortem", run_id)
        return self._http_get(f"/runs/{run_id}/postmortem")

    def spawn_child_run(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Spawn a child run under parent_run_id."""
        if self._mode == "direct":
            result = self._direct_call("spawn_child_run", parent_run_id, task_id, config)
            if hasattr(result, "child_run_id") and result.child_run_id:
                return result.child_run_id
            if isinstance(result, str) and result.strip():
                return result
            raise RuntimeAdapterBackendError(
                "spawn_child_run",
                cause=ValueError("spawn_child_run returned no child_run_id"),
            )
        body: dict[str, Any] = {"task_id": task_id}
        if config:
            body["config"] = config
        resp = self._http_post(f"/runs/{parent_run_id}/children", body)
        child_id = resp.get("child_run_id", "")
        if not child_id:
            raise RuntimeAdapterBackendError(
                "spawn_child_run",
                cause=ValueError("HTTP spawn_child_run returned no child_run_id"),
            )
        return child_id

    def query_child_runs(self, parent_run_id: str) -> list[dict[str, Any]]:
        """Return child run summaries for the given parent run."""
        if self._mode == "direct":
            result = self._direct_call("query_child_runs", parent_run_id)
            if isinstance(result, list):
                return [
                    item if isinstance(item, dict) else (
                        {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
                        if hasattr(item, "__dict__") else {"child_run_id": str(item)}
                    )
                    for item in result
                ]
            return []
        resp = self._http_get(f"/runs/{parent_run_id}/children")
        return resp.get("children", []) if isinstance(resp, dict) else []

    async def spawn_child_run_async(
        self,
        parent_run_id: str,
        task_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Async version of spawn_child_run via asyncio.to_thread."""
        import asyncio  # noqa: PLC0415
        return await asyncio.to_thread(self.spawn_child_run, parent_run_id, task_id, config)

    async def query_child_runs_async(self, parent_run_id: str) -> list[dict[str, Any]]:
        """Async version of query_child_runs via asyncio.to_thread."""
        import asyncio  # noqa: PLC0415
        return await asyncio.to_thread(self.query_child_runs, parent_run_id)

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
                    import threading  # noqa: PLC0415

                    holder: dict[str, Any] = {}

                    def _runner() -> None:
                        try:
                            holder["result"] = asyncio.run(result)
                        except Exception as exc:  # noqa: BLE001
                            holder["error"] = exc

                    thread = threading.Thread(target=_runner, daemon=True)
                    thread.start()
                    thread.join()
                    if "error" in holder:
                        raise holder["error"]
                    return holder.get("result")
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

    def _http_put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """PUT JSON to agent-kernel HTTP server."""
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="PUT",
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
