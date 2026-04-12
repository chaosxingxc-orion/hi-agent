---
name: search_evidence
version: 1.0.0
description: Gather, evaluate, and rank evidence relevant to a research question or task goal
when_to_use: When the agent needs to collect supporting facts, data, or references for a claim or decision
tags: [trace, research, evidence]
lifecycle_stage: certified
confidence: 0.85
cost_estimate_tokens: 800
source: builtin
---

# Search Evidence

Given a research question or task context, systematically gather and evaluate evidence:
1. **Identify search axes** — what dimensions of evidence are needed (factual, comparative, temporal, causal)
2. **Collect candidate evidence** — from available context, knowledge base, and tools
3. **Evaluate quality** — source reliability, recency, relevance, and completeness
4. **Rank and filter** — surface the strongest evidence first

## Instructions

- Formulate 2-4 targeted search queries that cover different angles of the question
- For each piece of evidence, note: source, claim, confidence level, and relevance to the goal
- Distinguish between direct evidence (confirms the claim), indirect evidence (supports context), and counter-evidence (challenges the claim)
- Surface gaps — what evidence is missing that would strengthen the case?

## Output Format

Respond with a JSON object:
```json
{
  "evidence": [
    {"claim": "...", "source": "...", "confidence": 0.0-1.0, "type": "direct|indirect|counter"}
  ],
  "gaps": ["..."],
  "overall_confidence": 0.0-1.0,
  "recommendation": "proceed|gather_more|escalate"
}
```
