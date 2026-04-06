"""Separation-of-concerns guard utilities."""

from __future__ import annotations


class SeparationOfConcernError(PermissionError):
    """Raised when submitter/approver separation rule is violated."""


def enforce_submitter_approver_separation(
    *,
    submitter: str,
    approver: str,
    enabled: bool = True,
) -> None:
    """Enforce submitter/approver separation when policy is enabled."""
    if not enabled:
        return
    if submitter == approver:
        raise SeparationOfConcernError("submitter and approver must be different principals")

