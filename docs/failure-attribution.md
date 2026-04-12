# hi-agent Failure Attribution

**Version**: 1.0 | **Date**: 2026-04-12

本文档定义：当 hi-agent 出现故障时，哪些是平台责任，哪些是使用方配置问题。清晰的责任边界是快速定位和解决问题的前提。

---

## 归因矩阵

### A. 平台责任（hi-agent team owns）

| 现象 | 错误类型 | 归因 | 处置 |
|------|---------|------|------|
| `GET /ready` 返回 5xx | 服务不可用 | 平台内部错误 | 提 issue，附日志 |
| `POST /runs` 返回 500 | 提交失败 | 平台内部错误 | 提 issue |
| `GET /runs/{id}` 返回 run 永久卡在 `running` | 死锁/watchdog 失效 | 平台 bug | 提 issue，附 run_id |
| `python -m hi_agent run --local` 崩溃且无错误消息 | 启动失败 | 平台 bug | 提 issue，附完整 traceback |
| 并发任务出现状态交叉污染（run A 的结果出现在 run B） | 隔离失效 | 平台 bug | 高优提 issue |
| MemoryLifecycleManager / 知识系统 crash | 子系统故障 | 平台 bug | 提 issue |
| 内置技能 (`analyze_goal`, `search_evidence`, `synthesize`) 无法发现 | 技能发现失败 | 平台 bug | 提 issue |
| `GET /manifest` 返回空能力列表 | 装配失败 | 平台 bug | 提 issue |

---

### B. 使用方配置问题（Integrator owns）

| 现象 | 错误消息 | 归因 | 修复方法 |
|------|---------|------|---------|
| `RuntimeError: Production mode requires real agent-kernel` | prod guard 触发 | 未设置 `--local` 或 `HI_AGENT_ENV=dev` | 加 `--local` 或设置环境变量 |
| `RuntimeError: No API key found` | prod guard 触发 | prod 模式下缺少 API Key | 设置 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY` |
| LLM API 返回 401/403 | 认证失败 | API Key 无效或过期 | 更新 API Key |
| LLM API 返回 429 | 限流 | 请求频率超限 | 降低并发，检查 quota |
| 技能文件无法加载：`missing required field 'name'` | SKILL.md 格式错误 | frontmatter 不规范 | 检查 SKILL.md 格式 |
| 自定义技能未出现在 `/skills/list` | 技能未被发现 | 目录配置错误 | 检查 `skill_storage_dir` |
| MCP 服务器连接超时 | MCP 不可达 | MCP server 未启动或地址错误 | 检查 MCP server 状态 |
| 任务 goal 无法解析 | `invalid_context` failure code | goal 格式不符合要求 | 检查 goal 文本，避免特殊字符 |
| 插件加载失败：`entry_point not found` | 插件 manifest 错误 | `plugin.json` 中 entry_point 路径错误 | 修正 entry_point |
| `POST /runs` 返回 400 | 请求格式错误 | JSON body 缺少 `goal` 字段 | 检查请求 payload |

---

### C. 共同责任 / 需进一步诊断

| 现象 | 可能原因 | 诊断步骤 |
|------|---------|---------|
| 任务 state=`failed`，无明确错误 | 多种原因 | 1. 检查 `GET /runs/{id}` 的 `error` 字段<br>2. 查看 failure_code<br>3. 对照 `FAILURE_RECOVERY_MAP` |
| 结果质量低（`_degraded: true`） | 无 LLM，heuristic 降级 | 设置 API Key 切换完整模式 |
| 任务执行很慢 | LLM 延迟 / 复杂 goal | 检查 LLM provider 状态；拆解 goal |
| 内存/知识查询无结果 | 数据未入库 | 确认任务已完成 + 触发 `/memory/dream` |

---

## 标准 Failure Codes

定义于 `hi_agent.failures.taxonomy.FailureCode`（源自 agent-kernel `TraceFailureCode`）:

| Code | 含义 | 典型原因 |
|------|------|---------|
| `missing_evidence` | 任务执行缺少必要输入 | goal 信息不足 |
| `invalid_context` | 上下文无效 | goal 格式错误 |
| `harness_denied` | 操作被安全机制拒绝 | 高风险操作未经批准 |
| `model_output_invalid` | 模型输出不符合预期格式 | LLM 响应解析失败 |
| `model_refusal` | 模型拒绝执行 | 内容策略限制 |
| `callback_timeout` | 回调超时 | 外部服务响应慢 |
| `no_progress` | 任务无进展 | 探索空间耗尽 |
| `contradictory_evidence` | 证据相互矛盾 | 数据质量问题 |
| `unsafe_action_blocked` | 不安全操作被阻断 | 平台安全机制正常工作 |
| `exploration_budget_exhausted` | 探索预算耗尽 | goal 复杂度超出预算配置 |
| `execution_budget_exhausted` | 执行预算耗尽 | token/时间超限 |

---

## 如何提交平台 Issue

提交 issue 时请附上：

```bash
# 1. 平台版本
curl http://localhost:8080/manifest | jq '{platform, version}'

# 2. Readiness 状态
python -m hi_agent readiness --json 2>&1

# 3. 复现命令（最小化）
python -m hi_agent run --goal "..." --local 2>&1

# 4. 完整 traceback（如有）
```

Issue tracker: `https://github.com/your-org/hi-agent/issues`

---

## 原则

> **平台职责**：确保最小路径 `python -m hi_agent run --goal "..." --local` 不崩溃，降级时有明确的 `_degraded` 标记。
>
> **使用方职责**：配置正确的 API Key、正确格式的 SKILL.md、可达的 MCP server。
>
> **共同职责**：结果质量由 goal 质量、LLM 能力、技能成熟度共同决定。
