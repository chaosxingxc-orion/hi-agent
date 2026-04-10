# Agent-Kernel 演进提案

> 来源: hi-agent 集成实践
> 日期: 2026-04-09
> 状态: **已实施** (agent-kernel v0.2.0)

## 背景

hi-agent 已从"代码复制 + sys.path hack"完成迁移到正式依赖 agent-kernel (GitHub `v0.2.0`)。
以下提案项已全部在 agent-kernel v0.2.0 中实施。

---

## Tier 1: 必要修改 — 已完成 ✓

### 1.1 TaskRestartPolicy 增加 `max_backoff_ms` 字段

**文件**: `agent_kernel/kernel/task_manager/contracts.py`

**现状**:
```python
@dataclass(frozen=True, slots=True)
class TaskRestartPolicy:
    max_attempts: int = 3
    backoff_base_ms: int = 1_000
    on_exhausted: Literal["reflect", "escalate", "abort"] = "escalate"
    heartbeat_timeout_ms: int = 300_000
```

**建议增加**:
```python
    max_backoff_ms: int = 30_000  # 指数退避上限
```

**理由**: 指数退避需要封顶，否则第 10 次重试将等待 `1000 * 2^8 = 256秒`。hi-agent 当前的退避计算为:
```python
delay = min(backoff_base_ms * (2 ** max(0, attempt_seq - 2)), max_backoff_ms)
```
这是通用的重试模式，属于基础设施层，不应由上层自行实现。

---

### 1.2 EffectClass / SideEffectClass 改为 StrEnum

**文件**: `agent_kernel/kernel/contracts.py`

**现状**: 使用 `Literal` 类型
```python
EffectClass = Literal["read_only", "idempotent_write", "compensatable_write", "irreversible_write"]
SideEffectClass = Literal["read_only", "local_write", "external_write", "irreversible_submit"]
```

**建议改为**:
```python
from enum import StrEnum

class EffectClass(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    COMPENSATABLE_WRITE = "compensatable_write"
    IRREVERSIBLE_WRITE = "irreversible_write"

class SideEffectClass(StrEnum):
    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXTERNAL_WRITE = "external_write"
    IRREVERSIBLE_SUBMIT = "irreversible_submit"
```

**理由**:
- 上层（hi-agent）需要 Enum 行为：迭代 (`for e in EffectClass`)、集合成员 (`e in {EffectClass.READ_ONLY}`)、`.value` 提取、`isinstance` 检查、作为 dict key
- `StrEnum` 既保持字符串兼容（JSON 序列化、与 Literal 等值比较），又支持 Enum 方法
- `StrEnum` 是 Python 3.11+ 标准库，agent-kernel 要求 >=3.12，无兼容问题
- 当前 agent-kernel 内部使用这些类型的地方也能无缝过渡（字符串比较仍然有效）

**影响范围**: agent-kernel 内部需要检查所有使用 `EffectClass` / `SideEffectClass` 的地方，确保字符串赋值改为枚举成员。主要涉及:
- `kernel/contracts.py` — Action dataclass 的 effect_class 和 side_effect_class 字段类型注解
- 所有构造 Action 的地方

---

### 1.3 失败码映射上游化

**文件**: 建议新建 `agent_kernel/kernel/failure_mappings.py`

**现状**: agent-kernel 定义了 `TraceFailureCode` (12 码)，但没有标准的恢复映射和人工审批门映射。hi-agent 自行维护了这两个映射。

