"""Authorization context built from HTTP request headers (HI-W1-D5-001)."""

from __future__ import annotations
from dataclasses import dataclass
from fastapi import Request


@dataclass
class AuthorizationContext:
    role: str
    token: str | None
    runtime_mode: str
    submitter: str | None
    approver: str | None

    @classmethod
    def from_request(cls, request: Request) -> "AuthorizationContext":
        """Build authorization context from request headers.

        Headers:
          Authorization: Bearer <token>
          X-Role: submitter | approver | auditor | admin
          X-Submitter: <id>
          X-Approver: <id>
        Runtime mode is read from app.state if available, otherwise dev-smoke.
        """
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip() or None
        role = request.headers.get("X-Role", "submitter")
        runtime_mode = getattr(request.app.state, "runtime_mode", "dev-smoke")
        submitter = request.headers.get("X-Submitter") or None
        approver = request.headers.get("X-Approver") or None
        return cls(
            role=role,
            token=token,
            runtime_mode=runtime_mode,
            submitter=submitter,
            approver=approver,
        )
