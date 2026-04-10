"""Model router that selects a gateway based on model name."""

from __future__ import annotations

from hi_agent.llm.protocol import LLMGateway, LLMRequest, LLMResponse


class ModelRouter:
    """Routes LLM requests to the appropriate gateway based on model name.

    Gateways are registered under a logical name.  Model-prefix patterns
    (e.g. ``"gpt-"``) map incoming model strings to the correct gateway.
    """

    def __init__(self) -> None:
        """Initialize ModelRouter."""
        self._gateways: dict[str, LLMGateway] = {}
        self._model_patterns: list[tuple[str, str]] = []  # (prefix, gateway_name)

    def register(self, name: str, gateway: LLMGateway) -> None:
        """Register a gateway under *name*.

        Args:
            name: Logical name for this gateway (e.g. ``"openai"``).
            gateway: An object satisfying the :class:`LLMGateway` protocol.
        """
        self._gateways[name] = gateway

    def add_model_pattern(self, prefix: str, gateway_name: str) -> None:
        """Map a model-name prefix to a registered gateway.

        Args:
            prefix: Model name prefix (e.g. ``"gpt-"``).
            gateway_name: Name of a previously registered gateway.
        """
        self._model_patterns.append((prefix, gateway_name))

    def route(self, model: str) -> LLMGateway:
        """Return the gateway responsible for *model*.

        Matching rules (evaluated in registration order):
        1. If *model* starts with a registered prefix, use that gateway.
        2. If *model* exactly matches a registered gateway name, use it.

        Args:
            model: The model identifier from an :class:`LLMRequest`.

        Raises:
            KeyError: No gateway matches *model*.
        """
        for prefix, gw_name in self._model_patterns:
            if model.startswith(prefix):
                return self._gateways[gw_name]
        if model in self._gateways:
            return self._gateways[model]
        raise KeyError(f"No gateway registered for model {model!r}")

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Convenience: route *request.model* and call ``complete``.

        Args:
            request: The LLM request to fulfil.

        Returns:
            The response from the matched gateway.
        """
        gateway = self.route(request.model)
        return gateway.complete(request)
