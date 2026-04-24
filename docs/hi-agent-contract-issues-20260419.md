# hi-agent × agent-kernel 契约不一致问题反馈

**日期**：2026-04-19
**环境**：`/root/hi-platform/`（灵虾部署机 `123.60.154.110`）
**现象**：4-19 升级 hi-agent 新包后，任意 POST /runs 请求均失败，task-trace agent 无法启动 run

---

## 环境版本

| 组件 | 当前部署时间戳 | 路径 |
|---|---|---|
| `hi-agent` | **2026-04-19 05:45** | `/root/hi-platform/hi-agent-main/` |
| `agent-kernel` | **2026-04-16 22:53** | `/root/hi-platform/agent-kernel-main/` |
| Python | 3.12.3（venv） | `/root/hi-platform/venv/` |
| ecosystem env | `HI_AGENT_KERNEL_BASE_URL=local` | `/root/hi-platform/ecosystem.config.cjs` |

两个仓库版本不同步，但问题不完全是版本错位 —— 看下面诊断。

---

## 运行时错误（pm2 `hi-agent-error.log` + `agent-kernel-error.log`）

### ❶ hi-agent → agent-kernel HTTP 路径写错了 3 处

```
ResilientKernelAdapter: 'start_run' buffered after 4 retries
  (Backend operation failed: /runs/start: HTTP Error 405: Method Not Allowed)

ResilientKernelAdapter: 'start_run' buffered after 4 retries
  (Backend operation failed: /runs: HTTP Error 400: Bad Request)

ResilientKernelAdapter: 'open_stage' buffered after 4 retries
  (Backend operation failed: /stages/open: HTTP Error 404: Not Found)
```

来源：`hi-agent-main/hi_agent/runtime_adapter/kernel_facade_client.py`
```python
line 73:  self._http_post("/stages/open", {"stage_id": stage_id})
line 134: # kernel POST /runs expects StartRunRequest shape, not {task_id}
line 411: resp = self._http_post("/runs/spawn_child", body)
```

**对照 agent-kernel `service/http_server.py` 实际暴露的端点**（04-16 版已正确）：

| hi-agent 调用的 | agent-kernel 实际路径 | 备注 |
|---|---|---|
| `POST /runs/start` | `POST /runs`（line 80 `post_runs`） | 路径写错，多了 `/start` |
| `POST /runs`（body = `{task_id}`） | `POST /runs`（body = `StartRunRequest`） | 路径对了，body schema 不对 |
| `POST /stages/open` | `POST /runs/{run_id}/stages/open`（line 261 `post_run_stage_open`） | 路径少了 `/runs/{run_id}` 前缀 |
| `POST /runs/spawn_child` | `POST /runs/{run_id}/children`（line 221 `post_run_children`） | 命名 + 路径都不一致 |

**建议修复位置**：`hi-agent` 仓库的 `hi_agent/runtime_adapter/kernel_facade_client.py`

### ❷ agent-kernel LocalWorkflowGateway 固定 run_id bug

```
File "/root/hi-platform/agent-kernel-main/agent_kernel/substrate/local/adaptor.py", line 227,
  in start_workflow
    raise ValueError(f"LocalWorkflowGateway: duplicate run_id {run_id!r} is not allowed")
ValueError: LocalWorkflowGateway: duplicate run_id 'default' is not allowed
```

第一次调用成功，第二次同一个 run_id `'default'` 再进来就拒绝。`run_id = 'default'` 是硬编码的默认值，没有从 request 里取也没有生成 UUID。

> ⚠️ 这个 bug 是 **2026-04-11 那次升级同一模式的重复**（当时写死的是 `run_id='trace'`，这次是 `'default'`，根因没修）。

**建议修复位置**：`agent-kernel` 仓库的 `agent_kernel/substrate/local/adaptor.py:227` 附近的 run_id 生成逻辑

### ❸ Production mode readiness 问题（可选修）

```
readiness: 1 issue(s): kernel: Production mode requires a real agent-kernel HTTP endpoint.
  Set kernel_base_url to http(s)://... and do not use 'local'.
```

