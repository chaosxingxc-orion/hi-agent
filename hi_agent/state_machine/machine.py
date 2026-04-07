"""Generic finite state machine with transition validation and history."""

from __future__ import annotations

from typing import Callable


class InvalidTransition(Exception):
    """Raised when a transition is not allowed by the state machine."""


class StateMachine:
    """A generic finite state machine.

    Parameters
    ----------
    name:
        Human-readable name for this machine (used in error messages).
    states:
        The full set of valid states.
    initial:
        The starting state (must be in *states*).
    transitions:
        Mapping from each state to the set of states reachable from it.
    terminal:
        Optional set of states that are considered terminal (no further
        transitions allowed out of them).
    """

    def __init__(
        self,
        name: str,
        states: set[str],
        initial: str,
        transitions: dict[str, set[str]],
        terminal: set[str] | None = None,
    ) -> None:
        if initial not in states:
            raise ValueError(f"Initial state {initial!r} not in states")
        self._name = name
        self._states = frozenset(states)
        self._current = initial
        self._transitions = {k: frozenset(v) for k, v in transitions.items()}
        self._terminal = frozenset(terminal) if terminal else frozenset()
        self._history: list[tuple[str, str, str]] = []
        self._callbacks: list[Callable[[str, str], None]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current(self) -> str:
        """Return the current state."""
        return self._current

    @property
    def is_terminal(self) -> bool:
        """Return whether the current state is terminal."""
        return self._current in self._terminal

    @property
    def history(self) -> list[tuple[str, str, str]]:
        """Return the transition history as ``(from, to, machine_name)`` tuples."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Transition logic
    # ------------------------------------------------------------------

    def can_transition(self, to_state: str) -> bool:
        """Check whether transitioning to *to_state* is allowed."""
        if to_state not in self._states:
            return False
        allowed = self._transitions.get(self._current, frozenset())
        return to_state in allowed

    def available_transitions(self) -> set[str]:
        """Return the set of states reachable from the current state."""
        return set(self._transitions.get(self._current, frozenset()))

    def transition(self, to_state: str) -> None:
        """Move to *to_state*, raising :class:`InvalidTransition` on failure."""
        if not self.can_transition(to_state):
            raise InvalidTransition(
                f"[{self._name}] Cannot transition from "
                f"{self._current!r} to {to_state!r}"
            )
        from_state = self._current
        self._current = to_state
        self._history.append((from_state, to_state, self._name))
        for cb in self._callbacks:
            cb(from_state, to_state)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_transition(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback invoked after every successful transition.

        The callback receives ``(from_state, to_state)``.
        """
        self._callbacks.append(callback)
