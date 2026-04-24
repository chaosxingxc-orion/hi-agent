> **⚠ SUPERSEDED**: This document contains an incomplete diagnosis from 2026-04-21.
> The correct root cause is documented in `docs/hi-agent-prod-mode-issue-20260422.md`.
> **Do not act on the diagnosis in this document.**

---

# hi-agent 04-21 新版 prod 模式 / 真 LLM 调用不可用

**日期**：2026-04-21
**环境**：灵虾部署机 `123.60.154.110`，`/root/hi-platform/`
**hi-agent 版本**：04-21 07:45 同事 push 的 `hi-agent-main.zip`（已解压 BOM 清理、syntax OK）
**agent-kernel 版本**：`/root/hi-platform/agent-kernel-main/`（04-16 独立部署，端口 8400；新 hi-agent 内嵌有另一份 04-21）

---

## 现象速览

| 组合 | LLM 调用 | run 状态 | 备注 |
|---|---|---|---|
| `HI_AGENT_ENV=` (default dev) + `KERNEL_BASE_URL=local` | **3s clamp 全 timeout → heuristic fallback** | **4 分钟 completed** | 可用但全 heuristic 假跑 |
| default dev + local kernel + 去掉 http_gateway.py 3s clamp | timeout 120s，in-process 直测 12s 可返回 | **stage=None 卡 6+ 分钟** | LLM 能调，但 run worker 不推进 |
| `HI_AGENT_ENV=prod` + `KERNEL_BASE_URL=local` | - | **stage=None 卡 9+ 分钟**，CPU 0.2% idle | run worker 不启动 |
| `HI_AGENT_ENV=prod` + `KERNEL_BASE_URL=http://127.0.0.1:8400` | - | **stage=None 卡 5+ 分钟** | agent-kernel 没收到任何 HTTP 请求 |

**结论**：**只有 dev-smoke + heuristic fallback 能让 run 走到 completed**。任何"真 LLM + run 正常推进"的组合都卡在第一个 stage 之前。

---

## 已确认的事实

### 1. MaaS glm-5.1 → LLM gateway 本身工作正常
in-process 直调 `AsyncHTTPGateway` 成功返回：
```
FAIL→OK in 12.63s: content='Hello to you!', model='glm-5.1'
```
说明 gateway 构造、base_url、api_key、httpx client 都对的上。glm-5.1 单次调用 10-13s。

### 2. agent-kernel endpoints 与 hi-agent `kernel_facade_client.py` 路径已对齐
对照 /openapi.json 和 `hi_agent/runtime_adapter/kernel_facade_client.py`：
- POST `/runs`、GET `/runs/{run_id}`、POST `/runs/{run_id}/stages/{stage_id}/open`、POST `/runs/{run_id}/children`、POST `/runs/{run_id}/cancel`、POST `/runs/{run_id}/resume`、POST `/runs/{run_id}/signal`、POST `/runs/{run_id}/task-views` 全部匹配。

04-19 的 3 个 contract bug（`/runs/start`、`/stages/open`、`/runs/spawn_child`）在新版已修。

### 3. 修了一个新的 URL bug
`hi_agent/llm/http_gateway.py` line 470 和 507 原本硬编码 `"/v1/chat/completions"` 作为 absolute path 传给 `httpx.AsyncClient.post`。因为 httpx 对 absolute path 会**覆盖 base_url 的 path**（urljoin 语义），所以 `base_url=https://api.modelarts-maas.com/v2` 会被覆盖成 `/v1/chat/completions`（404）。

已改成 `f"{self._base_url}/chat/completions"`。这个修复必须保留，否则所有非 `/v1` 的 OpenAI 兼容 provider 都会 404。

### 4. `kernel_adapter.status = "not_built"` 可能是 display bug
`GET /health` 在所有组合下都显示 `kernel_adapter: {status: "not_built"}`，包括 dev-smoke 下 run 能 completed 的情况。所以这个字段不是真实的 kernel 状态。但 prod 模式下 run worker 确实没跑起来（CPU idle + 无 log + kernel 没收到 HTTP），跟这个字段是否关联不确定。

