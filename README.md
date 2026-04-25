# hi-agent

`hi-agent` 是基于 **TRACE**（Task → Route → Act → Capture → Evolve）框架构建的企业级智能体系统。  
负责任务理解、路由决策、能力执行、记忆沉淀与持续进化；底层持久化运行时由内联的 `agent_kernel/` 承载。

*最后更新：2026-04-25（Wave 9）*

---

## 系统定位

| 仓库 / 包 | 职责 | 位置 |
|-----------|------|------|
| `hi_agent/` | 智能体大脑：策略、路由、执行、记忆/知识/技能、持续进化 | 本仓库 |
| `agent_kernel/` | Durable runtime：run 生命周期、事件事实、幂等与恢复治理 | 本仓库（已内联，2026-04-19） |
| `agent-core` | 通用能力模块：工具、检索、MCP 等 | 集成到 hi_agent/ |

---

## 架构概览

| 层 | 组件 | 文件 | 职责 |
|----|------|------|------|
| API 入口 | HTTP Server / RunManager | `hi_agent/server/app.py` | 接收请求、管理 run 生命周期 |
| 执行层 | RunExecutor / StageOrchestrator | `hi_agent/runner.py`, `execution/` | 阶段遍历（线性/图/恢复）、治理门禁 |
| LLM 层 | TierAwareLLMGateway / FailoverChain | `hi_agent/llm/` | 分层路由（strong/medium/light）、凭证轮转、流式输出 |
| 认知系统 | Memory / Knowledge / Skill | `hi_agent/memory/`, `knowledge/`, `skill/` | 三层记忆、四层检索、技能进化 |
| 进化引擎 | EvolveEngine | `hi_agent/evolve/` | Postmortem → 技能提取 → A/B 检验 |
| Durable Runtime | agent_kernel | `agent_kernel/` | EventLog、幂等、恢复治理、HTTP 服务 |

完整架构图：[ARCHITECTURE.md](ARCHITECTURE.md)

---

## 核心概念

| 概念 | 定义 |
|------|------|
| **Task** | 形式化任务契约（目标、约束、预算）`contracts/task.py` |
| **Run** | 可持久化的长时执行实体 `runner.py` |
| **Stage** | 任务推进的形式阶段（TRACE S1→S5） `runner_stage.py` |
| **Branch** | 探索空间中的逻辑轨迹 `trajectory/` |
| **Task View** | 每次模型调用前重建的最小充分上下文 `task_view/` |
| **Action** | 通过 Harness 执行的外部操作 `harness/` |
| **Memory** | 智能体经历的三层记忆（短/中/长期） `memory/` |
| **Knowledge** | 稳定知识（wiki + 图谱 + 四层检索） `knowledge/` |
| **Skill** | 可复用流程单元（5 阶段生命周期 + 版本进化） `skill/` |
| **Feedback** | 结果、评测与实验产生的优化信号 `evolve/` |
| **TeamRunSpec** | 团队协作 run 契约，含成员角色与任务分配 `contracts/team_runtime.py` |
| **CapabilityDescriptor** | 规范化能力描述符（Wave 9 DF-50 统一入口） `capability/registry.py` |
| **ReasoningTrace** | 结构化推理过程记录，支持回溯与审计 `contracts/reasoning_trace.py` |

---

## 目录结构

```text
hi_agent/          # 智能体大脑（策略、路由、执行、认知、进化）
agent_kernel/      # Durable runtime（EventLog、幂等、恢复、HTTP）
config/            # llm_config.json（本地，gitignored）+ llm_config.example.json
tests/             # 4100+ 测试（unit / integration / e2e / security / perf）
docs/              # 架构参考、规格、runbook、sprint 文档、delivery 记录
scripts/           # verify_llm.py、e2e_verify.sh 等验证脚本
```

详细模块说明：[ARCHITECTURE.md](ARCHITECTURE.md)

---

## 快速开始 — 三分钟上手（Posture-first）

```bash
# 1. 初始化研究环境
hi-agent init --posture research --config-dir ./config

# 2. 检查配置
hi-agent doctor

# 3. 启动服务
export HI_AGENT_POSTURE=research
export HI_AGENT_DATA_DIR=./data
python -m hi_agent serve --port 8080

# 4. 提交第一个 run
curl -X POST http://localhost:8080/runs \
  -H "Content-Type: application/json" \
  -d '{"goal":"hello","project_id":"proj-1"}'
```

30 分钟完整指南：[docs/quickstart-research-profile.md](docs/quickstart-research-profile.md)

---

## 快速开始

```bash
# 安装依赖（agent-kernel 已内联，无需 submodule）
python -m pip install -e ".[dev]"

# 本地执行（不依赖 server）
python -m hi_agent run --goal "Analyze quarterly revenue data" --local

# 指定 HI_AGENT_HOME（profile / episode / checkpoint 目录）
python -m hi_agent run --goal "Analyze data" --local --home /data/hi_agent

# 启动 API server
python -m hi_agent serve --host 127.0.0.1 --port 8080

# 从 checkpoint 恢复
python -m hi_agent resume --checkpoint checkpoint_run-001.json
```

