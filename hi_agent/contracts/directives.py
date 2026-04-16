"""Stage execution directives — allows business layer to signal mid-run re-planning."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class StageDirective:
    """Returned by a replan_hook to signal how the execute() loop should proceed.

    Platform honors the directive; business layer provides the replan_hook callable.

    action values:
    - "continue": proceed normally (default)
    - "skip": remove target_stage_id from remaining stages
    - "repeat": push the current stage back onto the front of the remaining list
    - "insert": splice new_stage_specs immediately after the current stage
    """

    action: Literal["continue", "skip", "repeat", "insert"] = "continue"
    target_stage_id: str = ""
    new_stage_specs: list[dict] = field(default_factory=list)
    reason: str = ""
