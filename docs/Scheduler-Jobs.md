---
name: 调度任务总表
description: APScheduler 定时任务完整清单：时间/函数/状态/依赖关系
type: reference
created: 2026-03-19
updated: 2026-03-19
tags: [scheduler, jobs, cron, APScheduler, NZT, active]
---

# 调度任务总表

> **时区**: 所有时间为 NZT (UTC+13)
> **对应美股**: 盘中 = NZT 01:30-08:00, 收盘 = NZT ~08:00
> **文件**: `app/scheduler.py`

---

## 收盘后任务（09:15-10:00 NZT）

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 1 | Market Data Fetch | Tue-Sat 09:15 | `_run_market_data_pipeline()` | AV日行情入库 |
| 1b | Regime Monitor | Tue-Sat 09:20 | `_run_regime_monitor()` | Regime变化检测+飞书告警 |
| 2 | D+1 Confirmation | Tue-Sat 09:30 | `_run_confirmation_engine()` | 信号次日确认 |
| 3 | Daily Entry Check | Tue-Sat 09:40 | `_run_daily_entry_check()` | 入场条件检查 |
| 4 | Daily Exit Check | Tue-Sat 09:45 | `_run_daily_exit_check()` | 止损/止盈检查 |
| 5 | Signal Outcome | Tue-Sat 09:50 | `_run_signal_outcome_collector()` | 信号结果追踪(1d/5d/20d) |
| **5b** | **AI Event Signal Scan** | **Tue-Sat 09:55** | `_run_event_signal_scan()` | **C2: AV新闻+DeepSeek分类→飞书推送** |
| 6 | News Outcome | Tue-Sat 10:00 | `_run_news_outcome_collector()` | 新闻事件关联 |

## 盘中任务（02:30-09:00 NZT）

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 7 | Tiger Order Sync | Tue-Sat 每30min 01:00-09:30 | `_run_sync_tiger_orders()` | 券商订单对账 |
| 8 | Intraday Price Scan | Tue-Sat 每20min 02:30-08:40 | `_run_intraday_price_scan()` | 盘中行情扫描 |
| 9 | Intraday Trailing Stop | Tue-Sat 每5min | `_run_intraday_trailing_stop()` | 实时Trailing检查 |
| 10 | Unfilled Order Mgr | Tue-Sat 每15min | `_run_manage_unfilled_orders()` | 未成交订单管理 |
| 11 | News Pipeline | Tue-Sat 03:30 | `_run_news_pipeline()` | RSS+AI新闻分类 |
| 12 | Geopolitical Scan 1 | Tue-Sat 04:00 | `_run_geopolitical_scan()` | 地缘政治盘中扫描 |
| 13 | Geopolitical Scan 2 | Tue-Sat 07:30 | `_run_geopolitical_scan()` | 地缘政治临近收盘 |

## 周末任务（Saturday 10:00-12:00 NZT）

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 14 | Weekly Rotation | Sat 10:00 | `_run_weekly_rotation()` | 核心周轮动 |
| 15 | Pattern Statistics | Sat 10:30 | `_run_pattern_stat_collector()` | 技术形态统计 |
| 16 | Sector Rotation | Sat 10:30 | `_run_sector_rotation_collector()` | 板块轮动记录 |
| 17 | Backtest Precompute | Sat 11:00 | `_run_backtest_precompute()` | 25组合预计算 |
| 18 | Newsletter Gen+Send | Sat 12:00 | `_run_newsletter_generation()` | 周报生成+发送 |

## AI增强收集器（10:15-11:30 NZT）

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 19 | AI Sentiment | Tue-Sat 10:15 | `_run_ai_sentiment_collector()` | AI情绪评分（知识库） |
| 20 | ETF Fund Flow | Tue-Sat 10:30 | `_run_etf_flow_collector()` | ETF资金流向 |
| 21 | Earnings Analyzer | Tue-Sat 11:00 | `_run_earnings_report_collector()` | 财报分析 |
| 22 | 13F Holdings | Sat 11:30 | `_run_institutional_holdings_collector()` | 机构持仓 |

## 月度/维护

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 23 | Auto Param Tune | 每月1日 12:00 | `_run_auto_param_tune()` | 月度参数微调 |
| **23b** | **ML-V3A Monthly Retrain** | **每月1日 13:00** | `_run_ml_monthly_retrain()` | **滑动18个月重训 XGBRanker，完成后飞书通知** |
| 24 | KB Cleanup | 每天 15:00 | `_run_knowledge_cleanup()` | 知识库清理 |

---

## 任务依赖链

```
09:15 Market Data ──→ 09:20 Regime ──→ 09:30 D+1 Confirm
                                        ↓
                      09:40 Entry Check ──→ 09:45 Exit Check
                                             ↓
                      09:50 Signal Outcome
                                             ↓
                      09:55 AI Event Scan (C2) ← Tiger持仓 + 轮动快照
                                             ↓ 飞书推送 + event_signals表
                      10:00 News Outcome

Sat 10:00 Weekly Rotation
├── 10:30 Pattern Stats + Sector Rotation
├── 11:00 Backtest Precompute
└── 12:00 Newsletter

10:15-11:30 AI收集器（独立，不阻塞主链）
```

---

## 手动触发 API

| 端点 | 说明 |
|------|------|
| `POST /api/admin/run-event-scan` | 立即触发 C2 事件信号扫描 |
| `POST /api/admin/refresh-yearly-performance` | 刷新年度业绩JSON |
| `POST /htmx/backtest-run` | 前台回测运行 |
| `POST /rotation/ml/retrain?months_lookback=18` | 手动触发 ML-V3A 重训（后台，完成后飞书通知）|

> Admin 端点需要 Header: `X-Admin-Token: <ADMIN_TOKEN>`
> Rotation 端点需要 Header: `X-API-Key: <API_KEY>`