### 5. prod 模式下 agent-kernel 端没收到任何 HTTP
配 `KERNEL_BASE_URL=http://127.0.0.1:8400` 并发起 POST /runs 之后，`/root/.pm2/logs/agent-kernel-error.log` 和 `agent-kernel-out.log` 都没新日志。说明 hi-agent 根本没往 kernel 发请求就卡住了。

---

## 复现步骤

```bash
# 当前 ecosystem.config.cjs 已是 dev-smoke + local 的"最后 known good"
# 要复现 prod 模式卡住：

# 1. 改 ecosystem，加 HI_AGENT_ENV=prod
#    /root/hi-platform/ecosystem.config.cjs 的 hi-agent 段：
#        HI_AGENT_ENV: 'prod',

# 2. pm2 delete+start hi-agent（必须 delete，restart --update-env 不重读 ecosystem env）
pm2 delete hi-agent && pm2 start /root/hi-platform/ecosystem.config.cjs --only hi-agent

# 3. 发 run
TOKEN=dev-local-key-20260419
RID=$(curl -sf -X POST http://127.0.0.1:8080/runs \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"goal":"repro","task_family":"quick_task","risk_level":"low"}' | jq -r .run_id)
echo $RID

# 4. 观察 state + stage 永远是 running / None
while true; do
  curl -sf -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/runs/$RID | jq '{state, current_stage}'
  sleep 15
done

# 5. 看进程 CPU（0.2% idle，没跑）
pm2 show hi-agent | grep cpu
```

---

## 怀疑方向（提供给同事排查）

1. **AgentServer 启动时 kernel adapter 构建失败但不报错**。某处 try/except 吃掉了异常，导致 run worker 构造时拿到空的 kernel，run 提交后没 worker 启动。建议在 `/root/hi-platform/hi-agent-main/hi_agent/server/app.py` 的 kernel 初始化加更严格的 fail-fast。
2. **prod 模式的 readiness precondition 检查不通过**。`runtime_mode_resolver.resolve_runtime_mode` 在 `env=="prod"` 直接返回 `prod-real`，但 readiness snapshot 里的 `llm_mode / kernel_mode` 在 TraceConfig 默认是空串（不是 `"real"/"http"`），可能下游代码按严格模式处理时 fail。
3. **`http_gateway.py` 的 dev-smoke clamp 副作用**：`self._timeout = min(self._timeout, 3)` + `self._max_retries = 0` 本意是 smoke test 快速失败走 heuristic，但 glm-5.1 reasoning 模型单次 >10s，被 clamp 后所有 LLM 调用必 timeout。建议改成：clamp 只在没配 `OPENAI_API_KEY` 时才生效（credential-absent 场景），或至少放宽到 30s。
4. **新版去掉 heuristic fallback 的 dev→prod 过渡不完整**。prod 模式下 heuristic fallback 显然被禁用（因为 "NOT formal production E2E"），但真 LLM 路径的 kernel worker 启动又没走通，导致两头不靠。

---

## 当前线上状态

- **ecosystem**：已回滚到 `KERNEL_BASE_URL=local` + 无 `HI_AGENT_ENV`
- **hi-agent 代码**：保留 `http_gateway.py` 的 /v1 → f-string 修复（必须保留）+ dev-smoke clamp 恢复原状
- **linggan-claw**：已带 Bearer 调 hi-agent，task-trace 完成后总结已走 MaaS glm-5.1
- **task-trace 用户侧体验**：发消息 → hi-agent dev-smoke 4 分钟 heuristic 假跑 → claw maxPolls=90（3 分钟）超时 → 前端看到 "⏱️ 任务执行超时"

task-trace 目前**对外是坏的**，等同事修 prod 模式后恢复。灵虾里 task-trace "装了但基本没人用"，短期坏掉无业务影响。
