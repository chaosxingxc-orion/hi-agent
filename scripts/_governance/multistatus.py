"""Multistatus gate protocol.

Defines the four-state protocol for governance gate scripts:

    PASS  — gate's invariant holds at current HEAD; emits exit code 0.
    WARN  — gate observed a soft issue; tracked but not ship-blocking; exit 0.
    DEFER — gate cannot run because a prerequisite is missing; tracked debt; exit 0.
    FAIL  — gate's invariant is violated at current HEAD; ship-blocking; exit 1.

Every gate script SHOULD use this module (via :func:`emit`) so a single
runner (``scripts/_governance/multistatus_runner.py``) can aggregate results
across all gates uniformly.

Backward-compatibility: the older :func:`emit_and_exit` helper is preserved
unchanged for callers that already adopted it.

Usage (new-style)::

    from scripts._governance.multistatus import GateStatus, GateResult, emit

    emit(GateResult(
        status=GateStatus.PASS,
        gate_name="contract_freeze",
        reason="no uncommitted changes to agent_server/contracts/",
        evidence={"changed_files": 0},
    ))

The runner shape is fixed::

    {
      "gate":  "<gate_name>",
      "status": "PASS"|"FAIL"|"WARN"|"DEFER",
      "reason": "<one-line human-readable>",
      "evidence": { ... arbitrary JSON ... },
      "expiry_wave": <int|null>
    }
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MultistatusParseError(ValueError):
    """Raised when gate stdout cannot be parsed as a multistatus payload."""


class GateStatus(Enum):
    """Four-state multistatus enum."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    DEFER = "DEFER"

    @classmethod
    def from_str(cls, value: str) -> GateStatus:
        if not isinstance(value, str):
            raise MultistatusParseError(f"status must be str, got {type(value).__name__}")
        upper = value.strip().upper()
        for member in cls:
            if member.value == upper:
                return member
        valid = [m.value for m in cls]
        raise MultistatusParseError(f"invalid status {value!r}; expected one of {valid}")


@dataclass(frozen=True)
class GateResult:
    """Immutable result of a single gate run.

    scope: process-internal — value object passed between gate scripts and the
    runner; never persisted across tenants.
    """
    status: GateStatus
    gate_name: str
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    expiry_wave: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the runner JSON shape."""
        return {
            "gate": self.gate_name,
            "status": self.status.value,
            "reason": self.reason,
            "evidence": dict(self.evidence),
            "expiry_wave": self.expiry_wave,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GateResult:
        """Inverse of :meth:`to_dict`. Raises MultistatusParseError on bad input."""
        if not isinstance(data, dict):
            raise MultistatusParseError(f"expected dict, got {type(data).__name__}")
        for field_name in ("gate", "status"):
            if field_name not in data:
                raise MultistatusParseError(f"missing required field {field_name!r}")
        gate_name = data["gate"]
        if not isinstance(gate_name, str) or not gate_name:
            raise MultistatusParseError("'gate' must be non-empty str")
        status = GateStatus.from_str(data["status"])
        reason = data.get("reason", "")
        if not isinstance(reason, str):
            raise MultistatusParseError("'reason' must be str")
        evidence = data.get("evidence", {}) or {}
        if not isinstance(evidence, dict):
            raise MultistatusParseError("'evidence' must be dict")
        expiry = data.get("expiry_wave")
        if expiry is not None and not isinstance(expiry, int):
            raise MultistatusParseError("'expiry_wave' must be int or null")
        return cls(
            status=status,
            gate_name=gate_name,
            reason=reason,
            evidence=evidence,
            expiry_wave=expiry,
        )


def emit(result: GateResult, *, stream=None) -> None:
    """Print the GateResult JSON on a single line and exit.

    Exit code:
      - PASS / WARN / DEFER  → 0  (not ship-blocking)
      - FAIL                 → 1  (ship-blocking)

    Note: WARN and DEFER are non-blocking by design; the runner is responsible
    for aggregating them and applying score caps where appropriate.
    """
    out = stream if stream is not None else sys.stdout
    out.write(json.dumps(result.to_dict(), separators=(",", ":")))
    out.write("\n")
    out.flush()
    sys.exit(0 if result.status is not GateStatus.FAIL else 1)


def parse(output: str) -> GateResult:
    """Parse a gate's stdout into a GateResult.

    Accepts: a single JSON object on any line of *output* matching the runner
    shape. Tolerates extra surrounding lines (e.g. legacy human-readable output
    plus an appended JSON line). The LAST valid multistatus JSON object wins —
    so a script that prints legacy text first and emits the multistatus JSON
    last still parses correctly.
    """
    if not isinstance(output, str):
        raise MultistatusParseError(f"output must be str, got {type(output).__name__}")
    last_err: Exception | None = None
    last_result: GateResult | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if not line or not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
        if not isinstance(obj, dict) or "status" not in obj or "gate" not in obj:
            continue
        try:
            last_result = GateResult.from_dict(obj)
        except MultistatusParseError as exc:
            last_err = exc
            continue
    if last_result is not None:
        return last_result
    raise MultistatusParseError(
        f"no valid multistatus JSON line found in output"
        f"{'; last error: ' + str(last_err) if last_err else ''}"
    )


# ---------------------------------------------------------------------------
# Backward-compatible legacy helper — kept verbatim so existing callers
# (and the W14-D9 multistatus_gates audit) do not break.
# ---------------------------------------------------------------------------

_EXIT_CODES = {
    "pass": 0,
    "fail": 1,
    "not_applicable": 2,
    "deferred": 3,
    "warn": 1,  # warn always fail unless caller explicitly handles
}


def emit_and_exit(
    *,
    status: str,
    check: str,
    json_output: bool = False,
    strict: bool = False,
    allow_warn: bool = False,
    **kwargs,
) -> None:
    """Legacy emit-and-exit helper (W14 vintage).

    New gate scripts should prefer :func:`emit` + :class:`GateResult`.
    """
    result = {"status": status, "check": check, **kwargs}
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        if status == "pass":
            print(f"PASS: {check}")
        elif status == "not_applicable":
            reason = kwargs.get("reason", "not applicable")
            print(f"not_applicable: {reason}")
        elif status == "deferred":
            reason = kwargs.get("reason", "deferred")
            print(f"deferred: {reason}")
        elif status == "warn":
            reason = kwargs.get("reason", "warn")
            print(f"WARN: {reason}", file=sys.stderr)
        else:
            reason = kwargs.get("reason", "failed")
            print(f"FAIL: {reason}", file=sys.stderr)

    exit_code = _EXIT_CODES.get(status, 1)
    if status == "not_applicable" and strict:
        exit_code = 1
    if status == "warn" and allow_warn:
        exit_code = 0
    sys.exit(exit_code)
