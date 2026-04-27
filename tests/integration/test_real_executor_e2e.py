"""True end-to-end integration test for executor.execute() with a real custom profile.

Proves that the D1+D2+D8 fix works: build_invoker() now uses the SHARED
CapabilityRegistry singleton, so capabilities registered via
builder.build_capability_registry().register(...) are visible when execute()
dispatches actions through the harness.

Per CLAUDE.md P3 (Production Integrity Constraint):
- All hi_agent internal components run for real (no internal mocks).
- Capability handlers are real Python functions.
- unittest.mock.patch is used ONLY to intercept outbound HTTP calls that
  the LLM gateway would make to external network services (allowed per P3).
"""

from __future__ import annotations

import uuid

import pytest

# ---------------------------------------------------------------------------
# Real capability handlers — plain Python functions, no mocks
# ---------------------------------------------------------------------------


def fake_analyze(payload: dict) -> dict:
    """Real Python function serving as a capability handler for 'fake_analyze'."""
    return {
        "result": "analysis done",
        "score": 0.9,
        "input_received": payload,
    }


def fake_summarize(payload: dict) -> dict:
    """Real Python function serving as a capability handler for 'fake_summarize'."""
    return {
        "summary": "This is a fake summary.",
        "tokens": 42,
    }


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestRealExecutorE2E:
    """End-to-end test proving capability wiring fix works through executor.execute()."""

    def _make_builder_with_capabilities(self):
        """Create a SystemBuilder with two real capability handlers registered."""
        from hi_agent.capability.registry import CapabilitySpec
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()

        # Use the shared singleton registry — this is the registry that
        # build_invoker() will use after the D1+D2+D8 fix.
        cap_registry = builder.build_capability_registry()
        for name, handler in [
            ("fake_analyze", fake_analyze),
            ("fake_summarize", fake_summarize),
        ]:
            if name not in cap_registry.list_names():
                cap_registry.register(
                    CapabilitySpec(
                        name=name,
                        handler=handler,
                        description=f"Real handler for {name} — no mocks",
                    )
                )

        return builder

    def _make_profile_spec(self, profile_id: str):
        """Build a minimal 2-action ProfileSpec that requires the real capabilities."""
        from hi_agent.profiles.contracts import ProfileSpec

        return ProfileSpec(
            profile_id=profile_id,
            display_name="E2E Test Profile",
            description="Minimal profile for capability wiring e2e test",
            required_capabilities=["fake_analyze", "fake_summarize"],
            stage_actions={
                "S1_understand": "fake_analyze",
                "S3_build": "fake_summarize",
            },
        )

    # ------------------------------------------------------------------
    # Assertion 1: build_executor() completes without MissingCapabilityError
    # ------------------------------------------------------------------

    def test_build_executor_does_not_raise_missing_capability(self):
        """build_executor() must not raise MissingCapabilityError when capabilities are registered.

        This directly validates the D1+D2+D8 fix: the shared registry used by
        _validate_required_capabilities() is the same object that was populated
        by build_capability_registry().register(...).
        """
        from hi_agent.config.builder import MissingCapabilityError
        from hi_agent.contracts.task import TaskContract

        profile_id = f"e2e_profile_{uuid.uuid4().hex[:8]}"
        builder = self._make_builder_with_capabilities()
        builder.register_profile(self._make_profile_spec(profile_id))

        contract = TaskContract(
            task_id=f"e2e-cap-{uuid.uuid4().hex[:8]}",
            goal="Analyze data and produce a summary",
            profile_id=profile_id,
        )

        # Must NOT raise MissingCapabilityError
        try:
            executor = builder.build_executor(contract)
        except MissingCapabilityError as exc:
            pytest.fail(f"build_executor() raised MissingCapabilityError unexpectedly: {exc}")

        assert executor is not None, "build_executor() must return a RunExecutor instance"

    # ------------------------------------------------------------------
    # Assertion 2: executor.execute() completes without "Unknown capability" error
    # ------------------------------------------------------------------

    def test_execute_does_not_raise_unknown_capability(self):
        """executor.execute() must not raise 'Unknown capability' through the harness.

        Before the D1+D2+D8 fix, build_invoker() created a FRESH CapabilityRegistry
        disconnected from the shared singleton, so every capability dispatch raised
        KeyError: 'Unknown capability: <name>'.  This test proves the fix is live.

        LLM HTTP calls are patched at the transport layer only (allowed per P3)
        because we do not have live credentials in CI.
        """
        from unittest.mock import MagicMock, patch

        from hi_agent.contracts.task import TaskContract

        profile_id = f"e2e_profile_{uuid.uuid4().hex[:8]}"
        builder = self._make_builder_with_capabilities()
        builder.register_profile(self._make_profile_spec(profile_id))

        contract = TaskContract(
            task_id=f"e2e-exec-{uuid.uuid4().hex[:8]}",
            goal="Analyze quarterly revenue data",
            profile_id=profile_id,
        )

        executor = builder.build_executor(contract)
        assert executor is not None

        # Patch only the HTTP transport layer to block outbound LLM calls.
        # The LLM gateway class itself is NOT patched — all hi_agent internal
        # logic runs for real (P3 compliant).
        fake_llm_response = MagicMock()
        fake_llm_response.status_code = 200
        fake_llm_response.json.return_value = {
            "choices": [{"message": {"content": "heuristic fallback"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        fake_llm_response.text = '{"choices":[{"message":{"content":"heuristic fallback"}}]}'

        # Patch urllib.request.urlopen and httpx.Client.post to block real HTTP.
        # If no API key is configured (CI), the gateway is None anyway (dev mode
        # fallback), so these patches are a no-op but present for safety.
        with (
            patch("urllib.request.urlopen", return_value=fake_llm_response),
            patch("httpx.Client.post", return_value=fake_llm_response),
        ):
            try:
                result = executor.execute()
            except KeyError as exc:
                if "Unknown capability" in str(exc):
                    pytest.fail(
                        f"executor.execute() raised 'Unknown capability' error — "
                        f"capability registry fix (D1+D2+D8) is NOT active: {exc}"
                    )
                raise
            except Exception:
                # Any other exception from real subsystems is surfaced verbatim
                # so the caller sees the true failure, not a hidden mock path.
                raise

        # ------------------------------------------------------------------
        # Assertion 3: returned result is not None
        # ------------------------------------------------------------------
        assert result is not None, "executor.execute() must return a non-None result string"

        # ------------------------------------------------------------------
        # Assertion 4: the run reached a terminal state, not a capability error
        # ------------------------------------------------------------------
        # Valid terminal outcomes from RunExecutor.execute()
        valid_outcomes = {"completed", "failed", "aborted", "escalated", "timeout"}
        assert result == "completed", (
            f"Unexpected result from executor.execute(): {result!r}"
        )

        # The critical invariant: if the run failed, it must NOT be due to
        # capability infrastructure errors.  Check the event log for any
        # "Unknown capability" failure event.
        if hasattr(executor, "event_emitter") and hasattr(executor.event_emitter, "events"):
            capability_errors = [
                ev
                for ev in executor.event_emitter.events
                if "Unknown capability" in str(getattr(ev, "payload", {}))
            ]
            assert len(capability_errors) == 0, (
                f"Found 'Unknown capability' errors in event log: {capability_errors}"
            )

    # ------------------------------------------------------------------
    # Assertion 5: shared registry identity — same object, not two instances
    # ------------------------------------------------------------------

    def test_shared_registry_identity_between_build_capability_registry_and_build_invoker(self):
        """build_invoker() must use the exact same CapabilityRegistry instance
        as build_capability_registry(), not a freshly-created one.

        This directly validates the root cause fix (D1): build_invoker() was
        previously creating a new CapabilityRegistry() internally.
        """
        from hi_agent.config.builder import SystemBuilder

        builder = SystemBuilder()

        # Obtain the shared singleton
        shared_registry = builder.build_capability_registry()
        assert shared_registry is not None

        # Obtain a second reference — must be the exact same object
        second_ref = builder.build_capability_registry()
        assert second_ref is shared_registry, (
            "build_capability_registry() must return the same singleton on repeated calls"
        )

        # Build an invoker and verify it holds the shared registry
        invoker = builder.build_invoker()
        assert invoker is not None

        # The invoker's internal registry must be the shared singleton
        invoker_registry = getattr(invoker, "_registry", None) or getattr(invoker, "registry", None)
        if invoker_registry is not None:
            assert invoker_registry is shared_registry, (
                "build_invoker() must use the shared CapabilityRegistry singleton, "
                "not create a new CapabilityRegistry(). "
                "This is the root cause of the 'Unknown capability' defect."
            )
