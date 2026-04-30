"""Stage execution directives — allows business layer to signal mid-run re-planning."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# scope: process-internal — directive value object (CLAUDE.md Rule 12 carve-out)
class InsertSpec(BaseModel):
    """Specification for inserting a new stage after a target anchor.

    target_stage_id: anchor stage — new stage inserted AFTER this one.
    new_stage: name for the inserted stage; must be unique in run.
    config: arbitrary stage config passed to the inserted stage executor.
    """

    # scope: process-internal
    target_stage_id: str  # anchor stage — new stage inserted AFTER this one
    new_stage: str  # name for the inserted stage; must be unique in run
    config: dict = Field(default_factory=dict)


# scope: process-internal — directive value object (CLAUDE.md Rule 12 carve-out)
class StageDirective(BaseModel):
    """Runtime directive from a replan_hook to modify stage execution order.

    Platform honors the directive; business layer provides the replan_hook callable.

    action values:
    - "continue": proceed normally (default)
    - "skip": remove target_stage_id from remaining stages
    - "repeat": push the current stage back onto the front of the remaining list
    - "insert": splice InsertSpec entries immediately after their anchor stages
    - "skip_to": jump forward to the named stage, dropping all intermediate stages
    """

    # scope: process-internal
    action: Literal["continue", "skip", "repeat", "insert", "skip_to"] = "continue"
    target_stage_id: str | None = None  # for skip / repeat
    skip_to: str | None = None  # for skip_to action (added W25-M.1)
    insert: list[InsertSpec] = Field(default_factory=list)  # for insert action
    reason: str | None = None

    @model_validator(mode="after")
    def _check_action_consistency(self) -> StageDirective:
        if self.action == "skip_to" and not self.skip_to:
            raise ValueError("skip_to action requires skip_to field to be set")
        if self.action == "insert" and not self.insert:
            raise ValueError("insert action requires at least one InsertSpec in insert list")
        if self.action in ("skip", "repeat") and not self.target_stage_id:
            raise ValueError(f"{self.action} action requires target_stage_id")
        return self