**建议增加**:
```python
from agent_kernel.kernel.contracts import TraceFailureCode

# 失败码 → 推荐恢复动作（可被上层覆盖）
FAILURE_RECOVERY_MAP: dict[TraceFailureCode, str] = {
    TraceFailureCode.MISSING_EVIDENCE: "task_view_degradation",
    TraceFailureCode.INVALID_CONTEXT: "pre_call_abort",
    TraceFailureCode.HARNESS_DENIED: "approval_escalation",
    TraceFailureCode.MODEL_OUTPUT_INVALID: "retry_or_downgrade_model",
    TraceFailureCode.MODEL_REFUSAL: "alternate_model_or_human",
    TraceFailureCode.CALLBACK_TIMEOUT: "recovery_path",
    TraceFailureCode.NO_PROGRESS: "watchdog_handling",
    TraceFailureCode.CONTRADICTORY_EVIDENCE: "human_gate_c",
    TraceFailureCode.UNSAFE_ACTION_BLOCKED: "human_gate_approval",
    TraceFailureCode.BUDGET_EXHAUSTED: "cts_termination_or_gate_b",
    TraceFailureCode.EXPLORATION_BUDGET_EXHAUSTED: "cts_termination_or_gate_b",
    TraceFailureCode.EXECUTION_BUDGET_EXHAUSTED: "cts_termination_or_gate_b",
}

# 失败码 → 人工审批门类型（None = 无需人工介入）
FAILURE_GATE_MAP: dict[TraceFailureCode, str | None] = {
    TraceFailureCode.MISSING_EVIDENCE: None,
    TraceFailureCode.INVALID_CONTEXT: None,
    TraceFailureCode.HARNESS_DENIED: "gate_d",
    TraceFailureCode.MODEL_OUTPUT_INVALID: None,
    TraceFailureCode.MODEL_REFUSAL: None,
    TraceFailureCode.CALLBACK_TIMEOUT: None,
    TraceFailureCode.NO_PROGRESS: "gate_b",
    TraceFailureCode.CONTRADICTORY_EVIDENCE: "gate_a",
    TraceFailureCode.UNSAFE_ACTION_BLOCKED: "gate_d",
    TraceFailureCode.BUDGET_EXHAUSTED: "gate_b",
    TraceFailureCode.EXPLORATION_BUDGET_EXHAUSTED: "gate_b",
    TraceFailureCode.EXECUTION_BUDGET_EXHAUSTED: "gate_b",
}
```

**理由**:
- 这是 TRACE 架构的标准故障处理语义，应该有统一的参考定义
- 覆盖了 agent-kernel 新增的 2 个 budget 细分码
- 标注为"推荐映射"，上层可覆盖

---

## Tier 2: 建议改进（不阻塞迁移，但有价值）

### 2.1 BUDGET_EXHAUSTED 码的统一策略

**现状**:
- hi-agent 使用 `BUDGET_EXHAUSTED`（统一码）
- agent-kernel 拆分为 `EXPLORATION_BUDGET_EXHAUSTED` + `EXECUTION_BUDGET_EXHAUSTED`

**建议**: 保持 agent-kernel 的细分设计（更精确），但确保 hi-agent 的 `BUDGET_EXHAUSTED` 能映射到两者之一。在 `TraceFailureCode` 中增加一个辅助方法:
```python
@classmethod
def is_budget_exhausted(cls, code: "TraceFailureCode") -> bool:
    return code in (cls.BUDGET_EXHAUSTED, cls.EXPLORATION_BUDGET_EXHAUSTED, cls.EXECUTION_BUDGET_EXHAUSTED)
```

### 2.2 TaskAttempt 作为公共 API 文档化

**文件**: `agent_kernel/kernel/task_manager/contracts.py`

hi-agent 当前使用自定义的 `TaskAttemptRecord`（轻量版），应迁移到 agent-kernel 的 `TaskAttempt`（包含时间戳、严格的 outcome 类型、reflection_output）。建议在 agent-kernel 的文档中明确标注 `TaskAttempt` 为公共 API。

### 2.3 InMemoryKernelRuntimeEventLog 作为测试工具导出

**文件**: `agent_kernel/kernel/persistence/`

建议在 `agent_kernel.testing` 或 `agent_kernel.kernel.persistence` 中明确导出以下类作为公共测试工具:
- `InMemoryKernelRuntimeEventLog`
- `InMemoryDedupeStore`
- `StaticRecoveryGateService`

