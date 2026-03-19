---
name: V5 破浪路线图（详细）
description: V5 全阶段开发路线图，含进度状态、任务清单、优先级
type: reference
created: 2026-03-19
updated: 2026-03-19
tags: [V5, planned, roadmap, 破浪]
---

# V5 破浪路线图（详细版）

## Phase 1：Walk-Forward 验证 ⚠️ 初步完成（含幸存者偏差）

| 项 | 值 |
|---|---|
| **文件** | scripts/walk_forward_v5_full.py |
| **结果状态** | ⚠️ **含幸存者偏差**，需 Phase 1.5 修正后才可作为上线依据 |

### 当前结果（含偏差，仅供参考）
- V4 趋势: OOS Sharpe 2.33 → PASS（修正后预期 1.6~2.0）
- MR 均值回归: OOS Sharpe 0.959 → PASS（修正后预期 0.6~0.8）  
- ED 事件驱动: OOS Sharpe 0.393 → MARGINAL（修正后预期 0.2~0.4）

## ⭐ Phase 1.5：幸存者偏差修复（上线前硬性前提）

| 项 | 值 |
|---|---|
| **状态** | ⏳ **下一个执行** |
| **优先级** | **P0 — 上线卡口** |
| **预计工时** | Tier 1: 2-3天 / Tier 2: Phase 5 后 |
| **文档** | [[Walk-Forward/07-Survivorship-Bias-Fix]] |

### Tier 1（现在做）
- 实现 get_pit_universe(as_of_year) — AV LISTING_STATUS?date= 还原历史股票名单
- 修改 _fetch_backtest_data 按年份加载对应 PIT universe
- 重跑 walk_forward_v5_full.py，获取修正后结果
- 消除 Future IPO Bias（可信度提升 60-70%）

### Tier 2（Phase 5 FMP 迁移后）
- 拉取已退市股票的历史 OHLCV（需 FMP 750req/min，AV 不可行）
- 彻底消除幸存者偏差

## Phase 2：动态选股池 ⚠️ 代码存在，未完全接入

- Dashboard 展示 ✅ 2026-03-19 完成（/htmx/universe-status）
- 路由端点 /api/universe/refresh ⏳
- Scheduler 集成（每周六 NZT 06:00）⏳

## Phase 3：盘后 AI 事件信号 ✅ 已完成

commit 58f9280，调度 NZT 09:55 周二至周六，飞书推送

## Phase 3b：宏观事件驱动策略 🟡 规划中

P2 优先级，Phase 1.5 + Phase 2 后开发

## Phase 4：信号订阅产品 ✅ 已完成（暂缓推广）

commits 0974ad0 61e3f82 8c537e2，等 WF 结果确认后对外推广

## Phase 5：FMP 替换 Alpha Vantage ⏸️ 等待

等实盘 3 个月后执行。Phase 1.5 Tier 2 依赖此阶段完成。

## 优先级总表（2026-03-19）

| 阶段 | 内容 | 优先级 | 状态 |
|------|------|--------|------|
| Phase 1 | Walk-Forward 初步验证 | P0 | ⚠️ 含偏差 |
| Phase 1.5 | 幸存者偏差修复 Tier 1 | P0 | ⏳ 下一个 |
| Phase 2 | 动态选股池路由+Scheduler | P1 | ⚠️ 部分完成 |
| Phase 3 | AI 事件信号 | P2 | ✅ |
| Phase 3b | 宏观事件驱动 | P2 | 🟡 规划中 |
| Phase 4 | 订阅产品 | P3 | ✅ 暂缓推广 |
| Phase 5 | FMP 迁移 | P1 | ⏸️ |
| Phase 1.5 Tier 2 | 完整幸存者偏差修复 | P1 | ⏳ 等 Phase 5 |

## 执行时间线

2026-03~04：Phase 1.5 Tier 1（2-3天）+ Phase 2 剩余
上线后：小仓位实盘 5K-10K，积累 3 个月
2026-07+：Phase 5 FMP 迁移 → Phase 1.5 Tier 2 → Newsletter 正式推广
