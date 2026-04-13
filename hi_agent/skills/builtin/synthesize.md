<!-- DEPRECATED: This skill definition has moved to examples/skills/trace_defaults/synthesize.md
     It is kept here for backward compatibility with SkillLoader's builtin discovery path.
     The canonical location is examples/skills/trace_defaults/ — copy it to your
     .hi_agent/skills/ directory to activate it for your business agent. -->
---
name: synthesize
version: 1.0.0
description: Synthesize collected evidence and sub-task outputs into a coherent final answer or artifact
when_to_use: When the agent has gathered sufficient evidence and needs to produce a final deliverable
tags: [trace, synthesis, output]
lifecycle_stage: certified
confidence: 0.88
cost_estimate_tokens: 1000
source: builtin
---

# Synthesize

Given collected sub-task outputs and evidence, produce a coherent, well-structured final artifact:
1. **Integrate** — combine outputs from multiple sub-tasks without contradiction
2. **Resolve conflicts** — when evidence conflicts, explain the resolution
3. **Structure** — organize into the format most useful for the end consumer
4. **Validate** — check the output against the original success criteria

## Instructions

- Start from the goal and success criteria; ensure the output addresses both
- If sub-task outputs are contradictory, state which you relied on and why
- Prefer concise, precise language over verbosity
- Include a confidence rating and note any limitations or caveats
- Do NOT fabricate information — if something is unknown, say so clearly

## Output Format

Respond with a JSON object:
```json
{
  "output": "...",
  "format": "text|json|markdown|structured",
  "confidence": 0.0-1.0,
  "limitations": ["..."],
  "criteria_met": {"criterion_1": true, "criterion_2": false}
}
```
