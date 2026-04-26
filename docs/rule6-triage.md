# Rule 6 Inline-Fallback Violation Triage

Wave 11 audit of the 33 reported sites from `scripts/check_rules.py`.
After AST-based FP suppression (docstrings, exception fallbacks, stdlib types),
the real-defect count is approximately 19, concentrated in `agent_kernel/`.

## Classification

### FALSE POSITIVES (suppressed by AST fix, Wave 11)
- `hi_agent/knowledge/factory.py:5` — line is in docstring quoting Rule 6 text
- `hi_agent/server/_durable_backends.py:4` — line is in module docstring
- `hi_agent/runtime_adapter/resilient_kernel_adapter.py:197` — `cause = last_exc or RuntimeError(...)` (exception construction, not shared-state)
- ~1-2 additional stdlib/primitive type patterns (auto-suppressed)

### DATACLASS-CONFIG (low risk, not shared-state resources)
- `agent_kernel/runtime/bundle.py:324-329, 374, 534-543, 564` — `config_X or RuntimeXConfig()` where RuntimeXConfig is a config dataclass, not a shared pool or stateful resource. Rule 6 spirit does not apply to stateless config dataclasses.
  **Owner:** RO | **Wave target:** Wave 12 review (confirm stateless) | **Action:** add comment explaining why not Rule 6

### REAL DEFECTS (shared-state resources — genuine Rule 6 violations)
- `agent_kernel/kernel/persistence/pg_*.py` (4 sites) — `self._bridge = bridge or AsyncPGBridge(dsn=...)` where AsyncPGBridge IS a shared async database pool. **ACTUAL Rule 6 violation.**
  **Owner:** RO | **Wave target:** Wave 12 fix | **Action:** require bridge via required constructor arg

### BORDERLINE (stdlib Path or single-use construction)
- `hi_agent/capability/tools/builtin.py:46,95` — `base_dir = workspace_root or Path(".").resolve()` — stdlib `Path`, not shared-state. Low risk.
  **Owner:** CO | **Wave target:** Wave 13 or N/A | **Action:** tolerate (Path is not a shared resource)
- `hi_agent/task_mgmt/reflection_bridge.py:78` — review needed
  **Owner:** RO | **Wave target:** Wave 12 review

## Summary

| Category | Count (approx) | Action |
|---|---|---|
| False positives (suppressed) | ~4 | Fixed by AST migration (Wave 11) |
| Dataclass-config (low risk) | ~10 | Wave 12 review |
| Real defects (PG bridges) | ~4 | Wave 12 fix (RO) |
| Borderline stdlib | ~2 | Tolerate or Wave 13 |
| **Real defects after suppression** | **~4** | |
