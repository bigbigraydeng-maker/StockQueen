---
name: 破浪计划 — 活跃项目追踪
description: StockQueen V5 产品化破浪计划总表（项目状态追踪）
created: 2026-03-19
updated: 2026-03-19
tags: [projects, tracker, v5, active, 破浪]
---

# 🌊 破浪计划 — 项目追踪总表

> **这是破浪实验室行动记录，直接产品化，不搞研究。住在：向前冲！**
>
> 「破浪」=「进攻」= StockQueen V5 产品化全流程（探索未知、创造价值、所向披靡）
> **每次开始任务前先查看此处，从上到下执行。**

---

## 📋 项目状态一览

| 优先级 | 项目 | 文档 | 状态 | 完成日期 |
|--------|------|------|------|---------|
| **P0** | 🔗 综合策略 V5 整合（V4+MR+ED） | [[Projects/A0-Multi-Strategy-V5]] | 🟡 规划中 | 预计商业化 2026-09 |
| **P1** | 📊 Dashboard 多策略信号展示 | [[Projects/C1-Dashboard-Signals]] | ✅ 已完成 | 2026-03-19 |
| **P2** | 📰 盘后 AI 新闻事件信号 | [[Projects/C2-AI-Event-Signals]] | ✅ 已完成 | 2026-03-19 |
| **P1** | 🌐 动态选股池 | [[Strategy/15-Dynamic-Universe]] | ✅ 已完成 | 2026-03-19 |
| **P1** | 🤖 ML-V3 非对称标签 | [[Projects/B1-ML-V3]] | 🟡 等待FMP | TBD |
| **P1** | 📡 FMP 数据源迁移 | [[Projects/V5-Roadmap-Detail#Phase-5]] | 🟡 等待用户评估底线 | 用户决定 |
| **P3** | 📧 Newsletter 订阅产品 | [[Projects/C3-Newsletter-Product]] | 🟡 进行中（Lab ✅ / Stripe 🔲） | — |

---

## 🗺️ 依赖关系图

```
综合策略 V5（A0）——规划中——（开始时间待定）
      │
      ├── ED（可行性测试）——待做
      ├── Monte Carlo（修复负债比）——待做
      └── 3个月实盘核查（2026-06-19）

FMP迁移（用户自行使用才触发）
      │
      └──→ ML-V3（B1）——规划中 ——需要优质选股池

Dashboard信号（C1）✅ 已完成
      │
盘后AI新闻（C2）✅ 已完成
      │
Newsletter订阅（C3）🟡 进行中 — Lab ✅ / Stripe 🔲
```

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
| 🟡 | 进行中（当前主线任务） |
| 🔵 | 规划中（已设计，待开始） |
| 🔲 | 未开始（排队中） |
| ✅ | 已完成（已归档） |
| 🟠 | 阻塞中（外部依赖） |

---

## 📎 相关参考文档

- [[Projects/V5-Roadmap-Detail]] — V5 完整路线图（各阶段详细清单）
- [[ML/00-Index]] — ML 增强层文档
- [[Walk-Forward/06-Sub-Strategy-WF-Validation]] — 子策略验证结果
- [[Backend-Services]] — 后端服务清单
- [[Product-Marketing]] — 产品营销文档
