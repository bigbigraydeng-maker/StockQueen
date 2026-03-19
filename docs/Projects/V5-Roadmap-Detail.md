---
name: V5 破浪路线图（详细）
description: V5 全阶段开发路线图，含进度状态、任务清单、优先级
type: reference
created: 2026-03-19
updated: 2026-03-19
tags: [V5, planned, roadmap, 破浪]
---

# V5 破浪路线图（详细版）

## Phase 1：Walk-Forward 验证 ✅ 完成

### 最终结论（PIT修正 + 三版对比）
- V4 OOS Sharpe：**3.10**（5/5窗口全正，最差1.97）
- 最优参数：**TOP_N = 3**（三版WF对比验证）
- 判定：**绿灯上线 ✅**
- 详见 [[Walk-Forward/08-PIT-WF-Results-V4]]

---

## Phase 1.5：幸存者偏差修复 ✅ 完成（2026-03-19）

### Tier 1 完成内容
- `universe_service.py` 新增 `get_pit_universe(as_of_year)`
- `walk_forward_v5_full.py` 接入 PIT universe_filter
- 补充搜索范围 top_n=[2-7]，三版对比锁定 top_n=3

### Tier 2（Phase 5 FMP 迁移后）
- 拉取已退市股票历史 OHLCV，彻底消除幸存者偏差

---

## Phase 2：动态选股池 ⚠️ 部分完成

- Dashboard 选股池面板 ✅（/htmx/universe-status，2026-03-19）
- /api/universe/refresh 路由 ❌ 待做
- Scheduler 每周六自动刷新 ❌ 待做

---

## Phase 3：盘后 AI 事件信号 ✅ 完成

commit 58f9280，NZT 09:55 调度，飞书推送

---

## Phase 3b：宏观事件驱动策略 🟡 规划中

---

## Phase 4：信号订阅产品 ✅ 完成（暂缓推广）

---

## Phase 5：FMP 替换 AV ⏸️ 等待实盘3月后

---

## 优先级总表（2026-03-19 最终）

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 + 1.5 | WF验证 + PIT修正 + top_n锁定 | ✅ 完成 |
| 生产参数 | TOP_N=3（已改） | ✅ 完成 |
| Worktree merge | 今晚所有改动推main | 🔵 待执行 |
| Phase 2 剩余 | Universe路由+Scheduler | 🔵 本周 |
| MR/ED WF | 补跑验证 | 🔲 本周 |
| 实盘上线 | V4 30%仓位 | 🔵 WF绿灯，等merge |
| Phase 5 | FMP迁移 | ⏸️ 实盘3月后 |

## 执行时间线

```
今晚（2026-03-19）
  ✅ Phase 1.5 Tier 1 完成
  ✅ TOP_N=3 锁定
  🔵 Worktree merge → main → push

本周
  → Phase 2 Universe路由 + Scheduler
  → MR/ED WF补跑
  → V4 实盘上线（30%仓位）

2026-07+
  → FMP迁移 → Phase 1.5 Tier 2 → Newsletter推广
```
