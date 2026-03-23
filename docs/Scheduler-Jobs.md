---
name: 调度任务总表
description: APScheduler 定时任务完整清单：时间/函数/状态/依赖关系/Worker分配
type: reference
created: 2026-03-19
updated: 2026-03-23
tags: [scheduler, jobs, cron, APScheduler, NZT, active, worker-role]
---

# 调度任务总表

> **时区**: 所有时间为 NZT (UTC+13)
> **对应美股**: 盘中 = NZT 01:30-08:00, 收盘 = NZT ~08:00
> **文件**: `app/scheduler.py`
> **Worker 拆分**: `WORKER_ROLE` 环境变量控制（commit `af26f03`）

---

## Worker 角色分配

| WORKER_ROLE | 任务数 | 职责 | Render 服务 |
|-------------|--------|------|-------------|
| `scheduler` | 16 | 交易关键路径（信号/订单/轮动） | `stockqueen-scheduler` |
| `data-worker` | 21 | 数据采集/分析/ML/Newsletter | `stockqueen-data-worker` |
| `all` | 37 | 全部（本地开发用） | — |

---

## 收盘后任务（09:15-10:10 NZT）

| # | 任务 | Cron | 函数 | Worker | 说明 |
|---|------|------|------|--------|------|
| 1 | Market Data Fetch | Tue-Sat 09:15 | `_run_market_data_pipeline()` | scheduler | AV日行情入库 |
| 1b | Regime Monitor | Tue-Sat 09:20 | `_run_regime_monitor()` | scheduler | Regime变化检测+飞书告警 |
| 2 | D+1 Confirmation | Tue-Sat 09:30 | `_run_confirmation_engine()` | scheduler | 信号次日确认 |
| 3 | Daily Entry Check | Tue-Sat 09:40 | `_run_daily_entry_check()` | scheduler | 入场条件检查 |
| 4 | Daily Exit Check | Tue-Sat 09:45 | `_run_daily_exit_check()` | scheduler | 止损/止盈检查 |
| 4e | ML Exit Scorer | Tue-Sat 09:46 | `_run_exit_scorer()` | scheduler | Phase 1 信号采集，XGBoost出场评分 |
| 4f | Midweek Replacement | Tue-Sat 09:47 | `_run_midweek_replacement()` | scheduler | 周中补位：ATR漂移验证 |
| 4d | Sub-Strategy Scan | Tue-Sat 09:50 | `_run_sub_strategy_scan()` | scheduler | MR + ED 候选信号扫描 |
| 5 | Signal Outcome | Tue-Sat 09:50 | `_run_signal_outcome_collector()` | data-worker | 信号结果追踪(1d/5d/20d) |
| 5b | AI Event Signal Scan | Tue-Sat 09:55 | `_run_event_signal_scan()` | data-worker | C2: AV新闻+DeepSeek分类 |
| 6 | News Outcome | Tue-Sat 10:00 | `_run_news_outcome_collector()` | data-worker | 新闻事件关联 |
| 5c | EDGAR Insider Scan | Tue-Sat 10:05 | `_run_insider_scan()` | data-worker | C4: SEC Form 4 内幕交易 |

## 盘中任务（01:00-09:30 NZT）

| # | 任务 | Cron | 函数 | Worker | 说明 |
|---|------|------|------|--------|------|
| 4b | Tiger Order Sync | Tue-Sat 每30min 01:00-09:30 | `_run_sync_tiger_orders()` | scheduler | 券商订单对账 |
| 20 | Intraday Trailing Stop | Tue-Sat 每5min 02:00-08:00 | `_run_intraday_trailing_stop()` | scheduler | 实时Trailing检查 |
| 21 | Unfilled Order Mgr | Tue-Sat 每15min 02:00-08:00 | `_run_manage_unfilled_orders()` | scheduler | 未成交订单管理 |
| 7 | News Pipeline | Tue-Sat 03:30 | `_run_news_pipeline()` | data-worker | RSS+AI新闻分类 |
| 8 | Geopolitical Scan 1 | Tue-Sat 04:00 | `_run_geopolitical_scan()` | scheduler | 地缘政治盘中扫描 |
| 9 | Geopolitical Scan 2 | Tue-Sat 07:30 | `_run_geopolitical_scan()` | scheduler | 地缘政治临近收盘 |

## 周末任务（Saturday NZT）

