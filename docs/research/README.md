# TRACE 研究计划

> 状态：活跃
> 创建日期：2026-04-05
> 关联架构：ARCHITECTURE.md V2.8
> 关联实施计划：docs/superpowers/plans/2026-04-05-trace-implementation-master-plan.md

## 目的

架构设计阶段已完成（V2.0→V2.8，8 轮迭代）。本研究计划不是继续写规范，而是**用实验回答实施前必须解决的技术问题**。每个课题的交付标准是"回答了什么具体问题 + 产出了什么可运行的代码/数据"，不是更多文档。

## 课题清单

| # | 课题 | 优先级 | 预计时间 | 前置依赖 | 状态 |
|---|------|--------|---------|---------|------|
| 1 | [LLM-based Route Engine 可行性与成本模型](./RT-01-llm-route-engine.md) | P0 | 3-5 天 | 无 | TODO |
| 2 | [分层记忆 L1 压缩质量与延迟](./RT-02-l1-compression.md) | P0 | 3-4 天 | 无 | TODO |
| 3 | [KnowledgeWiki ingest 实际效果](./RT-03-knowledge-ingest.md) | P1 | 5-7 天 | RT-01 | TODO |
| 4 | [agent-kernel 与 hi-agent 真实对接](./RT-04-kernel-integration.md) | P0 | 3-5 天 | 无 | TODO |
| 5 | [agent-core 能力对齐](./RT-05-core-alignment.md) | P1 | 5-7 天 | RT-04 | TODO |
| 6 | [Skill 结晶实际可行性](./RT-06-skill-extraction.md) | P2 | 7-10 天 | RT-01, RT-03 | TODO |
| 7 | [多实例协调与网络分区真实行为](./RT-07-multi-instance.md) | P2 | 5-7 天 | RT-04 | TODO |

## 执行顺序

```
Week 1-2（可并行）:
  RT-01 LLM Route Engine ─────┐
  RT-02 L1 压缩质量 ──────────┤
  RT-04 agent-kernel 对接 ─────┤
                               ↓
Week 3-4:
  RT-03 KnowledgeWiki ingest ──┤  (依赖 RT-01 的 Run 数据)
  RT-05 agent-core 对齐 ───────┤  (依赖 RT-04 的接口映射)
                               ↓
Week 5-6:
  RT-06 Skill 结晶 ────────────┤  (依赖 RT-01+RT-03 积累的 Run 数据)
  RT-07 多实例协调 ─────────────┘  (依赖 RT-04 的 Temporal 集成)
```

## 交付标准

每个课题完成时必须包含：
1. **结论摘要**：一段话回答核心问题
2. **数据表格**：延迟/成本/质量的量化测量结果
3. **代码产出**：可运行的 prototype 或 benchmark 脚本
4. **对架构的反馈**：规范中哪些假设被验证/推翻，需要修改什么
5. **下一步建议**：基于数据的实施建议
