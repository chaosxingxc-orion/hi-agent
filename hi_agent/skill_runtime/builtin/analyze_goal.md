<!-- DEPRECATED: This skill definition has moved to examples/skills/trace_defaults/analyze_goal.md
     It is kept here for backward compatibility with SkillLoader's builtin discovery path.
     The canonical location is examples/skills/trace_defaults/ — copy it to your
     .hi_agent/skills/ directory to activate it for your business agent. -->
---
name: analyze_goal
version: 1.0.0
description: Decompose a high-level goal into concrete sub-tasks and success criteria
when_to_use: When the agent receives a new task goal and needs to break it into actionable steps
tags: [trace, planning, decomposition]
lifecycle_stage: certified
confidence: 0.90
cost_estimate_tokens: 600
source: builtin
---

# Analyze Goal

Given a task goal, systematically decompose it into:
1. **Concrete sub-tasks** — discrete, executable steps
2. **Success criteria** — measurable conditions that define completion
3. **Dependencies** — which sub-tasks depend on others
4. **Risk factors** — what could go wrong and why

## Instructions

- Read the goal carefully and identify the core intent
- Break the goal into 3-7 sub-tasks (more is rarely better at this stage)
- For each sub-task, state: what needs to happen, what inputs are needed, what the output looks like
- State success criteria as verifiable conditions (not vague aspirations)
- Flag any ambiguities that require clarification before proceeding

## Output Format

Respond with a JSON object:
```json
{
  "sub_tasks": ["...", "..."],
  "success_criteria": ["...", "..."],
  "dependencies": {"task_n": ["task_m"]},
  "risks": ["..."],
  "clarifications_needed": []
}
```
