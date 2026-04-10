# hi-agent 执行计划：可靠性、自动优化与发布治理

## 目标
在现有代码基础上，按顺序落地以下能力并可测：

1. 运行可靠性增强（持久化与回放）
2. 自动优化闭环（建议 -> 配置回写）
3. 发布治理（SLO gate）
4. 验证与可运维化

## 执行顺序与验收

### 阶段 1：运行可靠性增强

#### 1.1 RunManager 持久化恢复
- 内容：
  - 为 `RunManager` 增加可选状态持久化路径（JSON）。
  - 进程重启后可恢复 run 元数据（至少 `created/running/failed/completed` 状态可见）。
- 验收：
  - 新建 run 后重建 manager，`list_runs()` 中可见原 run。
  - 持久化失败不导致主流程崩溃（best-effort）。

#### 1.2 事件回放通道
- 内容：
  - API 增加回放端点，支持按 `run_id` 回看历史事件文件。
  - 回放结果包含解析失败行统计与事件条目。
- 验收：
  - 可返回 `run_id` 对应事件列表和 `bad_lines` 计数。
  - 文件不存在时返回空列表而非 500。

### 阶段 2：自动优化闭环

#### 2.1 运行时配置存储接入 server
- 内容：
  - 在 `AgentServer` 内持有 `RuntimeConfigStore + ConfigHistory`。
  - 初始配置来自 `TraceConfig`。
- 验收：
  - 可读取当前配置版本和快照。

#### 2.2 /ops/autotune
- 内容：
  - 新增端点：从 `health + metrics` 生成容量/成本调优建议并自动 patch runtime config。
  - 返回：应用的 patch、新版本、建议来源。
- 验收：
  - 压力场景下能输出非空 patch。
  - patch 会进入 config history。

### 阶段 3：发布治理（SLO gate）

#### 3.1 /ops/release-gate
- 内容：
  - 基于 SLO（成功率、延迟）和队列风险（拒绝/超时）做发布准入判定。
  - 输出 `pass/fail` 与阻断原因。
- 验收：
  - 正常输入给出 pass。
  - 高风险输入给出 fail 且有结构化 reason 列表。

### 阶段 4：验证与交付

#### 4.1 测试
- 覆盖新增能力：
  - RunManager 持久化恢复
  - 事件回放端点
  - /ops/autotune
  - /ops/release-gate

#### 4.2 运维输出
- `GET /ops`、`GET /health`、`GET /metrics/json`、`GET /ops/release-gate` 联调说明。

## 不在本轮范围（后续）
- 真正分布式队列（Kafka/Redis/Temporal task queue）
- 多租户隔离与细粒度 RBAC
- 跨实例 exactly-once 语义

