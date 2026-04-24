同事顺手附的 Self-Audit Report 诚实承认仍有尾巴                                                                                                                                                        
                                                                                                                                                                                                         
  - 🟠 D1 store 重复：RawMemoryStore 4 处构造，3 处 LongTermMemoryGraph                                                                                                                                  
  - 🟠 E3 async 反模式 16 处
  - 🟠 E4 sync LLM gateway 里 blocking time.sleep                                                                                                                                                        
  - 🟠 H2 payload 来源的 base_dir 仍在（路径穿越风险）                                                                                                                                                   
  - 🟠 H3 prod_enabled_default=True 3 处                                                                                                                                                                 
  - 🟠 H4 MCP transport 里 1 处 shell=True                                                                                                                                                               
                                                                                                                                                                                                         
  P0/P1 修了，H 级安全面和 D 级架构债还开着——ICBC 演示前可以上这版拿 prod 模式跑通，但客户要是追问安全边界，H2/H4 是真 landmine。
  
  复现成功：                                                              
                                        
  test1 (fresh client per asyncio.run):    status=200  elapsed=4.12s  ✓
  test2 (shared client across asyncio.run):
    call0: status=200 elapsed=9.36s  ✓                                                                                                                                                                   
    call1: RuntimeError: Event loop is closed  ✗                                                                                                                                                         
    call2: status=429 elapsed=0.12s  (半死状态)                                                                                                                                                          
                                                                                                                                                                                                         
  根因板上钉钉：async_http_gateway.py:100 的 asyncio.run(self._inner.complete(request)) 每次开新 loop，但 self._inner._client (httpx.AsyncClient) 是 init 时建的共享 client，底层 httpcore pool        
  绑定到第一个 loop。第二次起所有调用要么 Event loop is closed 要么 TCP 层 ConnectTimeout（因为 anyio backend 找不到活 loop）。                                                                          
                                                                                                                                                                                                         
  这正好是 self-audit report 里 E3 async 反模式 16 处之一，属于 Flagged 但本次没修。P0-2/P1-5/P1-7 三个主修都到位，但 LLM 出口这条路在 MaaS 场景下一次都没跑通过（test2 call0 200 是因为 asyncio.run
  刚开没来得及关 loop，后续全挂）。                                                                                                                                                                      
                                                                                                                                                                                                         
  先等当前 run 跑完（已经在走 heuristic fallback 假跑，P1-7 防止了永久钉死，理论上能到 completed），看 state lifecycle 完不完整。

最终结论：没通                                                                                                                                                                                         
                                                                                                                                                                                                         
  替换流程：成功                         
                                                                                                                                                                                                         
  1. pm2 stop hi-agent ✓                                                                                                                                                                                 
  2. 备份：hi-agent-main.bak-20260421-pre-selfaudit ✓                                                                                                                                                    
  3. 新版上位（sha256 变化确认）✓                                                                                                                                                                        
  4. pm2 start → 8080 LISTEN、/health 200、kernel_adapter lazy ✓                                                                                                                                         
                                                                                                                                                                                                         
  运行层：不通                                                                                                                                                                                           
                                                                                                                                                                                                         
  ┌─────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐                                                                                          
  │                   检验点                    │                            结果                             │                                                                                          
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤                                                                                          
  │ MaaS 网络                                   │ ✅ 正常 — 机器上 curl 直连 200 OK, TCP 35ms                 │                                                                                          
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤                                                                                          
  │ P0-2（dev-smoke 3s clamp）                  │ ✅ 修复生效 — 不再无差别 clamp                              │                                                                                          
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤                                                                                          
  │ P0-3（base_url /v2 被覆盖）                 │ ✅ 修复生效 — 用绝对 URL                                    │                                                                                          
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤                                                                                          
  │ P1-7（worker 永久钉死）                     │ ✅ 修复生效 — 抛 TimeoutError，41 次 fallback 都顺利 return │
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤                                                                                          
  │ P1-5（stage update）                        │ ❌ 无验证 — 14 分钟 current_stage 持续 None                 │
  ├─────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤                                                                                          
  │ E3（shared AsyncClient across asyncio.run） │ ❌ 未修，致命 — LLM 出口彻底挂                              │
  └─────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┘                                                                                          
                  
  根因复现（可靠）                                                                                                                                                                                       
                  
  最小脚本直接复现：                                                                                                                                                                                     
  client = httpx.AsyncClient(...)       # 进程启动时建一次
  asyncio.run(client.post(...))          # call0: 200 OK ✓
  asyncio.run(client.post(...))          # call1: RuntimeError: Event loop is closed ✗                                                                                                                   
                                                                                                                                                                                                         
  async_http_gateway.py:100 的 asyncio.run(self._inner.complete(request)) 每次开新 event loop，但 self._inner._client 是共享的 httpx.AsyncClient，底层 httpcore pool 绑定到第一个 loop。第二次起全部     
  timeout/closed。                                                                                                                                                                                       
                                                                                                                                                                                                         
  → 在 hi-agent 里表现为：每个 LLM call TCP ConnectTimeout → Capability fallback to heuristic。Self-audit report 自己写着 "E3 async anti-patterns 16 sites" 仍 flagged                                   
  未修，这就是其中一处，而且是最致命的一处。
                                                                                                                                                                                                         
  当前线上状态    

  - hi-agent online @ 8080（新版）                                                                                                                                                                       
  - 原 bak 在 /root/hi-platform/hi-agent-main.bak-20260421-pre-selfaudit 随时可回滚
  - 41 条 LLM fallback 记录，run state 卡 running/current_stage=None 14+ 分钟未终态，连 cancel 都返回 not_found（run 对 worker 不可见？另一个 bug）                                                      
                                                                                                                                                                                                         
  三条下一步路径                                                                                                                                                                                         
                                                                                                                                                                                                         
  A. 最小 patch（30 分钟，我能写） — 改 async_http_gateway.py：每次 complete() 用 async with httpx.AsyncClient(...) as c: 现开现关，放弃连接池。glm-5.1 单次 10s，连接建立 35ms，代价可接受。能解 E3     
  这条致命 path。
                                                                                                                                                                                                         
  B. 回滚今早 07:58 版 — 但今早版同样有这个 bug（你上午 issue doc 里就是这个现象），回滚没用。                                                                                                           
   
  C. 找同事（zhihao？）修 — 这是架构级修复，理想做法是 AsyncHTTPGateway 运行在一个常驻 event loop 线程里，sync 侧用 asyncio.run_coroutine_threadsafe 桥接；self-audit 报告里那 16 处都要配套一起处理。   
                  
  演示时间线上我倾向 A 先临时止血，之后督促同事做 C。要不要我现在就上 A？