| # | 任务 | Cron | 函数 | Worker | 说明 |
|---|------|------|------|--------|------|
| 18 | Universe Refresh | Sat 09:00 | `_run_universe_refresh()` | data-worker | 动态选股池刷新 |
| 22a | FMP Fundamental Data | Sat 09:30 | `_run_fundamental_data_collector()` | data-worker | 公司概况+TTM比率 |
| 22b | FMP Earnings Calendar | Sat 09:30 | `_run_earnings_calendar_collector()` | data-worker | 历史EPS+beat率 |
| 22c | FMP Income Growth | Sat 09:30 | `_run_income_growth_collector()` | data-worker | 季度收入表 |
| 22d | FMP Cash Flow Health | Sat 09:30 | `_run_cashflow_health_collector()` | data-worker | 季度现金流 |
| 14 | Weekly Rotation | Sat 10:00 | `_run_weekly_rotation()` | scheduler | 核心周轮动 |
| 14b | Yearly Performance | Sat 10:15 | `_run_refresh_yearly_performance()` | scheduler | 年度业绩JSON刷新 |
| 14c | Equity Curve | Sat 10:20 | `_run_refresh_equity_curve()` | scheduler | 权益曲线JSON刷新 |
| 15 | Pattern Statistics | Sat 10:30 | `_run_pattern_stat_collector()` | data-worker | 技术形态统计 |
| 16 | Sector Rotation | Sat 10:30 | `_run_sector_rotation_collector()` | data-worker | 板块轮动记录 |
| 17 | Backtest Precompute | **GitHub Actions** | — | — | 每周六 22:00 UTC |
| 20a | Newsletter Preview | Sat 16:00 | `_run_newsletter_preview()` | data-worker | 生成+发预览邮件 |
| 20b | Newsletter Send | Sat 21:00 | `_run_newsletter_generation()` | data-worker | 审批后发送 |

## AI增强收集器（10:15-11:30 NZT）

| # | 任务 | Cron | 函数 | Worker | 说明 |
|---|------|------|------|--------|------|
| AI-1 | AI Sentiment | Tue-Sat 10:15 | `_run_ai_sentiment_collector()` | data-worker | AI情绪评分 |
| AI-2 | ETF Fund Flow | Tue-Sat 10:30 | `_run_etf_flow_collector()` | data-worker | ETF资金流向 |
| AI-3 | Earnings Analyzer | Tue-Sat 11:00 | `_run_earnings_report_collector()` | data-worker | 财报分析 |
| AI-4 | 13F Holdings | Sat 11:30 | `_run_institutional_holdings_collector()` | data-worker | 机构持仓 |

## 月度/维护

| # | 任务 | Cron | 函数 | Worker | 说明 |
|---|------|------|------|--------|------|
| 24 | Auto Param Tune | 每月1日 12:00 | `_run_auto_param_tune()` | data-worker | 月度参数微调 |
| 24b | ML-V3A Retrain | 每月1日 13:00 | `_run_ml_monthly_retrain()` | data-worker | 滑动18月重训XGBRanker |
| 25 | KB Cleanup | 每天 15:00 | `_run_knowledge_cleanup()` | data-worker | 知识库清理 |

---

## 任务依赖链

```
[scheduler] 09:15 Market Data → 09:20 Regime → 09:30 D+1 Confirm
                                                 ↓
[scheduler] 09:40 Entry → 09:45 Exit → 09:46 ML Exit → 09:47 Midweek
                                                 ↓
[scheduler] 09:50 Sub-Strategy Scan
[data-worker] 09:50 Signal Outcome
[data-worker] 09:55 AI Event (C2) → 10:00 News Outcome → 10:05 EDGAR (C4)

[data-worker] Sat 09:00 Universe → 09:30 FMP x4
[scheduler]   Sat 10:00 Rotation → 10:15 Yearly Perf → 10:20 Equity Curve
[data-worker] Sat 10:30 Pattern + Sector
[data-worker] Sat 16:00 Newsletter Preview → 21:00 Send

[data-worker] 每月1日 12:00 Param Tune → 13:00 ML Retrain
```

---

## 手动触发 API

| 端点 | 说明 |
|------|------|
| `POST /api/admin/run-event-scan` | 立即触发 C2 事件信号扫描 |
| `POST /api/admin/refresh-yearly-performance` | 刷新年度业绩JSON |
| `POST /api/admin/refresh-equity-curve` | 刷新权益曲线JSON |
| `POST /htmx/backtest-run` | 前台回测运行 |
| `POST /rotation/ml/retrain?months_lookback=18` | 手动触发 ML-V3A 重训 |

> Admin 端点需要 Header: `X-Admin-Token: <ADMIN_TOKEN>`
> Rotation 端点需要 Header: `X-API-Key: <API_KEY>`
