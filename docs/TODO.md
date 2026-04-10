# hi-agent TODO (TDD-first)

- [x] Bootstrap project structure (`hi_agent/`, `tests/`, `pyproject.toml`).
- [x] Write failing spike tests:
  - [x] `tests/test_spike_run.py`
  - [x] `tests/test_spike_identity.py`
  - [x] `tests/test_spike_dead_end.py`
- [x] Implement runtime and trajectory baseline:
  - [x] `hi_agent/runner.py`
  - [x] `hi_agent/runtime_adapter/{mock_kernel,kernel_adapter,protocol}.py`
  - [x] `hi_agent/trajectory/{greedy,backpropagation,stage_graph,dead_end}.py`
- [x] Implement contracts split:
  - [x] `hi_agent/contracts/{task,trajectory,stage,identity,memory,policy,cts_budget,config}.py`
- [x] Implement route, memory, capability, events, management modules.
- [x] Add spike + integration + subsystem test coverage.
- [ ] Remaining advanced roadmap:
  - [ ] Real external `agent-kernel` backend wiring in `KernelAdapter`.
  - [ ] Inline + batch evolve workflow.
  - [ ] Skill promotion and dataset evaluation pipeline.
