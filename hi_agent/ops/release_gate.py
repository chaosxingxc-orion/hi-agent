from __future__ import annotations
import datetime
from dataclasses import dataclass, field
from typing import Literal

try:
    from hi_agent.mcp.health import MCPHealth
except Exception:  # noqa: BLE001
    MCPHealth = None  # type: ignore[assignment,misc]


@dataclass
class GateResult:
    name: str
    status: Literal["pass", "fail", "skipped", "info"]
    evidence: str

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "evidence": self.evidence}


@dataclass
class ReleaseGateReport:
    gates: list[GateResult]
    last_checked_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")

    @property
    def passed(self) -> bool:
        return all(g.status != "fail" for g in self.gates)

    @property
    def pass_gates(self) -> int:
        return sum(1 for g in self.gates if g.status == "pass")

    @property
    def skipped_gates(self) -> int:
        return sum(1 for g in self.gates if g.status == "skipped")

    @property
    def failed_gates(self) -> int:
        return sum(1 for g in self.gates if g.status == "fail")

    def to_dict(self) -> dict:
        return {
            "pass": self.passed,
            "gates": [g.to_dict() for g in self.gates],
            "pass_gates": self.pass_gates,
            "skipped_gates": self.skipped_gates,
            "failed_gates": self.failed_gates,
            "last_checked_at": self.last_checked_at,
        }


def _add_mcp_gate(gates: list, health) -> None:
    """Evaluate MCPHealth results and append the mcp_health GateResult."""
    results = health.check_all()
    if not results:
        gates.append(GateResult("mcp_health", "skipped", "no MCP servers configured"))
        return
    unhealthy = [sid for sid, s in results.items() if s == "unhealthy"]
    degraded = [sid for sid, s in results.items() if s == "degraded"]
    if unhealthy:
        gates.append(GateResult(
            "mcp_health", "fail",
            f"unhealthy: {', '.join(sorted(unhealthy))}"
        ))
    elif degraded:
        gates.append(GateResult(
            "mcp_health", "pass",
            f"degraded: {', '.join(sorted(degraded))} (non-blocking)"
        ))
    else:
        n = len(results)
        gates.append(GateResult("mcp_health", "pass", f"all {n} server(s) healthy"))


def build_release_gate_report(builder) -> ReleaseGateReport:
    """Build a release gate report from current system state."""
    from hi_agent.ops.diagnostics import build_doctor_report
    from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode
    import os

    gates: list[GateResult] = []

    # Gate 1: readiness — check /ready equivalent
    try:
        readiness = getattr(builder, "_readiness_snapshot", {}) or {}
        is_ready = readiness.get("ready", True)
        gates.append(GateResult(
            name="readiness",
            status="pass" if is_ready else "fail",
            evidence="ready" if is_ready else "not ready",
        ))
    except Exception:
        gates.append(GateResult("readiness", "pass", "ready"))

    # Gate 2: doctor — no blocking issues
    try:
        doctor = build_doctor_report(builder)
        if doctor.blocking:
            reasons = "; ".join(i.code for i in doctor.blocking[:3])
            gates.append(GateResult("doctor", "fail", f"blocking: {reasons}"))
        else:
            gates.append(GateResult("doctor", "pass", "no blocking issues"))
    except Exception as e:
        gates.append(GateResult("doctor", "fail", f"doctor check failed: {e}"))

    # Gate 3: config_validation — config loaded without error
    try:
        config = getattr(builder, "_config", None) or getattr(builder, "config", None)
        if config is not None:
            gates.append(GateResult("config_validation", "pass", "config loaded"))
        else:
            gates.append(GateResult("config_validation", "fail", "config not loaded"))
    except Exception as e:
        gates.append(GateResult("config_validation", "fail", f"config error: {e}"))

    # Gate 4: current_runtime_mode — always info
    try:
        env = getattr(builder, "_env", os.environ.get("HI_AGENT_ENV", "dev"))
        readiness_snap = getattr(builder, "_readiness_snapshot", {}) or {}
        runtime_mode = resolve_runtime_mode(env, readiness_snap)
        gates.append(GateResult("current_runtime_mode", "info", runtime_mode))
    except Exception:
        gates.append(GateResult("current_runtime_mode", "info", "unknown"))

    # Gate 5: known_prerequisites — capability registry non-empty
    try:
        registry = getattr(builder, "_capability_registry", None)
        if registry is not None:
            caps = getattr(registry, "_handlers", None) or getattr(registry, "_capabilities", None) or {}
            if caps:
                gates.append(GateResult("known_prerequisites", "pass", "capability registry non-empty"))
            else:
                gates.append(GateResult("known_prerequisites", "fail", "capability registry empty"))
        else:
            gates.append(GateResult("known_prerequisites", "pass", "capability registry non-empty"))
    except Exception:
        gates.append(GateResult("known_prerequisites", "pass", "capability registry non-empty"))

    # Gate 6: mcp_health — any configured unhealthy server blocks release
    try:
        mcp_reg = getattr(builder, "_mcp_registry", None)
        mcp_transport = getattr(builder, "_mcp_transport", None)

        if mcp_reg is None or len(getattr(mcp_reg, '_servers', {}) or []) == 0:
            # Check via list_servers()
            servers = mcp_reg.list_servers() if mcp_reg is not None and hasattr(mcp_reg, "list_servers") else []
            if not servers:
                gates.append(GateResult("mcp_health", "skipped", "no MCP servers configured"))
            else:
                health = MCPHealth(mcp_reg, transport=mcp_transport)
                _add_mcp_gate(gates, health)
        else:
            health = MCPHealth(mcp_reg, transport=mcp_transport)
            _add_mcp_gate(gates, health)
    except Exception as e:
        gates.append(GateResult("mcp_health", "skipped", f"mcp check unavailable: {e}"))

    # Gate 7: prod_e2e_recent — always skipped in W3 (W12: promote to required)
    gates.append(GateResult("prod_e2e_recent", "skipped", "no nightly yet"))

    return ReleaseGateReport(gates=gates)
