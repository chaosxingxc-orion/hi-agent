"""EvaluatorRuntime — helpers for managing evaluator lifecycle at run time.

``EvaluatorRuntime`` is the platform glue between a ``ProfileSpec``'s
evaluator and the ``EvaluationMiddleware``.  It:

- Constructs an evaluator from a factory or uses a pre-built instance.
- Optionally wraps a custom evaluator alongside the platform
  ``DefaultEvaluator`` using ``CompositeEvaluator``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EvaluatorRuntime:
    """Lifecycle manager for a pluggable evaluator instance.

    Usage::

        runtime = EvaluatorRuntime(evaluator=my_eval)
        mw._evaluator = runtime.evaluator  # inject into EvaluationMiddleware
    """

    def __init__(
        self,
        evaluator: Any | None = None,
        wrap_with_default: bool = True,
        default_weight: float = 0.4,
        custom_weight: float = 0.6,
    ) -> None:
        """Args:
        evaluator: Pre-built Evaluator instance.  When None, a
            ``DefaultEvaluator`` is used as the sole evaluator.
        wrap_with_default: When True and ``evaluator`` is not None,
            wraps both ``DefaultEvaluator`` and the custom evaluator in a
            ``CompositeEvaluator`` so platform baseline criteria are always
            checked alongside domain-specific criteria.
        default_weight: Weight for ``DefaultEvaluator`` in composite.
        custom_weight: Weight for custom evaluator in composite.
        """
        from hi_agent.evaluation.contracts import CompositeEvaluator, DefaultEvaluator

        if evaluator is None:
            self._evaluator: Any = DefaultEvaluator()
        elif wrap_with_default:
            self._evaluator = CompositeEvaluator([
                (DefaultEvaluator(), default_weight),
                (evaluator, custom_weight),
            ])
        else:
            self._evaluator = evaluator

    @property
    def evaluator(self) -> Any:
        """The live evaluator instance ready for injection."""
        return self._evaluator

    @classmethod
    def from_resolved_profile(
        cls,
        resolved_profile: Any | None,
        wrap_with_default: bool = True,
    ) -> EvaluatorRuntime:
        """Build an EvaluatorRuntime from a ResolvedProfile.

        When the profile has no evaluator, returns a runtime backed by the
        platform ``DefaultEvaluator`` only.
        """
        evaluator = None
        if resolved_profile is not None and resolved_profile.has_evaluator:
            evaluator = resolved_profile.evaluator
        return cls(evaluator=evaluator, wrap_with_default=wrap_with_default)
