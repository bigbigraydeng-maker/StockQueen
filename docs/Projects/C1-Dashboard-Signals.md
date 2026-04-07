---
name: Project C1 - Dashboard Multi-Strategy Signals
description: MR/ED 子策略信号展示（破浪实验室 /lab 页面）
created: 2026-03-19
updated: 2026-03-21
tags: [project, dashboard, signals, mr, ed, lab]
status: completed
completed: 2026-03-19
---

# 📊 Project C1：Dashboard 多策略信号展示

## ✅ 已完成（2026-03-19）

> **设计决策**：信号展示放在 `/lab`（破浪实验室）而非生产 Dashboard，避免干扰正式界面。

---

## 实现架构

```
GET /lab
  └── lab.html
        └── C1 区块（HTMX，每300秒刷新）
              └── GET /htmx/sub-strategies
                    └── partials/_sub_strategies.html
                          ├── MR 候选信号列表（RSI/BB触发）
                          ├── ED 候选信号列表（财报事件）
                          ├── 当前 Regime + 资金分配比例
                          └── 无持仓时显示空状态
```

---

## 新增/修改文件

| 文件 | 说明 |
|------|------|
| `app/routers/web.py` | 新增 `GET /lab` + `GET /htmx/sub-strategies` |
| `app/templates/lab.html` | 破浪实验室主页（含 C1/C2/C3/B1 区块） |
| `app/templates/partials/_sub_strategies.html` | C1 HTMX 局部模板（新建） |
| `app/services/portfolio_manager.py` | 新增 `get_cached_daily_signals()` + `get_strategy_allocations()` |

---

## 功能说明

### `/lab` 破浪实验室页面
- C1 MR/ED 子策略信号（本 checklist）
- C2 AI 事件信号（状态卡片）
- C3 Newsletter 管理面板
- B1 ML-V3（ML排序，Massive 数据驱动）

### `/htmx/sub-strategies` 数据来源
- `get_cached_daily_signals()` → 从 Supabase `cache_store` 读取上次盘后扫描结果
  - `mr_candidates`: MR 触发列表（RSI < 28 + BB底部）
  - `ed_candidates`: ED 触发列表（财报超预期，数据来自 Massive）
- `get_strategy_allocations(regime)` → 根据当前体制返回三策略资金分配比例
  - Bull: V4 60% / MR 25% / ED 15%
  - Bear: V4 100% / MR 0% / ED 0%（防御模式）

---

## 与生产 Dashboard 的区别

| 页面 | 用途 | 内容 |
|------|------|------|
| `/dashboard` | 生产监控（用户可见） | V4 持仓 + Regime + 信号历史 |
| `/lab` | 实验室（内部） | MR/ED 候选信号 + 破浪项目进度 |

---

## 📎 相关文档

- [[Projects/C2-AI-Event-Signals]] — C2 事件信号
- [[Projects/C3-Newsletter-Product]] — C3 Newsletter
- [[Backend-Services]] — 后端服务
- [[Projects/00-Active-Projects]] — 返回项目总览