---

## CLI 用法

| 子命令 | 说明 |
|--------|------|
| `run` | 本地单次运行（`--local`）或远程提交 |
| `serve` | 启动 HTTP API 服务（`--prod` 启用生产模式） |
| `resume` | 从检查点恢复（`--checkpoint` 或 `--run-id`） |
| `init --posture {dev,research,prod}` | 初始化配置目录（Wave 9） |
| `doctor` | 检查配置和运行时状态，输出结构化诊断报告 |
| `readiness` | 运行就绪性检查（模型/技能/能力/MCP） |
| `tools` | 查看可用工具（`list` / `call`） |
| `status` | 查询 run 状态 |
| `health` | 服务器健康检查 |

### 关键环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HI_AGENT_POSTURE` | 运行姿态（`dev` / `research` / `prod`） | `dev` |
| `HI_AGENT_DATA_DIR` | 持久化数据目录（research/prod 必填） | 无 |
| `HI_AGENT_CONFIG_DIR` | 配置目录（tools.json, mcp_servers.json） | 无 |
| `HI_AGENT_LLM_MODE` | LLM 模式（`real` / `heuristic`） | `heuristic` |
| `HI_AGENT_ENV` | 运行环境（`dev` / `prod`） | `dev` |
| `HI_AGENT_LLM_DEFAULT_PROVIDER` | 默认 LLM 提供商 | `anthropic` |
| `HI_AGENT_KERNEL_BASE_URL` | 独立 agent-kernel HTTP 端点（prod 必填） | 无 |
| `HI_AGENT_API_TIMEOUT_SECONDS` | API 请求超时（秒） | `15` |

---

## API 核心端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/runs` | POST | 提交任务（支持 TaskContract 全部字段） |
| `/runs/{id}` | GET | 查询 run 状态（含 `current_stage`、`stage_updated_at`） |
| `/runs/{id}/cancel` | POST | 取消 run（已知 id→200，未知 id→404） |
| `/runs/{id}/events` | GET | SSE 实时事件流（stage_start/complete/RunStarted） |
| `/ready` | GET | 平台就绪检查（200=ready，503=not ready） |

Wave 9：所有 `/runs` 错误响应均包含 `{error_category, message, retryable, next_action}`。

完整端点文档：[docs/api-reference.md](docs/api-reference.md)

---

## 下游系统接入指南

### 三种部署姿态

| 姿态 | `HI_AGENT_ENV` | `HI_AGENT_LLM_MODE` | 用途 |
|------|---------------|---------------------|------|
| `dev-smoke` | `dev` | `heuristic` | 无需 API Key，冒烟验证流程 |
| `local-real` | `dev` | `real` | 本地接入真实 LLM，功能验证 |
| `prod-real` | `prod` | `real` | 生产部署，独立 kernel，真实 LLM |

### 接入真实 LLM（local-real 模式）

```bash
export HI_AGENT_LLM_DEFAULT_PROVIDER=openai
export HI_AGENT_OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
export OPENAI_API_KEY=<your-api-key>
export HI_AGENT_LLM_MODE=real
```

Anthropic：
```bash
export HI_AGENT_LLM_DEFAULT_PROVIDER=anthropic
export ANTHROPIC_API_KEY=<your-api-key>
export HI_AGENT_LLM_MODE=real
```

### 生产部署（prod-real）

```bash
export HI_AGENT_ENV=prod
export HI_AGENT_KERNEL_BASE_URL=http://127.0.0.1:8400   # 必填：独立 kernel HTTP 端点
export HI_AGENT_LLM_MODE=real
export HI_AGENT_LLM_DEFAULT_PROVIDER=openai
export HI_AGENT_OPENAI_BASE_URL=https://api.modelarts-maas.com/v2
export OPENAI_API_KEY=<your-api-key>
export HI_AGENT_LLM_TIMEOUT_SECONDS=180                  # reasoning 模型建议 ≥120s
```

> **prod 模式硬护栏**：缺 `kernel` 或 `llm_gateway` 时 `POST /runs` 直接返回 503 `platform_not_ready`（附补救 hint）。

### 常见陷阱

- `KERNEL_BASE_URL=...`（缺 `HI_AGENT_` 前缀）— 不会被读取，必须用 `HI_AGENT_KERNEL_BASE_URL`
- `HI_AGENT_KERNEL_URL=...`（历史拼写）— 仅 `/doctor` fallback，其他路径不读
- base_url 少写版本号（漏了 `/v2`）— 发 `POST {base_url}/chat/completions` 会 404

### 五步接入流程

