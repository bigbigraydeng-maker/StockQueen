---
name: 破浪计划 — 活跃项目追踪
description: StockQueen 破浪 产品化破浪计划总表（项目状态追踪）
created: 2026-03-19
updated: 2026-04-02
tags: [projects, tracker, v5, active, 破浪]
---

# 🌊 破浪计划 — 项目追踪总表

> **这是破浪实验室行动记录，直接产品化，不搞研究。住在：向前冲！**
>
> 「破浪」=「进攻」= StockQueen 破浪 产品化全流程（探索未知、创造价值、所向披靡）
> **每次开始任务前先查看此处，从上到下执行。**

---

## 📋 项目状态一览

| 优先级 | 项目 | 文档 | 状态 | 完成日期 |
|--------|------|------|------|---------|
| **P0** | 🔗 综合策略 V5 整合（V4+MR+ED） | [[Projects/A0-Multi-Strategy-V5]] | 🔵 规划中 | 预计商业化 2026-09 |
| **P1** | 📊 Dashboard 多策略信号展示 | [[Projects/C1-Dashboard-Signals]] | ✅ 已完成 | 2026-03-19 |
| **P2** | 📰 盘后 AI 新闻事件信号 | [[Projects/C2-AI-Event-Signals]] | ✅ 已完成 | 2026-03-19 |
| **P1** | 🌐 动态选股池 | [[Strategy/15-Dynamic-Universe]] | ✅ 已完成 | 2026-03-19 |
| **P1** | 🤖 ML-V3A 非对称标签 | [[Projects/B1-ML-V3]] | ✅ 已完成 | 2026-03-20 |
| **P1** | 📊 MR/ED Walk-Forward 验证 | [[Walk-Forward/06-Sub-Strategy-WF-Validation]] | ✅ 已完成 | 2026-03-21 |
| **P2** | 🗺️ 板块热力图归并优化 | [[Frontend-Website]] | ✅ 已完成 | 2026-03-22 |
| **P1** | 🔒 Sub-Tranche 出场优化 | [[Projects/D1-Sub-Tranche-Exit]] | 🟡 观测期（Phase 4） | — |
| **P1** | 🔄 Massive 数据源迁移 | [[Projects/V5-Roadmap-Detail#Phase-5]] | 🟡 进行中 | — |
| **P3** | 📧 Newsletter 订阅产品 | [[Projects/C3-Newsletter-Product]] | 🟡 进行中（Lab ✅ / Stripe 🔲）| — |
| **P2** | 💰 融资 Seed Round | [[Projects/E1-Fundraising]] | 🟡 进行中（文件草稿完成）| — |
| **P2** | 🔔 铃铛盘中动能（执行层） | [[Projects/C5-Intraday-Bell-Momentum]] | 🟡 迭代中 | 池子分层+入场确认 2026-04-02 |

---

## 🗺️ 依赖关系图

```
综合策略 V5（A0）——规划中——（开始时间待定）
      │
      ├── MR WF ✅ OOS Sharpe 0.96，RSI=28 锁定（2026-03-21）
      ├── ED WF ✅ OOS Sharpe 0.29，门控已上线（bear/choppy only）（2026-03-21）
      └── 3个月实盘核查（预计 2026-06-21）

ML-V3A（B1）✅ 已完成 2026-03-20
Sub-Tranche 出场优化（D1）🟡 Phase 4 观测期
      模型已训练（exit_scorer.pkl），Job 4e 每日运行
      信号采集中，Tranche B 执行层待开发

Massive 数据源迁移 🟡 进行中（替换 AV + FMP，统一 MASSIVE_API_KEY）

Dashboard信号（C1）✅ 已完成
盘后AI新闻（C2）✅ 已完成
板块热力图归并 ✅ 已完成 2026-03-22（33→21 sector，normalize_sector，DB迁移）
Newsletter订阅（C3）🟡 进行中 — Lab ✅ / Stripe 🔲
```

---

## ✅ 本周完成（2026-03-17 ~ 2026-03-22）

| 完成项 | 说明 |
|------|------|
| 宝典V4 模拟实盘上线 | Tiger Paper Trading，4仓已开（SH/PSQ/RWM/SHY）|
| lab 页面升级 | DEV PREVIEW → 模拟实盘 LIVE，A0 持仓面板 |
| 策略页数据纠偏 | Universe/TOP_N/Sharpe 全部修正为实际值 |
| MR WF ✅ | OOS 0.96，RSI=28 锁定 |
| ED WF ✅ + 门控 | bull/strong_bull 时停止入场 |
| D1 文档同步 | Phase 4 观测期，实际进度已远超文档 |
| Massive 迁移启动 | API Key 获取，接入替换 AV + FMP |
| **板块热力图归并** | **33→21 sector, normalize_sector(), top_tickers截断15, 详情页分页, DB迁移** |

---

## 📋 下周待办

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P1 | Massive 客户端开发 | massive_client.py 替换 alphavantage_client.py + fmp_client.py |
| P1 | D1 Tranche B 执行层 | 等观测期积累信号后开发（sub_trades 表 + 拆仓逻辑）|
| P2 | C3 Stripe 付费墙 | Checkout/Webhook/7天试用 |
| P3 | A0 综合策略规划 | MR/ED WF 已验证，可以开始设计组合权重 |

---

## 📁 归档规则

> ✅ **每个项目完成后必须执行（防止文档失效）：**

```
1. 将项目文档移至 docs/Archive/YYYY-MM/ 目录
2. 将状态更新为 ✅（并注释完成日期）
3. 更新对应后端文档（Strategy/ ML/ Backend-Services 等）
4. 将验证结果存入 Walk-Forward/ 或 Strategy/
5. 从本表删除条目
```

---

## 状态图例

| 符号 | 含义 |
|------|------|
| 🟡 | 进行中（当前主线任务）|
| 🔵 | 规划中（已设计，待开始）|
| 🔲 | 未开始（排队中）|
| ✅ | 已完成（已归档）|
| 🟠 | 阻塞中（外部依赖）|

---

## 📎 相关参考文档

- [[Projects/V5-Roadmap-Detail]] — V5 完整路线图（各阶段详细清单）
- [[ML/00-Index]] — ML 增强层文档
- [[ML/04-AB-Test-Results]] — V1/V2/V3A 全部 A/B 测试结果
- [[Walk-Forward/06-Sub-Strategy-WF-Validation]] — 子策略验证结果
- [[Backend-Services]] — 后端服务清单
- [[Product-Marketing]] — 产品营销文档