这些类对上层智能体的单元测试至关重要。

---

## 不需要上游化的部分（hi-agent 独有）

| 模块 | 原因 |
|------|------|
| `ReflectionOrchestrator` / `ReflectionBridge` | 任务级反思（跨多次尝试），与 agent-kernel 的脚本级反思层级不同 |
| `ProgressWatchdog` | 基于成功率的应用层监控，与 agent-kernel 的心跳监控互补 |
| `ActionState` (8 状态) | 治理层状态机，agent-kernel 通过事件隐式追踪 |
| `MockKernel` | adapter 层测试工具，agent-kernel 用 Temporal 测试服务器 |
| `FAILURE_RECOVERY_MAP` / `FAILURE_GATE_MAP` 的具体值 | 即使上游化为参考映射，hi-agent 可能需要覆盖 |

---

## Tier 3: 打包与安装问题

### 3.1 Git Submodule 阻塞 pip install

**问题**: agent-kernel 仓库包含两个 git submodule (`external/temporal`、`external/agent-core`)。
通过 `pip install git+https://github.com/.../agent-kernel.git@v0.1.0` 安装时，pip 会执行
`git submodule update --init --recursive`，而 temporal 仓库包含超长文件路径，在 Windows 上
因 260 字符路径限制导致 checkout 失败。

**建议**:
1. 将 submodule 从打包构建中排除（在 `pyproject.toml` 中配置 hatch 排除 `external/`）
2. 或移除 temporal submodule（agent-kernel 不直接编译 temporal，只通过 SDK 调用）
3. 短期 workaround: 使用本地 editable install (`pip install -e ../agent-kernel --no-deps`)

---

## 实施建议

1. **v0.2.0**: 包含 Tier 1 的三项修改（max_backoff_ms、StrEnum、failure mappings）+ Tier 3 打包修复
2. **v0.2.1**: 包含 Tier 2 的改进
3. hi-agent 迁移完成后，锁定到对应的 agent-kernel tag

---

## hi-agent 落地补充（2026-04-10）

以下为 hi-agent 侧已完成的工程收口，用于消除与本提案之间的实践偏差：

1. **移除测试层 sys.path 注入**
- 删除 `tests/conftest.py` 中对 `../agent-kernel` 的路径注入逻辑。
- 测试与运行统一依赖 `pyproject.toml` 中的正式依赖安装流程。

2. **TaskAttempt 对齐**
- `hi_agent.task_mgmt.restart_policy` 以 `agent-kernel` 的 `TaskAttempt` 为主类型。
- `TaskAttemptRecord` 保留为兼容别名，仅用于平滑迁移。

3. **budget failure 兼容统一入口**
- `hi_agent.failures.taxonomy.is_budget_exhausted_failure_code` 统一处理：
  - 上游细分码：`exploration_budget_exhausted` / `execution_budget_exhausted`
  - 兼容历史码：`budget_exhausted`
- 说明：上游 `TraceFailureCode` 当前不包含 `BUDGET_EXHAUSTED` 成员。

4. **上游测试工具桥接**
- 新增 `hi_agent.testing`，统一 re-export：
  - `InMemoryKernelRuntimeEventLog`
  - `InMemoryDedupeStore`
  - `StaticRecoveryGateService`
- 便于 hi-agent 测试与上游测试工具保持一致入口。

### 仍需上游处理（超出 hi-agent 仓库边界）

- Tier 3 的 submodule 打包/安装问题属于 `agent-kernel` 仓库本身。
- 在上游彻底修复前，hi-agent 侧继续保留以下实践：
  - 依赖固定到 `agent-kernel` tag（当前 `v0.2.0`）
  - 安装失败时采用本地 editable 方案作为 fallback（`pip install -e ../agent-kernel --no-deps`）