```bash
# 1. 初始化配置
hi-agent init --posture research --config-dir ./config

# 2. 配置 LLM 凭证（见上）
export HI_AGENT_LLM_MODE=real && export OPENAI_API_KEY=...

# 3. 自检
hi-agent doctor
curl -s http://127.0.0.1:8080/diagnostics | jq '{env, runtime_mode, creds: .credentials_present}'

# 4. 提交 run 并观察进度
RUN_ID=$(curl -sf -X POST http://127.0.0.1:8080/runs \
  -H 'Content-Type: application/json' \
  -d '{"goal":"smoke","project_id":"proj-1"}' | jq -r .run_id)
curl -s http://127.0.0.1:8080/runs/$RUN_ID | jq '{state, current_stage}'

# 5. 端到端批量验证
bash scripts/e2e_verify.sh http://127.0.0.1:8080
```

### 可观测性端点

| 端点 | 用途 |
|------|------|
| `GET /ready` | 就绪状态 + runtime_mode |
| `GET /health` | 子系统健康（含 kernel_adapter） |
| `GET /diagnostics` | 部署自检（env / runtime_mode / credentials_present） |
| `GET /doctor` | 结构化诊断报告（prod 下实际探测 kernel） |
| `GET /metrics` | Prometheus 格式指标 |
| `GET /manifest` | 系统能力清单（runtime_mode / evolve_policy / provenance） |

---

## 关键能力

- **模型分层路由**：`TierAwareLLMGateway`（strong/medium/light）+ `FailoverChain` + `PromptCacheInjector`
- **流式与思考**：`stream()` 返回 `Iterator[LLMStreamChunk]`；`LLMRequest(thinking_budget=N)` 开启 Extended Thinking
- **多模态**：`messages[].content` 支持 content block 列表，图文混合输入
- **三层记忆**：L0 Raw → L1 STM → L2 Dream → L3 LongTermGraph + Dream 整合 + 语义图谱
- **四层检索**：Grep → BM25 → Graph → Embedding
- **技能进化**：`ChampionChallenger` A/B + `SkillEvolver` textual gradient 优化
- **进化三态**：`evolve_mode: auto | on | off`（`auto` 下 dev-smoke 开启，real 关闭）
- **ArtifactLedger 隔离**：quarantine + per-kind 计数器（Wave 9 TE-1/TE-4）
- **幂等 RunQueue / TeamRunRegistry**：auth-scoped，持久化（Wave 9 RO-1/3/4）
- **CapabilityDescriptor**：规范化能力描述符，统一注册入口（Wave 9 DF-50）
- **工作区隔离**：`(tenant_id, user_id, session_id)` 三维主键，路径穿越防护

Posture defaults 参考：[docs/posture-reference.md](docs/posture-reference.md)

### RBAC/SOC 操作授权

| 操作 | 所需角色 | SOC 分离 |
|------|---------|----------|
| `skill.promote` | `approver` / `admin` | 是（submitter ≠ approver） |
| `skill.evolve` | `approver` / `admin` | 是 |
| `memory.consolidate` | `approver` / `admin` | 否 |

---

## 开发与验证

```bash
# Lint
python -m ruff check hi_agent agent_kernel tests scripts

# 全量离线测试
python -m pytest tests/ -q --ignore=tests/integration/test_live_llm_api.py
# 4100 passed（Wave 9，2026-04-25）

# Live API 测试（需 config/llm_config.json 配置 volces.api_key）
python -m pytest tests/integration/test_live_llm_api.py -m live_api -v

# LLM 配置验证
python scripts/verify_llm.py                            # 流式测试
python scripts/verify_llm.py --thinking                 # + 思考模式
python scripts/verify_llm.py --multimodal path/to.png   # + 多模态

# 导入冒烟
python -c "import hi_agent; import agent_kernel"
```

---

## 参考文档

- [ARCHITECTURE.md](./ARCHITECTURE.md) — L0 系统边界（含组件角色、集成点、LLM 配置）
- [hi_agent/ARCHITECTURE.md](./hi_agent/ARCHITECTURE.md) — L1 hi-agent 详细架构
- [agent_kernel/ARCHITECTURE.md](./agent_kernel/ARCHITECTURE.md) — L1 agent-kernel 详细架构
- [docs/quickstart-research-profile.md](docs/quickstart-research-profile.md) — 30 分钟研究环境快速开始
- [docs/posture-reference.md](docs/posture-reference.md) — dev/research/prod 姿态参考
- [docs/api-reference.md](docs/api-reference.md) — HTTP API 端点与错误分类完整文档
- [docs/downstream-responses/2026-04-25-wave9-delivery-notice.md](docs/downstream-responses/2026-04-25-wave9-delivery-notice.md) — Wave 9 交付通知
- [docs/runbook/](./docs/runbook/) — deploy、verify、rollback、incident runbook
- [docs/migration/contract-changes-2026-04-17.md](./docs/migration/contract-changes-2026-04-17.md) — 执行来源 + manifest + RBAC 变更通知
