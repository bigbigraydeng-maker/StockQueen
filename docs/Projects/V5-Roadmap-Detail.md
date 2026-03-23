---
name: V5 破浪路线图（详细）
description: V5 全阶段开发路线图，含进度状态、任务清单、优先级
type: reference
created: 2026-03-19
updated: 2026-03-21
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
- `universe_service.py` 新增 `async def get_pit_universe(as_of_year)`
- `walk_forward_v5_full.py` 接入 PIT universe_filter
- 补充搜索范围 top_n=[2-7]，三版对比锁定 top_n=3

### Tier 2（Phase 5 Massive 迁移后）
- 拉取已退市股票历史 OHLCV，彻底消除幸存者偏差
- Massive 高速率（750 req/min）使 ~14,000 次历史查询约 2 小时可完成

---

## Phase 2：动态选股池 ✅ 完成（2026-03-21 核实）

- Dashboard 选股池面板 ✅（/htmx/universe-status）
- `POST /api/admin/refresh-universe` 路由 ✅（web.py line 4236）
- `POST /htmx/admin/refresh-universe` 路由 ✅（web.py line 5102）
- Job 18：周六 09:00 NZT 自动刷新 ✅（scheduler.py line 352）
- `USE_DYNAMIC_UNIVERSE=True` ✅（rotation_watchlist.py）
- 动态选股池当前：**1,688只**（2026-03-20 刷新）

---

## Phase 3：盘后 AI 事件信号 ✅ 完成

commit 58f9280，NZT 09:55 调度，飞书推送

---

## Phase 3b：宏观事件驱动策略 🟡 规划中

---

## Phase 4：信号订阅产品 ✅ 完成（暂缓推广）

---

## Phase 5：Massive 数据源迁移 🟡 进行中

**目标**：将 Alpha Vantage（行情/基本面/新闻）+ FMP（财报日历）统一替换为 Massive，单一 API Key。

**迁移范围**：
- `alphavantage_client.py` → `massive_client.py`
- `fmp_client.py` → 合并至 `massive_client.py`
- 环境变量：`AV_API_KEY` + `FMP_API_KEY` → `MASSIVE_API_KEY`

**接口覆盖**：
- 日行情 OHLCV
- 公司概况 profile
- TTM 财务比率 ratios-ttm
- 季度收入表 income-statement
- 季度现金流 cash-flow-statement
- 财报日历 earnings
- 新闻情绪

---

## 优先级总表（2026-03-21 更新）

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 + 1.5 | WF验证 + PIT修正 + top_n锁定 | ✅ 完成 |
| 生产参数 | TOP_N=3, HB=0（已改）| ✅ 完成 |
| Worktree merge | 所有改动已推main | ✅ 完成 |
| Phase 2 | Universe路由+Scheduler+动态池 | ✅ 完成 |
| ML-V3A | 非对称标签排序上线 | ✅ 完成（2026-03-20） |
| 模拟实盘 | 宝典V4 Tiger Paper Trading | ✅ 运行中（4仓已开） |
| D1 Sub-Tranche | ML Exit Scorer（Phase 1 训练集）| 🟡 进行中 |
| MR/ED WF | 补跑验证 | 🔲 待做 |
| C3 Stripe | Newsletter 付费墙 | 🔲 待做 |
| Phase 5 | Massive 数据源迁移 | 🟡 进行中 |

## 执行时间线

```
✅ 2026-03-19  Phase 1.5 Tier 1 完成，TOP_N=3 锁定
✅ 2026-03-20  ML-V3A 上线，Worktree merge → main
✅ 2026-03-21  Phase 2 核实完成，破浪模拟实盘正式上线

本周（2026-03-22~）
  → Massive 数据源迁移（massive_client.py 开发）
  → D1 Sub-Tranche Phase 1（生成训练集）
  → MR/ED WF 补跑验证

待定
  → C3 Stripe 付费墙
  → Phase 1.5 Tier 2（退市股历史数据，用 Massive 高速率）→ Newsletter推广
```
