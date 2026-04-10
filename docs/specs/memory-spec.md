# Memory Spec

This document defines layered memory behavior (L0 raw, L1 compressed, L2 index).

## Scope
- Stage summary compression.
- Run index materialization.
- Token budgeting and truncation.

## Current Status
Implemented in `hi_agent/memory/*` and `hi_agent/task_view/*`.
