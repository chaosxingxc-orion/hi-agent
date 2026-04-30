"""Contract-layer exceptions for hi-agent stage directive and contract enforcement."""


class StageDirectiveError(RuntimeError):
    """Raised when posture forbids the requested directive action, or target is invalid."""
