# TRACE hi-agent 实施总体计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 TRACE V2.8 架构规范（ARCHITECTURE.md, 4070 行）落地为可运行的 hi-agent 代码，分三阶段交付。

**Architecture:** hi-agent 是 Python 项目，依赖 agent-kernel（Python, pyproject.toml, 已有 97 个源文件 + 100 个测试）和 agent-core/openjiuwen（Python SDK）。hi-agent 按 TRACE 五步循环（Task→Route→Act→Capture→Evolve）组织代码，通过 RuntimeAdapter 与 agent-kernel 对接。

**Tech Stack:** Python 3.14 / pytest / ruff / agent-kernel（本地 import）/ agent-core/openjiuwen（本地 import）/ SQLite（开发环境）/ gRPC（Capability 调用）

---

## 前置：项目初始化与架构文档拆分

### Task 0: 项目骨架初始化

**Files:**
- Create: `hi_agent/__init__.py`
- Create: `hi_agent/py.typed`
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "hi-agent"
version = "0.1.0"
description = "TRACE enterprise agent — the sole intelligent agent"
requires-python = ">=3.14"
dependencies = [
    "agent-kernel @ file:///${PROJECT_ROOT}/../agent-kernel",
    "openjiuwen @ file:///${PROJECT_ROOT}/../external/agent-core",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.8"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py314"
src = ["hi_agent", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "C4", "SIM", "RUF"]
```

- [ ] **Step 2: 创建包结构**

```
hi_agent/
  __init__.py          # 空
  py.typed             # PEP 561 marker
tests/
  __init__.py
  conftest.py          # 共享 fixtures
```

`tests/conftest.py`:
```python
"""Shared test fixtures for hi-agent."""
```

- [ ] **Step 3: 验证项目可安装**

Run: `cd D:\chao_workspace\hi-agent && pip install -e ".[dev]"`
Expected: 成功安装，无错误

- [ ] **Step 4: 验证 pytest 可运行**

Run: `pytest --co`
Expected: "no tests ran" (但不报错)

- [ ] **Step 5: 验证依赖可导入**

```python
# tests/test_smoke.py
def test_can_import_kernel():
    from agent_kernel.kernel import contracts
    assert hasattr(contracts, "RuntimeEvent")

def test_can_import_core():
    import openjiuwen
    assert openjiuwen is not None
```

Run: `pytest tests/test_smoke.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git init
git add pyproject.toml hi_agent/ tests/
git commit -m "feat: initialize hi-agent project skeleton with kernel and core dependencies"
```

### Task 1: 架构文档拆分

按 ARCHITECTURE.md §V2.8 的拆分建议，将 4070 行单文档拆为概览 + 6 个子规范。

**Files:**
- Modify: `ARCHITECTURE.md` (退化为概览 + 索引，~300 行)
- Create: `docs/specs/trajectory-spec.md`
- Create: `docs/specs/memory-spec.md`
- Create: `docs/specs/knowledge-spec.md`
- Create: `docs/specs/evolve-spec.md`
- Create: `docs/specs/security-spec.md`
- Create: `docs/specs/ops-spec.md`

- [ ] **Step 1: 创建 docs/specs/ 目录**

- [ ] **Step 2: 从 ARCHITECTURE.md 提取 trajectory-spec.md**

内容：§6（CTS + TrajectoryNode + 优化器）+ §14（状态机）+ §22（认知进展检测）+ §21（Route Engine 接口）

- [ ] **Step 3: 从 ARCHITECTURE.md 提取 memory-spec.md**

内容：§25.3（分层压缩记忆）+ §18（Task View，含 superseded 说明）

- [ ] **Step 4: 从 ARCHITECTURE.md 提取 knowledge-spec.md**

内容：§26（KnowledgeWiki）

- [ ] **Step 5: 从 ARCHITECTURE.md 提取 evolve-spec.md**

内容：§10（Inline+Batch 双轨）+ §8.3（Skill Registry + SkillContent）+ §24.4（EvalDataset）

- [ ] **Step 6: 从 ARCHITECTURE.md 提取 security-spec.md**

内容：§23（RBAC）+ §28（认证）+ §29（通信安全）+ §32（Gate 界面）

- [ ] **Step 7: 从 ARCHITECTURE.md 提取 ops-spec.md**

内容：§13（运维）+ §30（Runbook）+ §12（可观测）+ §33（多租户）

- [ ] **Step 8: 将 ARCHITECTURE.md 退化为概览 + 索引**

保留：文档头部 + 开发者快速入门 + 全局约定 + §1-§5（核心概念）+ §7（职责边界）+ §20（实现状态）+ §27（总结）+ Appendix A/B
删除：所有已提取到子规范的详细内容，替换为 `→ 详见 {spec_name}` 引用

- [ ] **Step 9: Commit**

```bash
git add docs/specs/ ARCHITECTURE.md
git commit -m "refactor: split ARCHITECTURE.md into 6 sub-specs + overview"
```

---

## 阶段 0: Spike（2-3 天）

验证关键假设，不追求代码质量——目的是发现规范中的问题。

### Task 2: Spike 1 — Run 骨架 S1→S5

**Goal:** 一个 quick_task family 的 Run 能走完 S1→S5 并成功完成。

**Files:**
- Create: `hi_agent/contracts.py` — TRACE 核心数据契约（TaskContract, TrajectoryNode, StageSummary 等）
- Create: `hi_agent/trajectory/node.py` — TrajectoryNode DAG 实现
- Create: `hi_agent/trajectory/optimizers.py` — greedy 优化器
- Create: `hi_agent/route_engine/base.py` — Route Engine 接口
- Create: `hi_agent/route_engine/rule_engine.py` — 规则引擎实现（不用 LLM）
- Create: `hi_agent/task_view/builder.py` — Task View 分层构建（L2→L1 简化版）
- Create: `hi_agent/runtime_adapter/mock_kernel.py` — MockKernel strict_mode
- Create: `hi_agent/runner.py` — Run 主循环
- Create: `hi_agent/identity.py` — action_id / task_view_id 确定性生成
- Test: `tests/test_spike_run.py`

- [ ] **Step 1: 定义核心契约 — contracts.py**

```python
"""TRACE core contracts — the data structures that cross all subsystems."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
import hashlib, base64

class StageState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"

class NodeType(StrEnum):
    DECISION = "decision"
    ACTION = "action"
    EVIDENCE = "evidence"
    SYNTHESIS = "synthesis"
    CHECKPOINT = "checkpoint"

class NodeState(StrEnum):
    OPEN = "open"
    EXPANDED = "expanded"
    PRUNED = "pruned"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass
class TaskContract:
    task_id: str
    goal: str
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    task_family: str = "quick_task"

@dataclass
class TrajectoryNode:
    node_id: str
    node_type: NodeType
    stage_id: str
    branch_id: str
    parent_ids: list[str] = field(default_factory=list)
    children_ids: list[str] = field(default_factory=list)
    description: str = ""
    action_ref: str | None = None
    evidence_ref: str | None = None
    local_score: float = 0.0
    propagated_score: float = 0.0
    visit_count: int = 0
    state: NodeState = NodeState.OPEN

@dataclass
class StageSummary:
    """L1 compressed stage summary — ≤ 2048 tokens."""
    stage_id: str
    stage_name: str
    findings: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    outcome: str = "active"

@dataclass
class RunIndex:
    """L2 run navigation layer — ≤ 512 tokens."""
    run_id: str
    task_goal_summary: str = ""
    stages_status: list[dict] = field(default_factory=list)
    current_stage: str = ""
    key_decisions: list[str] = field(default_factory=list)

def deterministic_id(*parts: str) -> str:
    """SHA-256 first 16 bytes, base64url encoded."""
    raw = "/".join(parts).encode()
    digest = hashlib.sha256(raw).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
```

- [ ] **Step 2: 实现 greedy 优化器**

```python
# hi_agent/trajectory/optimizers.py
"""Trajectory optimizers — greedy mode for V1."""
from __future__ import annotations
from hi_agent.contracts import TrajectoryNode, NodeState

class GreedyOptimizer:
    """Single-path greedy: always expand the best child, backtrack on failure."""

    def select_next(self, current: TrajectoryNode, children: list[TrajectoryNode]) -> TrajectoryNode | None:
        """Select the child with highest propagated_score. None if all terminal."""
        expandable = [c for c in children if c.state in (NodeState.OPEN, NodeState.EXPANDED)]
        if not expandable:
            return None
        return max(expandable, key=lambda n: n.propagated_score)

    def backpropagate(self, leaf: TrajectoryNode, dag: dict[str, TrajectoryNode], decay: float = 0.9) -> None:
        """Propagate quality signal from leaf to ancestors."""
        leaf.visit_count += 1
        current_id = leaf.node_id
        while True:
            node = dag[current_id]
            if not node.parent_ids:
                break
            parent_id = node.parent_ids[0]  # greedy: single parent
            parent = dag[parent_id]
            active_children = [dag[cid] for cid in parent.children_ids if dag[cid].state != NodeState.PRUNED]
            if active_children:
                parent.propagated_score = decay * sum(c.propagated_score for c in active_children) / len(active_children)
            parent.visit_count += 1
            current_id = parent_id
```

- [ ] **Step 3: 实现 Rule Engine（最简 Route Engine）**

```python
# hi_agent/route_engine/rule_engine.py
"""Minimal rule-based Route Engine for spike."""
from __future__ import annotations
from dataclasses import dataclass
from hi_agent.contracts import TrajectoryNode, NodeType, NodeState, deterministic_id

@dataclass
class BranchProposal:
    branch_id: str
    rationale: str
    action_kind: str

class RuleRouteEngine:
    """Fixed rule: one action per stage, no branching."""

    STAGE_ACTIONS = {
        "S1_understand": "analyze_goal",
        "S2_gather": "search_evidence",
        "S3_build": "build_draft",
        "S4_synthesize": "synthesize",
        "S5_review": "evaluate_acceptance",
    }

    def propose(self, stage_id: str, run_id: str, seq: int) -> list[BranchProposal]:
        action = self.STAGE_ACTIONS.get(stage_id, "unknown")
        bid = deterministic_id(run_id, stage_id, str(seq))
        return [BranchProposal(branch_id=bid, rationale=f"rule: {action}", action_kind=action)]
```

- [ ] **Step 4: 实现 MockKernel (strict_mode)**

```python
# hi_agent/runtime_adapter/mock_kernel.py
"""MockKernel with state machine validation (strict_mode)."""
from __future__ import annotations
from hi_agent.contracts import StageState

# Legal transitions per §14.3
_STAGE_TRANSITIONS: dict[StageState, set[StageState]] = {
    StageState.PENDING: {StageState.ACTIVE},
    StageState.ACTIVE: {StageState.BLOCKED, StageState.COMPLETED, StageState.FAILED},
    StageState.BLOCKED: {StageState.ACTIVE, StageState.FAILED},
    StageState.COMPLETED: set(),
    StageState.FAILED: set(),
}

class IllegalStateTransition(Exception):
    pass

class MockKernel:
    def __init__(self, *, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.stages: dict[str, StageState] = {}
        self.events: list[dict] = []
        self.task_views: dict[str, dict] = {}

    def open_stage(self, stage_id: str) -> None:
        if stage_id in self.stages:
            return  # idempotent
        self.stages[stage_id] = StageState.PENDING
        self._record("StageOpened", stage_id=stage_id)

    def mark_stage_state(self, stage_id: str, target: StageState) -> None:
        current = self.stages.get(stage_id)
        if current is None:
            raise ValueError(f"Stage {stage_id} not opened")
        if current == target:
            return  # idempotent no-op
        if self.strict_mode and target not in _STAGE_TRANSITIONS[current]:
            raise IllegalStateTransition(f"{stage_id}: {current} → {target} is illegal")
        self.stages[stage_id] = target
        self._record("StageStateChanged", stage_id=stage_id, from_state=current, to_state=target)

    def record_task_view(self, task_view_id: str, content: dict) -> str:
        if task_view_id in self.task_views:
            return task_view_id  # idempotent
        self.task_views[task_view_id] = content
        self._record("TaskViewRecorded", task_view_id=task_view_id)
        return task_view_id

    def _record(self, event_type: str, **payload) -> None:
        self.events.append({"event_type": event_type, **payload})

    # Test helpers
    def assert_stage_state(self, stage_id: str, expected: StageState) -> None:
        actual = self.stages.get(stage_id)
        assert actual == expected, f"Stage {stage_id}: expected {expected}, got {actual}"

    def get_events_of_type(self, event_type: str) -> list[dict]:
        return [e for e in self.events if e["event_type"] == event_type]
```

- [ ] **Step 5: 实现 Run 主循环**

```python
# hi_agent/runner.py
"""Run main loop — drives S1→S5 using greedy optimizer + rule engine."""
from __future__ import annotations
from hi_agent.contracts import (
    TaskContract, TrajectoryNode, NodeType, NodeState, StageState,
    StageSummary, RunIndex, deterministic_id,
)
from hi_agent.trajectory.optimizers import GreedyOptimizer
from hi_agent.route_engine.rule_engine import RuleRouteEngine
from hi_agent.runtime_adapter.mock_kernel import MockKernel

STAGES = ["S1_understand", "S2_gather", "S3_build", "S4_synthesize", "S5_review"]

class RunExecutor:
    def __init__(self, contract: TaskContract, kernel: MockKernel):
        self.contract = contract
        self.kernel = kernel
        self.run_id = deterministic_id(contract.task_id, "run")
        self.optimizer = GreedyOptimizer()
        self.route_engine = RuleRouteEngine()
        self.dag: dict[str, TrajectoryNode] = {}
        self.stage_summaries: dict[str, StageSummary] = {}
        self.action_seq = 0

    def execute(self) -> str:
        """Execute Run through all stages. Returns 'completed' or 'failed'."""
        for stage_id in STAGES:
            self.kernel.open_stage(stage_id)
            self.kernel.mark_stage_state(stage_id, StageState.ACTIVE)

            # Route: propose branch
            proposals = self.route_engine.propose(stage_id, self.run_id, self.action_seq)
            for p in proposals:
                node = TrajectoryNode(
                    node_id=deterministic_id(self.run_id, stage_id, p.branch_id, str(self.action_seq)),
                    node_type=NodeType.ACTION,
                    stage_id=stage_id,
                    branch_id=p.branch_id,
                    description=p.rationale,
                )
                self.dag[node.node_id] = node

                # Act: simulate action success
                node.state = NodeState.SUCCEEDED
                node.local_score = 1.0
                self.action_seq += 1

                # Backpropagate quality
                self.optimizer.backpropagate(node, self.dag)

            # Capture: create L1 stage summary
            self.stage_summaries[stage_id] = StageSummary(
                stage_id=stage_id,
                stage_name=stage_id,
                findings=[f"Completed {stage_id}"],
                outcome="succeeded",
            )

            self.kernel.mark_stage_state(stage_id, StageState.COMPLETED)

        return "completed"
```

- [ ] **Step 6: 写集成测试**

```python
# tests/test_spike_run.py
"""Spike 1: verify Run S1→S5 completes with greedy optimizer."""
from hi_agent.contracts import TaskContract, StageState
from hi_agent.runtime_adapter.mock_kernel import MockKernel
from hi_agent.runner import RunExecutor, STAGES

def test_run_s1_to_s5_completes():
    contract = TaskContract(task_id="test-001", goal="spike test", task_family="quick_task")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel)
    result = executor.execute()
    assert result == "completed"

def test_all_stages_reach_completed():
    contract = TaskContract(task_id="test-002", goal="stage check")
    kernel = MockKernel(strict_mode=True)
    RunExecutor(contract, kernel).execute()
    for stage_id in STAGES:
        kernel.assert_stage_state(stage_id, StageState.COMPLETED)

def test_trajectory_nodes_created():
    contract = TaskContract(task_id="test-003", goal="node check")
    kernel = MockKernel(strict_mode=True)
    executor = RunExecutor(contract, kernel)
    executor.execute()
    assert len(executor.dag) == 5  # one node per stage

def test_action_ids_are_deterministic():
    contract = TaskContract(task_id="test-004", goal="determinism check")
    kernel1, kernel2 = MockKernel(), MockKernel()
    e1, e2 = RunExecutor(contract, kernel1), RunExecutor(contract, kernel2)
    e1.execute(); e2.execute()
    assert list(e1.dag.keys()) == list(e2.dag.keys())

def test_illegal_stage_transition_rejected():
    kernel = MockKernel(strict_mode=True)
    kernel.open_stage("s1")
    # PENDING → COMPLETED is illegal (must go through ACTIVE)
    import pytest
    from hi_agent.runtime_adapter.mock_kernel import IllegalStateTransition
    with pytest.raises(IllegalStateTransition):
        kernel.mark_stage_state("s1", StageState.COMPLETED)
```

- [ ] **Step 7: 运行测试**

Run: `pytest tests/test_spike_run.py -v`
Expected: 5 passed

- [ ] **Step 8: Commit**

```bash
git add hi_agent/ tests/test_spike_run.py
git commit -m "spike: Run S1→S5 skeleton with greedy optimizer and MockKernel strict_mode"
```

### Task 3: Spike 2 — identity 确定性验证

**Files:**
- Create: `tests/test_spike_identity.py`

- [ ] **Step 1: 写 identity 确定性测试**

```python
# tests/test_spike_identity.py
"""Spike: verify action_id and task_view_id are deterministic and stable."""
from hi_agent.contracts import deterministic_id

def test_deterministic_id_same_input_same_output():
    a = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "0")
    b = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "0")
    assert a == b

def test_deterministic_id_different_input_different_output():
    a = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "0")
    b = deterministic_id("run1", "s1", "b1", "search_arxiv_v1", "1")
    assert a != b

def test_task_view_id_includes_policy_version():
    """Same evidence but different policy → different task_view_id."""
    tv1 = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v1")
    tv2 = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v2")
    assert tv1 != tv2

def test_task_view_id_same_evidence_same_policy():
    """Same everything → same task_view_id (idempotent rebuild)."""
    tv1 = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v1")
    tv2 = deterministic_id("run1", "s1", "b1", "0", "evidence_hash_1", "policy_v1")
    assert tv1 == tv2
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_spike_identity.py -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_spike_identity.py
git commit -m "spike: verify action_id and task_view_id deterministic generation"
```

### Task 4: Spike 3 — 死路检测

**Files:**
- Create: `hi_agent/trajectory/dead_end.py`
- Test: `tests/test_spike_dead_end.py`

- [ ] **Step 1: 实现死路检测**

```python
# hi_agent/trajectory/dead_end.py
"""Dead-end detection — §14.7: all branches eliminated in a stage."""
from __future__ import annotations
from hi_agent.contracts import TrajectoryNode, NodeState

def detect_dead_end(stage_id: str, dag: dict[str, TrajectoryNode]) -> bool:
    """Return True if all nodes in stage_id are terminal and none succeeded."""
    stage_nodes = [n for n in dag.values() if n.stage_id == stage_id]
    if not stage_nodes:
        return False
    terminal_states = {NodeState.PRUNED, NodeState.FAILED, NodeState.SUCCEEDED}
    all_terminal = all(n.state in terminal_states for n in stage_nodes)
    any_succeeded = any(n.state == NodeState.SUCCEEDED for n in stage_nodes)
    return all_terminal and not any_succeeded
```

- [ ] **Step 2: 写测试**

```python
# tests/test_spike_dead_end.py
from hi_agent.contracts import TrajectoryNode, NodeType, NodeState
from hi_agent.trajectory.dead_end import detect_dead_end

def test_no_dead_end_when_branch_succeeded():
    dag = {
        "n1": TrajectoryNode("n1", NodeType.ACTION, "S3", "b1", state=NodeState.SUCCEEDED),
        "n2": TrajectoryNode("n2", NodeType.ACTION, "S3", "b2", state=NodeState.FAILED),
    }
    assert detect_dead_end("S3", dag) is False

def test_dead_end_when_all_failed():
    dag = {
        "n1": TrajectoryNode("n1", NodeType.ACTION, "S3", "b1", state=NodeState.FAILED),
        "n2": TrajectoryNode("n2", NodeType.ACTION, "S3", "b2", state=NodeState.PRUNED),
    }
    assert detect_dead_end("S3", dag) is True

def test_no_dead_end_when_open_nodes_exist():
    dag = {
        "n1": TrajectoryNode("n1", NodeType.ACTION, "S3", "b1", state=NodeState.FAILED),
        "n2": TrajectoryNode("n2", NodeType.ACTION, "S3", "b2", state=NodeState.OPEN),
    }
    assert detect_dead_end("S3", dag) is False
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_spike_dead_end.py -v`
Expected: 3 passed

- [ ] **Step 4: Commit**

```bash
git add hi_agent/trajectory/dead_end.py tests/test_spike_dead_end.py
git commit -m "spike: dead-end detection for §14.7"
```

---

## 阶段 1: MVP（第一个 Run 可跑通）

Spike 验证通过后，将 spike 代码重构为生产质量。阶段 1 的 scope 见 §20.2。

> **注意：阶段 1 的详细实施计划将在 Spike 完成后，基于 Spike 中发现的规范歧义和性能数据单独编写。** 以下是阶段 1 的任务分解大纲（不含具体代码）：

### Task 5: 核心契约层重构

将 spike 的 `contracts.py` 拆分为独立模块，补充完整的类型定义：

- `hi_agent/contracts/task.py` — TaskContract, AcceptanceCriteria
- `hi_agent/contracts/trajectory.py` — TrajectoryNode, NodeType, NodeState, BranchView
- `hi_agent/contracts/stage.py` — StageState, StageDef, StageGraphDef
- `hi_agent/contracts/identity.py` — deterministic_id, action_id, task_view_id
- `hi_agent/contracts/policy.py` — PolicyVersionSet, PolicyContentSpec
- `hi_agent/contracts/cts_budget.py` — CTSBudget, CTSBudgetTemplate
- `hi_agent/contracts/config.py` — TaskFamilyConfig

### Task 6: 轨迹子系统

- `hi_agent/trajectory/node.py` — TrajectoryNode DAG 实现（CRUD + parent/child 管理）
- `hi_agent/trajectory/optimizer_base.py` — TrajectoryOptimizer protocol
- `hi_agent/trajectory/greedy.py` — GreedyOptimizer（从 spike 重构）
- `hi_agent/trajectory/backpropagation.py` — 质量信号回传算法
- `hi_agent/trajectory/dead_end.py` — 死路检测（从 spike 重构）
- `hi_agent/trajectory/stage_graph.py` — Stage Graph 定义 + 形式化验证（BFS 可达性、死锁检测）

### Task 7: Route Engine

- `hi_agent/route_engine/protocol.py` — RouteEngineInput / RouteEngineOutput 协议定义
- `hi_agent/route_engine/rule_engine.py` — 规则引擎实现（从 spike 重构，支持 TaskFamilyConfig）
- `hi_agent/route_engine/acceptance.py` — AcceptanceCriteriaEvaluator

### Task 8: 分层记忆

- `hi_agent/memory/l0_raw.py` — L0 原始证据存储（对接 agent-kernel event log）
- `hi_agent/memory/l1_compressed.py` — L1 Stage 压缩（异步 + fallback）
- `hi_agent/memory/l2_index.py` — L2 Run 导航层
- `hi_agent/memory/compressor.py` — LLM 压缩调用封装（mock 实现优先）

### Task 9: Task View 构建

- `hi_agent/task_view/builder.py` — 从分层记忆构建 Task View（L2→L1→L3→Knowledge）
- `hi_agent/task_view/token_budget.py` — 固定 token budget 分配策略

### Task 10: RuntimeAdapter

- `hi_agent/runtime_adapter/protocol.py` — RuntimeAdapter 协议（与 agent-kernel 的接口）
- `hi_agent/runtime_adapter/mock_kernel.py` — MockKernel strict_mode（从 spike 重构）
- `hi_agent/runtime_adapter/kernel_adapter.py` — 真实 agent-kernel adapter（阶段 1 末期）

### Task 11: Capability Registry

- `hi_agent/capability/registry.py` — CapabilityDescriptor 注册 + 依赖拓扑排序
- `hi_agent/capability/circuit_breaker.py` — 熔断器状态机
- `hi_agent/capability/invoker.py` — gRPC Capability 调用（mock 实现优先）

### Task 12: Event Schema + 事件日志

- `hi_agent/events/envelope.py` — EventEnvelope 定义
- `hi_agent/events/payload_schemas.py` — 11 种事件 payload schema
- `hi_agent/events/emitter.py` — 事件发射器（写入 agent-kernel event log）

### Task 13: 健康检查 + 优雅停机

- `hi_agent/management/health.py` — /live, /ready, /status 端点
- `hi_agent/management/shutdown.py` — 5 步优雅停机协议

### Task 14: Run 主循环重构

- `hi_agent/runner.py` — 重构为支持完整 Stage Graph 遍历、Task View 构建、事件发射的生产级实现

### Task 15: 阶段 1 集成测试

- `tests/integration/test_run_lifecycle.py` — Run S1→S5 完整生命周期
- `tests/integration/test_stage_transitions.py` — 所有合法/非法状态转移
- `tests/integration/test_dead_end_recovery.py` — 死路检测 + Gate B 触发
- `tests/integration/test_deterministic_replay.py` — 同一 Run 两次执行产生相同 ID

---

## 阶段 2: 生产就绪

> **阶段 2 的详细计划将在阶段 1 完成后编写。** 大纲如下：

### Task 16-19: 安全层
- RBAC 执行（mTLS + JWT middleware）
- Skill Registry 基础实现
- Human Gate 审批 API
- Secret 管理集成

### Task 20-23: 可观测层
- 核心指标埋点（run_success_rate + avg_token_per_run + 7 个 V2.8 新增指标）
- 分布式追踪 + callback 关联
- 审计日志 + HLC
- NotificationBackend 实现

### Task 24-26: 进化层（Inline）
- L3 Episodic 生成 + 去重
- KnowledgeWiki 基础实现（ingest + query + IndexPage）
- Inline Evolution 集成（Run 完成时自动触发 L3 + ingest）

---

## 阶段 3: 完整功能

> **阶段 3 的详细计划将在阶段 2 完成后编写。** 大纲如下：

### Task 27-30: 进化层（Batch）
- Evolve Pipeline: human_guided + parameter_tuning 策略
- route_replay 离线评估
- A/B 实验 + QualityGate
- 低频轻量路径

### Task 31-33: Skill 系统
- SkillContent 实现（prompt_template + action_pattern）
- Skill 注入 Task View
- Skill 结晶算法（skill_extraction）

### Task 34-36: 高级轨迹
- MCTS 优化器
- beam_search 优化器
- todo_dag 优化器

### Task 37-38: 运维完善
- 多实例协调 + 孤儿接管
- 成本归因 + 预算预警

---

## 文件结构总览

```
hi-agent/
├── ARCHITECTURE.md                    # 概览 + 索引（~300 行）
├── CLAUDE.md
├── pyproject.toml
├── docs/
│   ├── specs/
│   │   ├── trajectory-spec.md         # §6 + §14 + §22 + §21
│   │   ├── memory-spec.md             # §25.3 + §18
│   │   ├── knowledge-spec.md          # §26
│   │   ├── evolve-spec.md             # §10 + §8.3 + §24.4
│   │   ├── security-spec.md           # §23 + §28 + §29 + §32
│   │   └── ops-spec.md               # §13 + §30 + §12 + §33
│   └── superpowers/
│       └── plans/
│           └── 2026-04-05-trace-implementation-master-plan.md  # 本文件
├── hi_agent/
│   ├── __init__.py
│   ├── py.typed
│   ├── contracts/                     # 核心数据契约
│   │   ├── __init__.py
│   │   ├── task.py
│   │   ├── trajectory.py
│   │   ├── stage.py
│   │   ├── identity.py
│   │   ├── policy.py
│   │   ├── cts_budget.py
│   │   └── config.py
│   ├── trajectory/                    # 轨迹子系统
│   │   ├── __init__.py
│   │   ├── node.py
│   │   ├── optimizer_base.py
│   │   ├── greedy.py
│   │   ├── backpropagation.py
│   │   ├── dead_end.py
│   │   └── stage_graph.py
│   ├── route_engine/                  # 路由引擎
│   │   ├── __init__.py
│   │   ├── protocol.py
│   │   ├── rule_engine.py
│   │   └── acceptance.py
│   ├── memory/                        # 分层记忆
│   │   ├── __init__.py
│   │   ├── l0_raw.py
│   │   ├── l1_compressed.py
│   │   ├── l2_index.py
│   │   └── compressor.py
│   ├── task_view/                     # Task View 构建
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   └── token_budget.py
│   ├── runtime_adapter/               # agent-kernel 适配
│   │   ├── __init__.py
│   │   ├── protocol.py
│   │   ├── mock_kernel.py
│   │   └── kernel_adapter.py
│   ├── capability/                    # Capability 管理
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   ├── circuit_breaker.py
│   │   └── invoker.py
│   ├── events/                        # 事件系统
│   │   ├── __init__.py
│   │   ├── envelope.py
│   │   ├── payload_schemas.py
│   │   └── emitter.py
│   ├── management/                    # 运维接口
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── shutdown.py
│   └── runner.py                      # Run 主循环
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_smoke.py
    ├── test_spike_run.py
    ├── test_spike_identity.py
    ├── test_spike_dead_end.py
    └── integration/
        ├── __init__.py
        ├── test_run_lifecycle.py
        ├── test_stage_transitions.py
        ├── test_dead_end_recovery.py
        └── test_deterministic_replay.py
```

---

## 里程碑验收标准

| 里程碑 | 验收条件 | 预计时间 |
|---|---|---|
| **Spike 完成** | 5+4+3=12 个测试全部通过；发现的规范歧义已记录 | 2-3 天 |
| **阶段 1 完成** | quick_task Run S1→S5 完整通过（MockKernel）；所有 ID 确定性可验证；死路检测工作；Stage Graph 形式化验证通过 | 3-4 周 |
| **阶段 2 完成** | 多实例环境可运行；基础告警覆盖；Inline Evolution（L3 + KnowledgeWiki ingest）自动触发 | 3-4 周 |
| **阶段 3 完成** | 第一个 EvolveSession 成功晋升一个 Skill 版本；MCTS/beam/todo_dag 可配置使用 | 4-6 周 |
