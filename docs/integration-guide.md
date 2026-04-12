# hi-agent Integration Guide

**Version**: 1.0 | **Date**: 2026-04-12

从零到跑通的完整接入指南。

---

## Step 1: 验证平台可用性

### 1.1 本地模式（无需 API Key）

```bash
# 检查平台状态
python -m hi_agent readiness --local --json

# 预期输出
{
  "ready": true,
  "execution_mode": "local",
  "health": "ok",
  "capabilities": ["analyze_goal", "search_evidence", "build_draft", "synthesize", "evaluate_acceptance"]
}
```

### 1.2 完整模式（需要 LLM API Key）

```bash
export ANTHROPIC_API_KEY=sk-ant-xxx   # 或 OPENAI_API_KEY

python -m hi_agent readiness --json
# "execution_mode": "full" — 真实 LLM 调用
```

---

## Step 2: 运行第一个任务

### 2.1 CLI 方式

```bash
# 本地模式（最快上手）
python -m hi_agent run --goal "Analyze quarterly revenue trends" --local

# 完整模式（有 API Key 时）
python -m hi_agent run --goal "Analyze quarterly revenue trends"
```

### 2.2 HTTP API 方式

```bash
# 启动服务
python -m hi_agent serve --port 8080

# 提交任务
curl -s -X POST http://localhost:8080/runs \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarize the TRACE framework in one paragraph"}' \
  | jq .

# 轮询结果
RUN_ID=$(curl -s -X POST http://localhost:8080/runs \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarize TRACE"}' | jq -r .run_id)

curl -s http://localhost:8080/runs/$RUN_ID | jq '{state, result}'
```

### 2.3 Python SDK 方式

```python
from hi_agent.config.builder import SystemBuilder
from hi_agent.config.trace_config import TraceConfig
from hi_agent.contracts.task_contract import TaskContract

config = TraceConfig()
builder = SystemBuilder(config)

contract = TaskContract(
    task_id="my-task-001",
    goal="Analyze quarterly revenue trends",
)
executor = builder.build_executor(contract)
result = executor.execute()
print(result)
```

---

## Step 3: 添加自定义 Skill

### 3.1 创建 SKILL.md

在项目目录创建技能文件：

```bash
mkdir -p my_project/skills
cat > my_project/skills/revenue_analysis.md << 'EOF'
---
name: revenue_analysis
version: 1.0.0
description: Analyze revenue data and identify trends
tier: medium
eligibility:
  - condition: goal contains "revenue"
  - condition: goal contains "financial"
---

## Instructions

1. Extract time-series data from the input
2. Identify growth/decline patterns
3. Compare against benchmarks
4. Generate actionable insights

## Output Format

Return a structured analysis with:
- Summary (2-3 sentences)
- Key metrics table
- Trend direction (up/flat/down)
- Recommendations (3 bullet points)
EOF
```

### 3.2 配置技能目录

```python
config = TraceConfig(skill_storage_dir="my_project/skills")
```

或通过环境变量：

```bash
export HI_AGENT_SKILL_DIR=my_project/skills
python -m hi_agent run --goal "Analyze Q4 revenue"
```

### 3.3 验证技能已加载

```bash
curl http://localhost:8080/skills/list | jq '.[].name'
# "analyze_goal"
# "search_evidence"
# "synthesize"
# "revenue_analysis"   ← 你的技能
```

---

## Step 4: 集成 MCP 工具

### 4.1 注册 MCP 服务器

```python
from hi_agent.mcp import MCPRegistry, MCPBinding
from hi_agent.capability.registry import CapabilityRegistry

# 注册 MCP 服务器
mcp_registry = MCPRegistry()
mcp_registry.register_server(
    name="my-tools",
    endpoint="http://localhost:9000",
    transport="http",
)

# 将 MCP 工具绑定到 capability 层
cap_registry = CapabilityRegistry()
binding = MCPBinding(mcp_registry, cap_registry)
binding.bind_server("my-tools")  # 绑定该服务器的所有工具
```

### 4.2 检查 MCP 状态

```bash
curl http://localhost:8080/mcp/status
curl http://localhost:8080/mcp/tools
```

---

## Step 5: 使用 Capability Bundle

适合研究类智能体的场景化能力包：

```python
from hi_agent.capability.bundles.research import ResearchBundle
from hi_agent.capability.registry import CapabilityRegistry

registry = CapabilityRegistry()
registry.register_bundle(ResearchBundle())

# ResearchBundle 包含:
# web_search, web_extract, paper_parse,
# citation_capture, summarize_sources, literature_review
```

---

## Step 6: 故障排查

### 常见问题

**Q: `RuntimeError: Production mode requires real agent-kernel HTTP endpoint`**

```bash
# 原因: 未设置 --local 或 HI_AGENT_ENV
# 修复:
python -m hi_agent run --goal "..." --local
# 或:
export HI_AGENT_ENV=dev
```

**Q: 结果中包含 `"_degraded": true`**

```
这是预期行为。无 API Key 时，平台使用 heuristic 降级模式运行。
结果可用，但非 LLM 驱动。设置 ANTHROPIC_API_KEY 可切换至完整模式。
```

**Q: `skill not found: my_skill`**

```bash
# 检查技能是否被发现
curl http://localhost:8080/skills/list

# 检查 SKILL.md 格式（frontmatter 必须有 name 字段）
python -c "
from hi_agent.skill.loader import SkillLoader
loader = SkillLoader(['my_project/skills'])
print([s.name for s in loader.discover()])
"
```

**Q: 任务卡在 `running` 状态不动**

```bash
# 查看运行详情
curl http://localhost:8080/runs/{run_id}

# 查看平台日志 (启动时加 --log-level debug)
python -m hi_agent serve --port 8080 --log-level debug
```

**Q: 并发提交多个任务时出现状态污染**

```
hi-agent 使用 RunContext 进行严格的 per-run 状态隔离。
如果出现污染，请检查是否在多个任务间共享了 SystemBuilder 实例。
每次运行应使用独立的 executor = builder.build_executor(contract)。
```

---

## 最小集成检查清单

在将 hi-agent 接入你的系统前，验证以下所有项：

```bash
# 1. Readiness check
python -m hi_agent readiness --local --json | jq .ready
# → true

# 2. 单任务运行
python -m hi_agent run --goal "test task" --local
# → Run completed: completed (或 failed，但不崩溃)

# 3. HTTP API (如果使用)
curl http://localhost:8080/ready | jq .ready
# → true

# 4. 技能发现
curl http://localhost:8080/skills/list | jq length
# → >= 3 (至少 3 个内置技能)

# 5. 并发隔离
# 同时提交 3 个任务，确认各自独立完成
```

所有项通过 → 接入完成。
