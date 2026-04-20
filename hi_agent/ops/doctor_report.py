from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class DoctorIssue:
    subsystem: str
    code: str
    severity: Literal["blocking", "warning", "info"]
    message: str
    fix: str
    verify: str  # shell command to verify fix

    def to_dict(self) -> dict:
        return {
            "subsystem": self.subsystem,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "fix": self.fix,
            "verify": self.verify,
        }


@dataclass
class DoctorReport:
    status: Literal["ready", "degraded", "error"]
    blocking: list[DoctorIssue] = field(default_factory=list)
    warnings: list[DoctorIssue] = field(default_factory=list)
    info: list[DoctorIssue] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "blocking": [i.to_dict() for i in self.blocking],
            "warnings": [i.to_dict() for i in self.warnings],
            "info": [i.to_dict() for i in self.info],
            "next_steps": self.next_steps,
        }