目前 ecosystem 里 `HI_AGENT_KERNEL_BASE_URL=local`，hi-agent 新版会拒绝在 prod 模式下用 local/mock（逻辑合理）。但 hi-agent 现在没加 `--prod` flag，实际走 dev mode 用 LocalFSM —— 恰好撞到 ❷。

这不是 bug，只是观察点。等 ❶❷ 修好后可以换成 `http://127.0.0.1:8400` + `--prod`。

---

## 本质诊断

- **❶**：hi-agent 客户端是按"某个更早版本的 kernel 协议"或"某份草案"写的，跟 04-16 这版 kernel 的实际 endpoint map 不一致。即便 kernel 也升到最新，端点路径也大概率还是 `/runs/{id}/stages/open` 这类 RESTful 约定，需要 hi-agent 端迁移。
- **❷**：LocalWorkflowGateway 做兜底时的 run_id 策略有问题，连续两次调用必挂。

---

## 请求

1. **hi-agent**：`kernel_facade_client.py` 里 4 处 HTTP 路径 + POST /runs 的 body schema 对齐 agent-kernel 实际契约（`service/http_server.py` 是权威）。
2. **agent-kernel**：`substrate/local/adaptor.py` 的 run_id 生成从硬编码 `'default'` 改成 UUID 或从 request 里取。
3. **发新包时同步交付两个 zip**（如果以后 hi-agent 需要调用新 kernel 端点，两边必须一起升）。

---

## 我这边配合

### 验证脚本（修好后跑）
```bash
RUN_ID=$(curl -sf -X POST http://127.0.0.1:8080/runs \
  -H 'Content-Type: application/json' \
  -d '{"goal":"test","task_family":"quick_task","risk_level":"low"}' | jq -r .run_id)
echo "created run_id=$RUN_ID"

# 连发 3 次验证 run_id 不冲突
for i in 1 2 3; do
  curl -sf -X POST http://127.0.0.1:8080/runs \
    -H 'Content-Type: application/json' \
    -d '{"goal":"test '$i'","task_family":"quick_task","risk_level":"low"}' \
    | jq -c '{run_id, state}'
done

# 轮询首个 run 到终态
for i in $(seq 1 30); do
  STATE=$(curl -sf http://127.0.0.1:8080/runs/$RUN_ID | jq -r .state)
  echo "$i: $STATE"
  [ "$STATE" = "done" -o "$STATE" = "failed" ] && break
  sleep 2
done

tail -30 /root/.pm2/logs/hi-agent-error.log /root/.pm2/logs/agent-kernel-error.log
```

三条标准：
- 连发 3 次 POST /runs 得到 3 个不同 run_id，均返回 200
- run state 能走到 `done` 或 `failed`（不卡 `running`）
- error log 里不应出现 405/400/404/duplicate run_id 任何一条

### 坏包保留
4-11 那次失败版保留在 `/root/hi-platform/hi-agent-main.bad-new-20260411/`（可以 diff 参考修复过哪些）。

### 回滚策略
你修好后我们升级前用 `/root/hi-platform/hi-agent-main.bak-20260419/` 保留当前 4-19 版本，新版不行 30 秒回滚。

---

## 交付时建议的 smoke test（未来避免类似问题）

打包前在 Python 3.12.3 + 空 .hi_agent/ 环境跑一遍：

```bash
cd /tmp && rm -rf /tmp/smoke && mkdir /tmp/smoke && cd /tmp/smoke
unzip hi-agent-main.zip && unzip agent-kernel-main.zip
python3 -c "import hi_agent; import agent_kernel"                  # import 无 SyntaxError/BOM
python3 -m hi_agent serve --host 127.0.0.1 --port 18080 &
sleep 5
curl -sf http://127.0.0.1:18080/health/liveness || echo "FAIL"
# 上面那个验证脚本再跑一遍
```

之前两次交付都没过这个 baseline：4-11 包含 Python 2 `except A, B:` 语法（17 处）+ UTF-8 BOM（12 个文件），import 都失败；4-19 这次 import 通过了，但 run-then-poll 跑不通。**build → package → smoke test → ship** 这个流程走起来能省双方很多时间。

---

联系人：李泓琨（灵虾侧）
测试环境：`123.60.154.110` root（你有 key），pm2 两个 app 都在
