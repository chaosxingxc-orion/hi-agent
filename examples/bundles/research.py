"""ResearchBundle: capability bundle for research agent scenarios.

This is a domain-specific plugin — it lives in examples/, NOT in hi_agent/
core, because it implements capabilities for a specific business domain
(academic research) rather than generic platform infrastructure.

Usage::

    from examples.bundles.research import ResearchBundle
    from hi_agent.capability.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    bundle = ResearchBundle(llm_gateway=gateway)
    bundle.register(registry)

To use ResearchBundle from hi_agent.capability.bundles.research (deprecated
import path), see hi_agent/capability/bundles/research.py.

Provides:
    - web_search: Search the web for information
    - web_extract: Extract content from web pages
    - paper_parse: Parse academic paper structure and metadata
    - citation_capture: Extract and normalize citations
    - summarize_sources: Summarize a collection of sources
    - literature_review: Synthesize a structured literature review
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from hi_agent.capability.bundles.base import CapabilityBundle
from hi_agent.capability.registry import CapabilitySpec

if TYPE_CHECKING:
    from hi_agent.capability.registry import CapabilityRegistry
    from hi_agent.llm.protocol import LLMGateway

logger = logging.getLogger(__name__)


def _allow_heuristic() -> bool:
    import os

    env = os.environ.get("HI_AGENT_ENV", "prod").lower()
    return env != "prod" or os.environ.get(
        "HI_AGENT_ALLOW_HEURISTIC_FALLBACK", ""
    ).lower() in ("1", "true", "yes")


def _llm_or_heuristic(
    gateway: LLMGateway | None,
    cap_name: str,
    system_prompt: str,
    heuristic_output: str,
):
    """Build a handler that calls LLM or falls back to heuristic."""

    def handler(payload: dict) -> dict:
        goal = payload.get("goal", payload.get("query", payload.get("description", "")))

        if gateway is not None:
            try:
                from hi_agent.llm.protocol import LLMRequest

                req = LLMRequest(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": (
                                f"Task: {goal}\nContext: {payload.get('context', '')}"
                            ),
                        },
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                )
                resp = gateway.complete(req)
                try:
                    data = json.loads(resp.content)
                    data.setdefault("success", True)
                    data.setdefault("score", 0.85)
                    return data
                except json.JSONDecodeError:
                    return {"success": True, "output": resp.content, "score": 0.8}
            except Exception as exc:
                logger.warning("%s: LLM call failed: %s", cap_name, exc)
                if not _allow_heuristic():
                    return {"success": False, "score": 0.0, "error": str(exc)}

        if _allow_heuristic():
            return {
                "success": True,
                "output": f"[{cap_name}] {heuristic_output}: {goal}",
                "score": 0.5,
                "_heuristic": True,
            }
        return {"success": False, "score": 0.0, "error": f"{cap_name}: no LLM gateway in prod mode"}

    handler.__name__ = cap_name
    return handler


class ResearchBundle(CapabilityBundle):
    """Capability bundle for research agent scenarios.

    Provides 6 research-oriented capabilities backed by LLM or heuristic
    fallback when no LLM is configured.
    """

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        self._gateway = llm_gateway

    def register(self, registry: CapabilityRegistry) -> int:
        """Register all 6 research capabilities into the registry."""
        specs = [
            CapabilitySpec(
                name="web_search",
                handler=_llm_or_heuristic(
                    self._gateway,
                    "web_search",
                    (
                        "You are a web search engine. Given a query, return relevant "
                        "results as JSON: "
                        '{"results": [{"title": "...", "url": "...", "snippet": "..."}], '
                        '"query": "..."}'
                    ),
                    "Searched web for",
                ),
            ),
            CapabilitySpec(
                name="web_extract",
                handler=_llm_or_heuristic(
                    self._gateway,
                    "web_extract",
                    (
                        "You are a web content extractor. Extract the main text "
                        "content from the given URL or HTML. "
                        'Return JSON: {"title": "...", "content": "...", "url": "...", '
                        '"word_count": 0}'
                    ),
                    "Extracted content from",
                ),
            ),
            CapabilitySpec(
                name="paper_parse",
                handler=_llm_or_heuristic(
                    self._gateway,
                    "paper_parse",
                    (
                        "You are an academic paper parser. Extract structured metadata "
                        "from an academic paper. "
                        'Return JSON: {"title": "...", "authors": [], "abstract": "...", '
                        '"keywords": [], "year": null, "venue": "...", "doi": null}'
                    ),
                    "Parsed paper metadata for",
                ),
            ),
            CapabilitySpec(
                name="citation_capture",
                handler=_llm_or_heuristic(
                    self._gateway,
                    "citation_capture",
                    (
                        "You are a citation extractor. Extract and normalize all "
                        "citations from the given text. "
                        'Return JSON: {"citations": [{"text": "...", "normalized": "...", '
                        '"doi": null}]}'
                    ),
                    "Captured citations from",
                ),
            ),
            CapabilitySpec(
                name="summarize_sources",
                handler=_llm_or_heuristic(
                    self._gateway,
                    "summarize_sources",
                    (
                        "You are a research summarizer. Synthesize a concise summary "
                        "from multiple sources. "
                        'Return JSON: {"summary": "...", "key_points": [], "source_count": 0, '
                        '"confidence": 0.0}'
                    ),
                    "Summarized sources about",
                ),
            ),
            CapabilitySpec(
                name="literature_review",
                handler=_llm_or_heuristic(
                    self._gateway,
                    "literature_review",
                    (
                        "You are a literature review specialist. Produce a "
                        "structured literature review for the given topic. "
                        'Return JSON: {"topic": "...", "sections": [{"heading": "...", '
                        '"content": "..."}], "gaps": [], "total_sources": 0}'
                    ),
                    "Conducted literature review on",
                ),
            ),
        ]
        for spec in specs:
            registry.register(spec)
        logger.info("ResearchBundle.register: registered %d capabilities.", len(specs))
        return len(specs)
