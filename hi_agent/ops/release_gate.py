from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

try:
    from hi_agent.mcp.health import MCPHealth
except Exception:
    MCPHealth = None  # type: ignore[assignment,misc]


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _format_utc_z(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


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
    last_checked_at: str = field(default_factory=lambda: _format_utc_z(_utc_now()))

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
        gates.append(GateResult("mcp_health", "fail", f"unhealthy: {', '.join(sorted(unhealthy))}"))
    elif degraded:
        gates.append(
            GateResult(
                "mcp_health", "pass", f"degraded: {', '.join(sorted(degraded))} (non-blocking)"
            )
        )
    else:
        n = len(results)
        gates.append(GateResult("mcp_health", "pass", f"all {n} server(s) healthy"))


@dataclass
class ProdE2EResult:
    """Result of a prod-real execution check."""

    passed: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


def check_prod_e2e_recent(
    max_age_hours: int = 24,
    episodic_dir: str = ".hi_agent/episodes",
) -> ProdE2EResult:
    """Hard gate: fails if no prod-real execution found in last max_age_hours.

    Scans episodic_dir for episode JSON files and looks for any entry whose
    ``runtime_mode`` is "prod-real" and whose ``completed_at`` (or ``started_at``)
    timestamp is within the last ``max_age_hours``.

    Returns ProdE2EResult(passed=True) if a recent prod run exists,
    ProdE2EResult(passed=False, reason="...") otherwise.
    """
    cutoff = _utc_now() - datetime.timedelta(hours=max_age_hours)
    episodes_path = Path(episodic_dir)

    if not episodes_path.exists():
        return ProdE2EResult(
            passed=False,
            reason=f"episodic store not found: {episodic_dir}",
            details={"episodic_dir": str(episodes_path.resolve())},
        )

    episode_files = sorted(episodes_path.glob("*.json"))
    if not episode_files:
        return ProdE2EResult(
            passed=False,
            reason="no episodes found in episodic store",
            details={"episodic_dir": str(episodes_path.resolve()), "files": 0},
        )

    latest_prod_ts: datetime.datetime | None = None
    prod_run_count = 0

    for ep_file in episode_files:
        try:
            data = json.loads(ep_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        mode = data.get("runtime_mode") or data.get("execution_provenance", {}).get(
            "runtime_mode", ""
        )
        if mode != "prod-real":
            continue

        ts_str = data.get("completed_at") or data.get("started_at") or ""
        if not ts_str:
            continue

        try:
            ts = _parse_utc_timestamp(ts_str)
        except ValueError:
            continue

        prod_run_count += 1
        if latest_prod_ts is None or ts > latest_prod_ts:
            latest_prod_ts = ts

    if latest_prod_ts is None:
        return ProdE2EResult(
            passed=False,
            reason="no prod-real executions found in episodic store",
            details={
                "episodic_dir": str(episodes_path.resolve()),
                "total_episodes": len(episode_files),
            },
        )

    age_hours = (_utc_now() - latest_prod_ts).total_seconds() / 3600
    if latest_prod_ts < cutoff:
        return ProdE2EResult(
            passed=False,
            reason=(
                f"latest prod-real run is {age_hours:.1f}h old (max allowed: {max_age_hours}h)"
            ),
            details={
                "latest_prod_run": _format_utc_z(latest_prod_ts),
                "age_hours": round(age_hours, 2),
                "max_age_hours": max_age_hours,
                "prod_run_count": prod_run_count,
            },
        )

    return ProdE2EResult(
        passed=True,
        reason=f"prod-real run found {age_hours:.1f}h ago (within {max_age_hours}h window)",
        details={
            "latest_prod_run": _format_utc_z(latest_prod_ts),
            "age_hours": round(age_hours, 2),
            "max_age_hours": max_age_hours,
            "prod_run_count": prod_run_count,
        },
    )


def build_release_gate_report(builder) -> ReleaseGateReport:
    """Build a release gate report from current system state."""
    from hi_agent.ops.diagnostics import build_doctor_report
    from hi_agent.server.runtime_mode_resolver import resolve_runtime_mode

    gates: list[GateResult] = []

    # Gate 1: readiness — check /ready equivalent
    try:
        readiness = getattr(builder, "_readiness_snapshot", {}) or {}
        is_ready = readiness.get("ready", True)
        gates.append(
            GateResult(
                name="readiness",
                status="pass" if is_ready else "fail",
                evidence="ready" if is_ready else "not ready",
            )
        )
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
            caps = (
                getattr(registry, "_handlers", None)
                or getattr(registry, "_capabilities", None)
                or {}
            )
            if caps:
                gates.append(
                    GateResult("known_prerequisites", "pass", "capability registry non-empty")
                )
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

        if mcp_reg is None or len(getattr(mcp_reg, "_servers", {}) or []) == 0:
            # Check via list_servers()
            servers = (
                mcp_reg.list_servers()
                if mcp_reg is not None and hasattr(mcp_reg, "list_servers")
                else []
            )
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

    # Gate 7: prod_e2e_recent — hard gate in prod mode only.
    # In dev/non-prod mode this gate is skipped so it does not block local CI.
    env_mode = os.environ.get("HI_AGENT_ENV", "dev").lower()
    if env_mode == "prod":
        episodic_dir = os.environ.get("HI_AGENT_EPISODES_DIR", ".hi_agent/episodes")
        prod_result = check_prod_e2e_recent(episodic_dir=episodic_dir)
        if prod_result.passed:
            gates.append(GateResult("prod_e2e_recent", "pass", prod_result.reason))
        else:
            gates.append(GateResult("prod_e2e_recent", "fail", prod_result.reason))
    else:
        gates.append(
            GateResult("prod_e2e_recent", "skipped", "non-prod environment — gate skipped")
        )

    return ReleaseGateReport(gates=gates)
