# hi-agent Capability Boundaries

**Version**: 1.0 | **Date**: 2026-04-12

本文档声明 hi-agent 当前版本各模块的能力边界：哪些已交付、哪些是实验性、哪些是使用方责任。

---

## 1. 已交付能力（Production-Ready）

以下能力经过完整工程验证，可用于生产接入：

### 1.1 核心执行引擎

| 能力 | 状态 | 说明 |
|------|------|------|
| 线性 stage 执行 (`execute()`) | ✅ 生产 | 向后兼容，稳定 |
| 图驱动执行 (`execute_graph()`) | ✅ 生产 | DAG + 回溯边 + 多路由 |
| 异步执行 (`execute_async()`) | ✅ 生产 | asyncio + Semaphore 背压 |
| 会话恢复 (`resume --checkpoint`) | ✅ 生产 | L0 JSONL 持久化 |
| 并发隔离 (RunContext) | ✅ 生产 | per-run 状态隔离，2555 测试覆盖 |

### 1.2 中间件层（四阶段）

| 中间件 | 状态 | 说明 |
|--------|------|------|
| Perception | ✅ 生产 | 多模态解析、实体提取、摘要 |
| Control | ✅ 生产 | TrajectoryGraph 分解、资源绑定 |
| Execution | ✅ 生产 | 幂等执行、降级模式（`_degraded`） |
| Evaluation | ✅ 生产 | 质量评估、反思、升级 |

### 1.3 认知子系统

| 子系统 | 状态 | 说明 |
|--------|------|------|
| 三层记忆（短/中/长期） | ✅ 生产 | Dream 巩固、图级长期记忆 |
| 知识系统（Wiki + 图 + BM25） | ✅ 生产 | 四层检索，自动入库 |
| 技能系统（SKILL.md + 演化） | ✅ 生产 | 多路径发现、版本管理、A/B champion/challenger |
| ContextManager（7分区压缩） | ✅ 生产 | 四级阈值，断路器 |

### 1.4 任务管理

| 能力 | 状态 | 说明 |
|------|------|------|
| RestartPolicyEngine | ✅ 生产 | retry/reflect/escalate/abort，默认策略已配置 |
| ReflectionOrchestrator | ✅ 生产 | LLM 驱动的失败恢复 |
| BudgetGuard | ✅ 生产 | 层级下降 + 节点跳过 |
| 人工审核门（A/B/C/D） | ✅ 生产 | contract_correction/route/review/final_approval |

### 1.5 API

| 端点 | 状态 | 说明 |
|------|------|------|
| `GET /ready` | ✅ 生产 | Readiness 合约端点 |
| `POST /runs` | ✅ 生产 | 任务提交 |
| `GET /runs/{id}` | ✅ 生产 | 运行状态查询 |
| `GET /manifest` | ✅ 生产 | 动态平台信息 |
| `POST /memory/dream` | ✅ 生产 | Dream 巩固触发 |
| `GET /knowledge/query` | ✅ 生产 | 知识检索 |
| `POST /skills/evolve` | ✅ 生产 | 技能演化触发 |
| `GET /skills/list` | ✅ 生产 | 技能列表（含 source） |

---

## 2. 实验性能力（Experimental）

以下能力已有工程实现，但接口可能在后续版本变更：

### 2.1 MCP 层

| 能力 | 状态 | 注意事项 |
|------|------|---------|
| MCPRegistry（注册 + 健康检查） | 🧪 实验性 | 接口稳定，但 transport 层仅支持 http |
| MCPBinding（工具绑定到 capability） | 🧪 实验性 | 需要 MCP server 符合标准协议 |
| `GET /mcp/status`, `/mcp/tools` | 🧪 实验性 | 实现完整，但 MCP 生态仍在演进 |

### 2.2 插件系统

| 能力 | 状态 | 注意事项 |
|------|------|---------|
| PluginLoader（manifest 发现） | 🧪 实验性 | plugin.json 格式可能调整 |
| Plugin lifecycle hooks | 🧪 实验性 | on_load/on_activate/on_deactivate 已定义，hook 触发点待完善 |
| `GET /plugins/list`, `/plugins/status` | 🧪 实验性 | 实现完整 |

### 2.3 Capability Bundle

| 能力 | 状态 | 注意事项 |
|------|------|---------|
| ResearchBundle（6 项能力） | 🧪 实验性 | 能力定义完整，后端实现取决于工具绑定 |
| `CapabilityRegistry.register_bundle()` | 🧪 实验性 | 接口已定义，后续支持 config 级 bundle 选择 |

### 2.4 TierRouter / ModelSelector

| 能力 | 状态 | 注意事项 |
|------|------|---------|
| 基于 `skill_confidence` 的层级降级 | 🧪 实验性 | 信号收集机制待完善 |
| Budget-aware 模型选择 | 🧪 实验性 | 与 LLM provider 定价数据联动 |

---

## 3. 使用方责任边界

以下**不在 hi-agent 平台覆盖范围内**，由使用方负责：

### 3.1 LLM Provider

- API Key 的申请、续费、安全保管
- API 配额管理、限流处理
- 模型版本选择（影响输出质量）
- LLM provider 的服务可用性 SLA

### 3.2 外部工具后端

- MCP server 的部署、运维、升级
- 工具调用结果的业务正确性验证
- 工具的安全审计（hi-agent Harness 提供机制，但审计策略由使用方定义）

### 3.3 技能质量

- 自定义 SKILL.md 的内容质量
- 技能的领域适配性
- 技能演化后的回归验证

### 3.4 数据与隐私

- 传入 goal 的数据脱敏
- 记忆/知识系统中的敏感数据管理
- 结果的合规性审查

### 3.5 基础设施

- hi-agent 服务的部署、扩容、监控
- 存储路径（checkpoint、memory、knowledge）的备份
- 网络隔离、访问控制

---

## 4. 能力演进路线

### 近期（P1）
- MCP transport 层扩展（stdio、SSE）
- Plugin hook 触发点完善
- ResearchBundle 工具后端实现

### 中期
- 多 agent 协作（hi-agent 作为 coordinator）
- 跨 session 记忆联邦
- 技能市场（skill registry）

### 长期
- 自主技能发现与组合
- 成本持续下降：随技能成熟度提升，更多任务由 `light` 模型完成

---

## 5. 版本兼容性承诺

| 接口 | 承诺 |
|------|------|
| `POST /runs`, `GET /runs/{id}` | 主版本内向后兼容 |
| `GET /ready`, `GET /manifest` | 主版本内向后兼容 |
| SKILL.md frontmatter 格式 | 次版本内向后兼容 |
| plugin.json 格式 | 实验阶段不保证兼容 |
| MCP 注册 API | 实验阶段不保证兼容 |
| Python SDK 内部接口 | 不承诺，以 HTTP API 为稳定接口 |

**推荐**：使用方通过 HTTP API 接入，而非直接调用 Python 内部模块，以获得最强的版本稳定性保障。
