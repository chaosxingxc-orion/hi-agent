"""Action dispatch helpers for RunExecutor."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hi_agent.contracts import deterministic_id
from hi_agent.gate_protocol import GatePendingError
from hi_agent.observability.silent_degradation import record_silent_degradation

_logger = logging.getLogger(__name__)


@dataclass
class ActionDispatchContext:
    run_id: str
    current_stage: str
    action_seq: int
    invoker: Any
    harness_executor: Any | None
    runner_role: str | None
    invoker_accepts_role: bool
    invoker_accepts_metadata: bool
    hook_manager: Any | None
    capability_provenance_store: dict[str, list[dict]]
    force_fail_actions: set[str]
    action_max_retries: int
    record_event_fn: Callable[[str, dict], None]
    emit_observability_fn: Callable[[str, dict[str, object]], None]
    nudge_check_fn: Callable[[str, str], None] | None


class ActionDispatcher:
    def __init__(self, ctx: ActionDispatchContext) -> None:
        self._ctx = ctx

    def _invoke_capability_via_hooks(self, proposal: object, payload: dict) -> dict:
        """Invoke capability through ExecutionHookManager pre/post tool hooks.

        When _hook_manager is available, wraps the raw capability invocation
        so that all registered pre_tool and post_tool hooks fire around it.
        Falls back to direct invocation if hooks are unavailable.
        """
        if self._ctx.hook_manager is None:
            return self._invoke_capability(proposal, payload)

        try:
            from hi_agent.middleware.hooks import ToolCallContext

            tool_ctx = ToolCallContext(
                run_id=self._ctx.run_id,
                stage_id=payload.get("stage_id", self._ctx.current_stage or ""),
                tool_name=str(getattr(proposal, "action_kind", "unknown")),
                tool_input=payload,
                turn_number=self._ctx.action_seq,
            )

            def _call_fn(_ctx: ToolCallContext) -> str:
                result = self._invoke_capability(proposal, payload)
                # Store result so we can return it after hook chain completes
                _call_fn._last_result = result  # type: ignore[attr-defined]  expiry_wave: permanent
                return str(result.get("success", False))

            _call_fn._last_result = {}  # type: ignore[attr-defined]  expiry_wave: permanent

            # Run async hook chain via the process-wide SyncBridge (Rule 12) —
            # all hook invocations share one durable event loop so async
            # resources used by hooks (HTTP clients, cache connections) are
            # not torn down between calls.
            from hi_agent.runtime.sync_bridge import get_bridge

            # SA-7 (self-audit 2026-04-21): bound the wait so a hung hook
            # surfaces as TimeoutError instead of a silent wedge.
            _HOOK_TIMEOUT = 120.0  # noqa: N806 — module-level constant semantics  expiry_wave: permanent
            get_bridge().call_sync(
                self._ctx.hook_manager.wrap_tool_call(tool_ctx, _call_fn),
                timeout=_HOOK_TIMEOUT,
            )

            return _call_fn._last_result  # type: ignore[attr-defined]  expiry_wave: permanent
        except GatePendingError:
            # Flow-control: a tool raised a gate request. Must propagate so
            # the runner can suspend the run; never swallow into fallback.
            raise
        except Exception as exc:
            _logger.debug(
                "runner.hook_wrap_failed run_id=%s stage_id=%s error=%s",
                self._ctx.run_id,
                payload.get("stage_id", ""),
                exc,
            )
            return self._invoke_capability(proposal, payload)

    def _invoke_capability(self, proposal: object, payload: dict) -> dict:
        """Invoke capability with optional role and action metadata propagation.

        When a harness_executor is configured, actions are routed through the
        harness governance pipeline instead of direct capability invocation.
        """
        if self._ctx.harness_executor is not None:
            return self._invoke_via_harness(proposal, payload)

        kwargs: dict[str, object] = {}
        if self._ctx.invoker_accepts_role:
            kwargs["role"] = self._ctx.runner_role
        if self._ctx.invoker_accepts_metadata:
            kwargs["metadata"] = {
                "run_id": self._ctx.run_id,
                "stage_id": payload["stage_id"],
                "action_kind": payload["action_kind"],
                "branch_id": payload["branch_id"],
                "seq": payload["seq"],
                "attempt": payload["attempt"],
            }
        if kwargs:
            return self._ctx.invoker.invoke(proposal.action_kind, payload, **kwargs)
        return self._ctx.invoker.invoke(proposal.action_kind, payload)

    @staticmethod
    def _parse_invoker_role(constraints: list[str]) -> str | None:
        """Extract invoker role from constraints.

        Supported format: `invoker_role:<role_name>`.
        """
        for item in constraints:
            if not item.startswith("invoker_role:"):
                continue
            role = item.split(":", 1)[1].strip()
            if role:
                return role
        return None

    def _execute_action_with_retry(
        self,
        stage_id: str,
        proposal: object,
        *,
        upstream_artifact_ids: list[str] | None = None,
    ) -> tuple[bool, dict | None, int]:
        """Execute one action with retry semantics.

        Args:
            stage_id: Current stage identifier.
            proposal: Route proposal for the action.
            upstream_artifact_ids: Artifact IDs produced by prior actions in
                this stage.  Threaded through to the harness so artifact
                lineage is recorded on outputs.

        Returns:
          (success, result_payload_or_none, final_attempt_number)
        """
        max_attempts = self._ctx.action_max_retries + 1

        for attempt in range(1, max_attempts + 1):
            payload = {
                "run_id": self._ctx.run_id,
                "stage_id": stage_id,
                "branch_id": proposal.branch_id,
                "action_kind": proposal.action_kind,
                "seq": self._ctx.action_seq,
                "attempt": attempt,
                "should_fail": (
                    proposal.action_kind in self._ctx.force_fail_actions
                    or stage_id in self._ctx.force_fail_actions
                ),
                "upstream_artifact_ids": upstream_artifact_ids or [],
            }
            self._ctx.record_event_fn("ActionPlanned", payload)

            # Emit tool_call at state transition boundary (first attempt only).
            if attempt == 1:
                self._ctx.record_event_fn(
                    "tool_call",
                    {
                        "run_id": self._ctx.run_id,
                        "stage_id": stage_id,
                        "tool_name": str(getattr(proposal, "action_kind", "unknown")),
                        "seq": self._ctx.action_seq,
                    },
                )
                try:
                    from hi_agent.observability.spine_events import (
                        emit_capability_handler,
                        emit_tool_call,
                    )
                    _tool_name = str(getattr(proposal, "action_kind", "unknown"))
                    emit_tool_call(
                        tool_name=_tool_name,
                        tenant_id="",
                        profile_id="",
                    )
                    emit_capability_handler(
                        tool_name=_tool_name,
                        run_id=self._ctx.run_id,
                    )
                except Exception as exc:
                    record_silent_degradation(
                        component="execution.action_dispatcher.ActionDispatcher._dispatch",
                        reason="audit_emit_tool_call_failed",
                        exc=exc,
                    )

            try:
                # Fix-4: route through ExecutionHookManager (pre/post tool hooks)
                result = self._invoke_capability_via_hooks(proposal, payload)
                # W2-002: collect capability provenance for StageProvenance derivation
                if isinstance(result, dict) and "_provenance" in result:
                    self._ctx.capability_provenance_store.setdefault(stage_id, []).append(
                        result["_provenance"]
                    )
                success = bool(result.get("success", False))
                self._ctx.record_event_fn(
                    "ActionExecuted",
                    {
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "success": success,
                    },
                )
                self._ctx.emit_observability_fn(
                    "action_executed",
                    {
                        "run_id": self._ctx.run_id,
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "success": success,
                    },
                )
                # Fix-5: nudge check after each completed action attempt
                action_text = str(result) if result else ""
                self._ctx.nudge_check_fn(stage_id, action_text)
                if success:
                    return True, result, attempt
                if attempt == max_attempts:
                    return False, result, attempt
            except Exception as exc:
                self._ctx.record_event_fn(
                    "ActionExecutionFailed",
                    {
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                self._ctx.emit_observability_fn(
                    "action_executed",
                    {
                        "run_id": self._ctx.run_id,
                        "stage_id": stage_id,
                        "action_kind": proposal.action_kind,
                        "attempt": attempt,
                        "success": False,
                        "error": str(exc),
                    },
                )
                if attempt == max_attempts:
                    return False, None, attempt

        return False, None, max_attempts

    def _invoke_via_harness(self, proposal: object, payload: dict) -> dict:
        """Route action through HarnessExecutor and convert result to dict.

        Args:
            proposal: Route proposal with action_kind and branch_id.
            payload: Action payload dict.

        Returns:
            Dict in the format the runner expects from capability invocation.
        """
        from hi_agent.harness.contracts import ActionSpec, ActionState, SideEffectClass

        spec = ActionSpec(
            action_id=deterministic_id(
                self._ctx.run_id,
                payload["stage_id"],
                payload["branch_id"],
                str(payload["seq"]),
            ),
            action_type="mutate",
            capability_name=proposal.action_kind,
            payload=payload,
            side_effect_class=SideEffectClass(getattr(proposal, "side_effect_class", "read_only"))
            if hasattr(proposal, "side_effect_class")
            and proposal.side_effect_class in {e.value for e in SideEffectClass}
            else SideEffectClass.READ_ONLY,
            upstream_artifact_ids=list(payload.get("upstream_artifact_ids") or []),
        )

        result = self._ctx.harness_executor.execute(spec)

        success = result.state == ActionState.SUCCEEDED
        output = result.output if isinstance(result.output, dict) else {}
        return {
            "success": success,
            "score": output.get("score", 0.0),
            "evidence_hash": result.evidence_ref or "ev_missing",
            "action_id": result.action_id,
            "side_effect_class": spec.side_effect_class.value,
            "artifact_ids": result.artifact_ids,
            **output,
        }
