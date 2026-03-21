"""更新 Obsidian：SEC EDGAR Form 4 内幕信号开发记录"""
import urllib.request, ssl

TOKEN = 'f49ee79c2be8d5f7b2166185e4141b38e7fe26ee828185bf9688a407c79a32cf'
BASE  = 'https://127.0.0.1:27124/vault/'
ctx   = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode    = ssl.CERT_NONE

def put(path, content):
    data = content.encode('utf-8')
    url  = BASE + path
    req  = urllib.request.Request(url, data=data, method='PUT')
    req.add_header('Authorization', 'Bearer ' + TOKEN)
    req.add_header('Content-Type', 'text/markdown; charset=utf-8')
    with urllib.request.urlopen(req, context=ctx) as r:
        print(f'OK [{r.status}] {path}')


# ============================================================
# 1. Scheduler-Jobs.md
# ============================================================
SCHEDULER_JOBS = """---
name: 调度任务总表
description: APScheduler 定时任务完整清单：时间/函数/状态/依赖关系
type: reference
created: 2026-03-19
updated: 2026-03-21
tags: [scheduler, jobs, cron, APScheduler, NZT, active]
---

# 调度任务总表

> **时区**: 所有时间为 NZT (UTC+13)
> **对应美股**: 盘中 = NZT 01:30-08:00, 收盘 = NZT ~08:00
> **文件**: `app/scheduler.py`

---

## 收盘后任务（09:15-10:10 NZT）

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 1 | Market Data Fetch | Tue-Sat 09:15 | `_run_market_data_pipeline()` | AV日行情入库 |
| 1b | Regime Monitor | Tue-Sat 09:20 | `_run_regime_monitor()` | Regime变化检测+飞书告警 |
| 2 | D+1 Confirmation | Tue-Sat 09:30 | `_run_confirmation_engine()` | 信号次日确认 |
| 3 | Daily Entry Check | Tue-Sat 09:40 | `_run_daily_entry_check()` | 入场条件检查 |
| 4 | Daily Exit Check | Tue-Sat 09:45 | `_run_daily_exit_check()` | 止损/止盈检查 |
| **4e** | **ML Exit Scorer** | **Tue-Sat 09:46** | `_run_exit_scorer()` | **Phase 1 信号采集，XGBoost出场评分（不执行交易）** |
| **4b** | **Midweek Replacement** | **Tue-Sat 09:47** | `_run_midweek_replacement()` | **周中补位：ATR漂移验证，效率优化** |
| **4c** | **Sub-Strategy Scan** | **Tue-Sat 09:50** | `_run_sub_strategy_scan()` | **MR + ED 候选信号扫描** |
| 5 | Signal Outcome | Tue-Sat 09:50 | `_run_signal_outcome_collector()` | 信号结果追踪(1d/5d/20d) |
| **5b** | **AI Event Signal Scan** | **Tue-Sat 09:55** | `_run_event_signal_scan()` | **C2: AV新闻+DeepSeek分类→飞书推送** |
| 6 | News Outcome | Tue-Sat 10:00 | `_run_news_outcome_collector()` | 新闻事件关联 |
| **5c** | **EDGAR Insider Scan** | **Tue-Sat 10:05** | `_run_insider_scan()` | **C4: SEC Form 4 内幕交易→清洗→聚合→event_signals** |

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

## 周末任务（Saturday 09:00-12:00 NZT）

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| **18** | **Universe Refresh** | **Sat 09:00** | `_run_universe_refresh()` | **动态选股池刷新（1578 tickers，轮动前1小时）** |
| 14 | Weekly Rotation | Sat 10:00 | `_run_weekly_rotation()` | 核心周轮动 |
| **14b** | **Yearly Performance Refresh** | **Sat 10:15** | `_run_refresh_yearly_performance()` | **年度业绩JSON刷新** |
| **14c** | **Equity Curve Refresh** | **Sat 10:20** | `_run_refresh_equity_curve()` | **月度权益曲线JSON刷新（首页图表）** |
| 15 | Pattern Statistics | Sat 10:30 | `_run_pattern_stat_collector()` | 技术形态统计 |
| 16 | Sector Rotation | Sat 10:30 | `_run_sector_rotation_collector()` | 板块轮动记录 |
| 17 | Backtest Precompute | Sat 11:00 | `_run_backtest_precompute()` | 25组合预计算 |
| 19 | Newsletter Gen+Send | Sat 12:00 | `_run_newsletter_generation()` | 周报生成+发送 |

## AI增强收集器（10:15-11:30 NZT）

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 20 | AI Sentiment | Tue-Sat 10:15 | `_run_ai_sentiment_collector()` | AI情绪评分（知识库） |
| 21 | ETF Fund Flow | Tue-Sat 10:30 | `_run_etf_flow_collector()` | ETF资金流向 |
| 22 | Earnings Analyzer | Tue-Sat 11:00 | `_run_earnings_report_collector()` | 财报分析 |
| 23 | 13F Holdings | Sat 11:30 | `_run_institutional_holdings_collector()` | 机构持仓 |

## 月度/维护

| # | 任务 | Cron | 函数 | 说明 |
|---|------|------|------|------|
| 24 | Auto Param Tune | 每月1日 12:00 | `_run_auto_param_tune()` | 月度参数微调 |
| **24b** | **ML-V3A Monthly Retrain** | **每月1日 13:00** | `_run_ml_monthly_retrain()` | **滑动18个月重训 XGBRanker，完成后飞书通知** |
| 25 | KB Cleanup | 每天 15:00 | `_run_knowledge_cleanup()` | 知识库清理 |

---

## 任务依赖链

```
09:15 Market Data ──→ 09:20 Regime ──→ 09:30 D+1 Confirm
                                        ↓
                      09:40 Entry Check ──→ 09:45 Exit Check
                                             ↓
                      09:50 Signal Outcome
                                             ↓
                      09:55 AI Event Scan (C2) ← AV新闻 + DeepSeek
                                             ↓ event_signals表
                      10:00 News Outcome
                                             ↓
                      10:05 EDGAR Insider Scan (C4) ← SP100+大盘股 Form 4
                                             ↓ insider_transactions + event_signals表

Sat 09:00 Universe Refresh
Sat 10:00 Weekly Rotation
├── 10:15 Yearly Performance Refresh (JSON)
├── 10:20 Equity Curve Refresh (JSON)
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
| `POST /api/admin/refresh-equity-curve` | 刷新权益曲线JSON |
| `POST /htmx/backtest-run` | 前台回测运行 |
| `POST /rotation/ml/retrain?months_lookback=18` | 手动触发 ML-V3A 重训（后台，完成后飞书通知）|

> Admin 端点需要 Header: `X-Admin-Token: <ADMIN_TOKEN>`
> Rotation 端点需要 Header: `X-API-Key: <API_KEY>`
"""

# ============================================================
# 2. Data-Infrastructure.md
# ============================================================
DATA_INFRA = """---
name: 数据基础设施
description: Supabase数据库表、外部API、缓存层、数据流向
type: reference
created: 2026-03-19
updated: 2026-03-21
tags: [data, database, supabase, API, cache, infrastructure, active]
---

# 数据基础设施

## 外部服务

| 服务 | 用途 | 套餐 | 月费 | 状态 |
|------|------|------|------|------|
| **Render** | 应用托管 | Starter | $7 | 运行中 |
| **Supabase** | PostgreSQL + pgvector | Pro | $25 | 运行中 |
| **Massive** | 行情/基本面/财报/新闻 | 付费版 | — | 运行中 |
| **SEC EDGAR** | Form 4 内幕交易申报 | **免费** | $0 | 运行中 |
| **Tiger Broker** | 交易执行 API | — | 佣金制 | 运行中 |
| **DeepSeek** | AI分类/聊天 | Pay-per-use | ~$2 | 运行中 |
| **OpenAI** | 文本Embedding | Pay-per-use | ~$1 | 运行中 |
| **Anthropic** | Claude Newsletter | Pay-per-use | ~$3 | 运行中 |
| **Resend** | 邮件发送 | Free/Starter | $0-20 | 运行中 |
| **Stripe** | 支付处理 | Standard | 2.9%+30¢ | 运行中 |
| **Feishu** | 飞书机器人 | 企业版 | 免费 | 运行中 |

> **SEC EDGAR**：官方免费 API，提供 Form 4 内幕交易申报 XML，要求请求头带联系信息，max 10 req/sec。

---

## Supabase 数据库表

### 交易核心
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `positions` | 当前持仓 | 每笔交易 |
| `orders` | 订单记录 | 每笔交易 |
| `trade_history` | 已平仓交易 | 每次平仓 |

### 策略数据
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `rotation_snapshots` | 轮动评分快照 | 每周一次 |
| `sector_snapshots` | 板块评分快照 | 每周一次 |
| `regime_history` | Regime变化记录 | 每日 |
| `backtest_results` | 回测结果缓存 | 每周预计算 |

### 信号系统
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `signals` | 信号记录 | 每日 |
| `signal_confirmations` | D+1确认 | 每日 |
| `signal_outcomes` | 信号结果追踪 | 每日 |
| `event_signals` | 盘后AI事件信号（新闻+内幕交易） | 每日 |

### 内幕交易（SEC EDGAR Form 4）
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `insider_transactions` | 清洗后的 Form 4 交易记录（原始层） | 每日（10:05 NZT） |

> **insider_transactions 关键字段**：accession_number、filing_date、transaction_date、ticker、insider_name、title_normalized、is_officer、is_director、transaction_code（P/S）、notional_value、pct_of_holdings

### 知识库
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `knowledge_entries` | 知识库条目 | 持续 |
| `knowledge_vectors` | pgvector Embedding | 持续 |

### 新闻/事件
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `news_events` | 新闻事件 | 每日 |
| `geopolitical_events` | 地缘政治 | 每日 |
| `earnings_calendar` | 财报日历 | 每日 |

### 用户/订阅
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `subscribers` | Newsletter订阅者 | 用户操作 |
| `stripe_customers` | Stripe客户 | 支付时 |

### 系统
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `scheduler_logs` | 任务执行日志 | 每次任务 |
| `ohlcv_cache` | 行情缓存 | 每日 |
| `exit_scorer_signals` | ML出场评分信号 | 每日 |
| `universe_snapshots` | 动态选股池快照 | 每周 |

---

## 数据流向

```
Massive API（统一数据源）
├── 日行情 → ohlcv_cache → rotation_service → 评分
├── 基本面 → multi_factor_scorer → 基本面因子
├── 财报日历 → earnings_calendar → event_driven_service → 事件信号
├── EPS历史 → event_driven_service → 财报超预期判断
├── 公司概况 → multi_factor_scorer → PE/Beta/分析师目标价
├── TTM比率 → multi_factor_scorer → ROE/毛利率/PEG
└── 新闻 → news_scanner_service → DeepSeek分类 → event_signals

SEC EDGAR API（免费，max 10 req/sec）
├── company_tickers.json → CIK缓存（24h TTL）
├── submissions/{CIK}.json → 找近2天 Form 4 申报列表
├── Archives/.../*.xml → Form 4 XML下载解析
└── 清洗（仅P/S代码 + 职员/董事 + 名义金额>$50K）
    → insider_transactions（UPSERT，去重）
    → 聚合5天集群 → event_signals（集群买/CEO买/大额买/集群卖/大额卖）

Tiger Broker API
├── 订单同步 → orders/positions 表
├── 实时行情 → WebSocket → 前端
└── 成交确认 → trade_history

OpenAI API
└── text-embedding-3-small → knowledge_vectors (pgvector)

DeepSeek API
├── 新闻分类 → news_events.event_type
└── 飞书聊天 → 实时回复

Claude API
└── Newsletter内容 → 周报HTML → Resend → 订阅者邮箱
```

---

## 缓存架构

| 层 | 实现 | TTL | 用途 |
|---|------|-----|------|
| L1 内存缓存 | Python dict | 5-15分钟 | 行情/评分热数据 |
| L1b CIK映射缓存 | Python dict | 24小时 | EDGAR ticker→CIK |
| L2 数据库缓存 | `ohlcv_cache` | 24小时 | 历史行情 |
| L3 预计算缓存 | `backtest_results` | 1周 | 回测结果 |

---

## 环境变量

| 变量 | 用途 |
|------|------|
| `SUPABASE_URL` | 数据库连接 |
| `SUPABASE_KEY` | Supabase service key |
| `MASSIVE_API_KEY` | 行情/基本面/新闻 |
| `TIGER_*` | Tiger Broker SDK |
| `DEEPSEEK_API_KEY` | AI分类 |
| `OPENAI_API_KEY` | Embedding |
| `ANTHROPIC_API_KEY` | Claude Newsletter |
| `RESEND_API_KEY` | 邮件发送 |
| `STRIPE_SECRET_KEY` | 支付 |
| `FEISHU_*` | 飞书机器人 |

> SEC EDGAR 无需 API Key，仅需在 User-Agent 头中附上联系邮箱（已硬编码）。
"""

# ============================================================
# 3. Backend-Services.md
# ============================================================
BACKEND_SERVICES = """---
name: 后端服务清单
description: 全部后端服务模块、调用关系、文件位置、状态
type: reference
created: 2026-03-19
updated: 2026-03-21
tags: [backend, services, FastAPI, scheduler, active]
---

# 后端服务清单

## 服务架构

```
app/
├── main.py              # FastAPI 应用入口（~1100行）
├── scheduler.py         # APScheduler 32个定时任务（~650行）
├── config/
│   ├── settings.py      # Pydantic Settings（API Keys/环境变量）
│   ├── rotation_watchlist.py  # 选股池+回测参数（~730行）
│   ├── sp100_watchlist.py     # S&P 100 成分股
│   ├── pharma_watchlist.py    # 制药监视列表
│   └── geopolitical_watchlist.py  # 地缘政治关键词
├── routers/             # 9个路由器 → 145+条路由
│   ├── web.py           # 主Web路由（5203行，40+ HTMX + 页面 + API）
│   ├── rotation.py      # 轮动API
│   ├── signals.py       # 信号API
│   ├── knowledge.py     # 知识库API
│   ├── payments.py      # Stripe支付
│   ├── social.py        # 社交工具
│   ├── risk.py          # 风控API
│   ├── websocket.py     # WebSocket行情
│   └── compute.py       # Admin计算工作台
└── services/            # 29个服务模块
```

## 服务依赖关系

```
scheduler.py
├── market_service.py ─────→ massive_client.py
├── regime_monitor.py ─────→ rotation_service.py → notification_service.py
├── signal_service.py ─────→ multi_factor_scorer.py → massive_client.py
│                           → mean_reversion_service.py
│                           → event_driven_service.py → massive_client.py
├── rotation_service.py ───→ multi_factor_scorer.py → knowledge_service.py
│                           → portfolio_manager.py
├── order_service.py ──────→ risk_service.py → Tiger Broker SDK
├── news_service.py ───────→ ai_service.py (DeepSeek)
│                           → knowledge_service.py → embedding_service.py (OpenAI)
├── knowledge_collectors.py → knowledge_service.py
├── notification_service.py → Feishu Webhook / Twilio
├── news_scanner_service.py → massive_client.py → ai_service.py → event_signals表
├── sec_edgar_client.py ───→ SEC EDGAR API（免费）
│                           → insider_transactions表（Form 4 清洗原始层）
│                           → event_signals表（集群买/CEO买/大额买/集群卖）
└── newsletter (scripts/) ──→ ai_content_generator.py (Claude/DeepSeek)
                             → renderer.py → sender.py (Resend)
```

## 各服务详情

### 核心交易引擎

| 服务 | 文件 | 行数 | 关键函数 | 状态 |
|------|------|------|---------|------|
| 轮动引擎 | `rotation_service.py` | ~3500 | `run_rotation()`, `_detect_regime()`, `run_daily_entry_check()` | 运行中 |
| 多因子打分+ML重排 | `multi_factor_scorer.py` / `ml_scorer.py` | ~600 | `compute_multi_factor_score()`, XGBRanker重排 | 运行中 |
| 信号引擎 | `signal_service.py` | ~800 | `run_signal_generation()`, `run_confirmation_engine()` | 运行中 |
| 均值回归 | `mean_reversion_service.py` | ~610 | `scan_live_signals()` | 运行中 |
| 事件驱动 | `event_driven_service.py` | ~690 | `scan_live_events()` (bear/choppy门控) | 运行中 |
| 组合管理 | `portfolio_manager.py` | ~580 | `get_strategy_allocations()` | 运行中 |
| Regime监控 | `regime_monitor.py` | ~130 | `check_regime_and_alert()` | 运行中 |
| ML出场评分 | `exit_scorer.py` | — | Phase 1 信号采集（XGBoost，不执行交易） | 运行中 |
| AI事件信号 C2 | `news_scanner_service.py` | ~350 | `run_daily_scan()` (C2面板) | 运行中 |
| **内幕交易信号 C4** | **`sec_edgar_client.py`** | **~450** | **`run_insider_scan()`** | **运行中** |

### 交易执行

| 服务 | 文件 | 关键函数 | 状态 |
|------|------|---------|------|
| 订单管理 | `order_service.py` | `sync_tiger_orders()`, `run_intraday_trailing_stop()` | 运行中 |
| 风控引擎 | `risk_service.py` | `RiskEngine.check_all_risk_limits()` | 运行中 |

### 数据管线

| 服务 | 文件 | 关键函数 | 状态 |
|------|------|---------|------|
| 行情获取 | `market_service.py` | `run_market_data_fetch()` | 运行中 |
| Massive客户端 | `massive_client.py` | 行情/基本面/财报/新闻一体化 | 运行中 |
| **SEC EDGAR客户端** | **`sec_edgar_client.py`** | **`run_insider_scan()`** | **运行中** |
| WebSocket行情 | `websocket_service.py` | `start_websocket_client()` | 运行中 |

### AI / 知识库

| 服务 | 文件 | 关键函数 | 状态 |
|------|------|---------|------|
| AI分类/聊天 | `ai_service.py` | `run_ai_classification()`, `AIChatService` | 运行中 |
| 向量Embedding | `embedding_service.py` | `get_embedding()` | 运行中 |
| RAG知识库 | `knowledge_service.py` | `feed()`, `search()` | 运行中 |
| 数据收集器 | `knowledge_collectors.py` | 8个Collector类（含AISentiment/ETFFlow/EarningsReport/13F） | 运行中 |

### 通知 / 集成

| 服务 | 文件 | 关键函数 | 状态 |
|------|------|---------|------|
| 通知发送 | `notification_service.py` | `notify_regime_change()`, `notify_signals_ready()` | 运行中 |
| 飞书事件 | `feishu_event_service.py` | `start_feishu_event_client()` | 运行中 |
| 飞书API | `feishu_api_client.py` | Feishu Open API | 运行中 |
| 飞书长连接(备选) | `feishu_long_connection.py` | — | 休眠 |

### 数据库

| 服务 | 文件 | 说明 | 状态 |
|------|------|------|------|
| DB ORM | `db_service.py` | EventService, SignalService | 运行中 |

### 动态选股池

| 服务 | 文件 | 说明 | 状态 |
|------|------|------|------|
| 动态选股池 | `universe_service.py` | 1578只ticker，USE_DYNAMIC_UNIVERSE=True，每周六09:00刷新 | 运行中 |

## 中间件栈

| 中间件 | 说明 | 文件位置 |
|--------|------|---------|
| Rate Limiter | API速率限制 | main.py:232 |
| CORS | 跨域访问 | main.py:260 |
| Security Headers | X-Frame等安全头 | main.py:280 |
| Dashboard Auth | 仪表板登录认证 | main.py:310 |
| Request Logger | 请求日志 | main.py:360 |

---

## sec_edgar_client.py 设计说明

### 完整处理链

```
1. _ensure_cik_map()        # 下载 company_tickers.json → ticker→CIK（24h缓存）
2. fetch_form4_for_ticker() # submissions JSON → 找近2天 Form 4 申报
3. _fetch_form4_xml()       # 下载 XML，验证 ownershipDocument 格式
4. parse_form4_xml()        # 解析 nonDerivativeTransaction（跳过衍生品）
5. clean_transactions()     # is_officer/is_director + 名义金额 >= $50K
6. _upsert_transactions()   # UPSERT insider_transactions（4字段复合唯一键）
7. _compute_signals_for_ticker() # 聚合近5天 → 信号分级
8. _save_signals()          # UPSERT event_signals（url去重）
```

### 清洗规则

| 过滤层 | 规则 |
|---|---|
| 交易代码 | 只保留 P（公开市场买）/ S（公开市场卖），排除 M/A/G/F 等 |
| 角色 | is_officer=True 或 is_director=True（排除纯大股东） |
| 名义金额 | shares × price >= $50,000 |
| 价格 | price > 0（排除赠与/计划等无价格申报） |

### 信号规格

| 事件类型 | 触发条件 | 强度 | 方向 |
|---|---|---|---|
| insider_cluster_buy | 3+内幕人5天内买入 | 0.90 | bullish |
| insider_ceo_buy | CEO/CFO 买入 >= $100K | 0.85 | bullish |
| insider_large_buy | 任意内幕人买入 >= $500K | 0.80 | bullish |
| insider_director_buy | 通过门槛的任意买入 | 0.60 | bullish |
| insider_cluster_sell | 3+内幕人5天内卖出 | 0.40 | bearish |
| insider_large_sell | C-Suite 卖出 >= $2M | 0.35 | bearish |
"""

# ============================================================
# 4. Projects/C4-EDGAR-Insider-Signal.md
# ============================================================
C4_DOC = """---
name: C4 EDGAR内幕信号
description: SEC EDGAR Form 4 内幕交易信号服务：数据清洗、聚合规则、调度配置
type: project
created: 2026-03-21
updated: 2026-03-21
tags: [C4, insider, SEC, EDGAR, Form4, event_signals, active]
---

# C4：SEC EDGAR Form 4 内幕交易信号

## 背景

SEC EDGAR 是美国证券交易委员会的官方申报系统。上市公司内幕人士（CEO/CFO/董事等）在进行自家公司股票买卖后，必须在 T+2 工作日内提交 Form 4 申报。这是**完全免费**的结构化数据源，信号价值明显优于新闻情绪，尤其是**集群买入**和 **CEO 买入**。

## 信号价值

| 信号类型 | 学术研究平均超额收益（1个月） | 可靠性 |
|---|---|---|
| 集群买入（3+内幕人） | +4.2% vs 基准 | 高（多人一致，排除噪音） |
| CEO/CFO 公开市场买入 | +3.1% vs 基准 | 高（个人资金投入，非福利性） |
| 大额单笔买入（>$500K） | +2.5% vs 基准 | 中高 |
| 集群卖出 | -1.8% vs 基准 | 低（原因多样） |

买入信号远优于卖出信号。

## 文件清单

| 文件 | 说明 |
|---|---|
| `app/services/sec_edgar_client.py` | 主服务（~450行），含 CIK 缓存/XML解析/清洗/信号聚合 |
| `database/create_insider_transactions.sql` | DB 迁移脚本 |
| `app/scheduler.py` → `_run_insider_scan()` | 调度入口，每日 Tue-Sat 10:05 NZT |

## EDGAR API

| 端点 | 用途 |
|---|---|
| `https://www.sec.gov/files/company_tickers.json` | Ticker→CIK 映射（24h缓存） |
| `https://data.sec.gov/submissions/CIK{cik:010d}.json` | 公司申报列表 |
| `https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}` | Form 4 XML |

速率限制：Semaphore(5) + 0.12s delay，满足 EDGAR 官方 max 10 req/sec 要求。

## 数据清洗流程

```
Form 4 XML
    ↓  parse_form4_xml()
    ├── 只处理 nonDerivativeTransaction（跳过衍生品/期权行权）
    ├── transaction_code 必须是 P 或 S
    ├── shares > 0 且 price > 0（排除无价格申报）
    └── notional = shares × price >= $50,000
    ↓  clean_transactions()
    ├── is_officer=True 或 is_director=True
    └── notional >= $50,000（双重确认）
    ↓
insider_transactions（UPSERT 去重）
    ↓  _compute_signals_for_ticker()  ← 聚合近5天
    ↓
event_signals（与 C2 新闻信号共表，source='SEC EDGAR Form 4'）
```

## 信号分级

### 买入（每只 ticker 只取最高优先级）

| 优先 | 事件类型 | 触发条件 | 强度 |
|---|---|---|---|
| 1 | `insider_cluster_buy` | 5天内 3+ 不同内幕人买入 | **0.90** |
| 2 | `insider_ceo_buy` | CEO 或 CFO 买入 >= $100K | **0.85** |
| 3 | `insider_large_buy` | 任意内幕人买入 >= $500K | **0.80** |
| 4 | `insider_director_buy` | 通过门槛的任意买入 | **0.60** |

### 卖出（独立，不与买入互斥）

| 事件类型 | 触发条件 | 强度 |
|---|---|---|
| `insider_cluster_sell` | 5天内 3+ 不同内幕人卖出 | **0.40** |
| `insider_large_sell` | C-Suite 卖出 >= $2M | **0.35** |

## 职位规范化

| 原文关键词 | 标签 | 影响 |
|---|---|---|
| chief executive / ceo | ceo | 触发 insider_ceo_buy |
| chief financial / cfo | cfo | 触发 insider_ceo_buy |
| chief operating / coo | coo | 触发 insider_large_sell 门控 |
| president / chairman | president/chairman | 触发 insider_large_sell 门控 |
| director | director | 计入集群统计 |
| officer | officer | 计入集群统计 |

## 数据库表 insider_transactions

| 字段 | 类型 | 说明 |
|---|---|---|
| accession_number | TEXT | EDGAR 申报号 |
| filing_date | DATE | 申报日期 |
| transaction_date | DATE | 实际交易日 |
| ticker | TEXT | 股票代码 |
| insider_name | TEXT | 姓名（大写规范化） |
| title_normalized | TEXT | 职位标签 |
| is_officer / is_director | BOOLEAN | 角色 |
| transaction_code | TEXT | P 或 S |
| notional_value | FLOAT | 名义金额 |
| pct_of_holdings | FLOAT | 占总持仓% |

复合唯一键：`(accession_number, insider_name, transaction_code, transaction_date)`

## 与其他系统集成

- **event_signals 表**：与 C2 新闻信号共表，按 `source='SEC EDGAR Form 4'` 和 `event_type='insider_*'` 区分，Dashboard 面板直接可见
- **当前仓位注入**：`_run_insider_scan()` 自动注入 `positions` 表中的开仓股票，优先保障持仓股覆盖

## 后续扩展方向

- [ ] 高强度信号（>= 0.80）触发飞书即时推送
- [ ] 8-K 事件扫描（并购/CEO离职/重大合同）
- [ ] insider_cluster_buy 回测验证（在宝典V4选股池中的预测效果）
- [ ] Newsletter 付费版周报加入"本周内幕买入亮点"板块

## 关联文档

- [[Scheduler-Jobs]] — Job 5c 调度配置
- [[Data-Infrastructure]] — insider_transactions 表 + EDGAR 数据流
- [[Backend-Services]] — sec_edgar_client.py 服务详情
- [[C2-AI-Event-Signals]] — 同类事件信号（新闻驱动）
"""

put('docs/Scheduler-Jobs.md',                   SCHEDULER_JOBS)
put('docs/Data-Infrastructure.md',              DATA_INFRA)
put('docs/Backend-Services.md',                 BACKEND_SERVICES)
put('docs/Projects/C4-EDGAR-Insider-Signal.md', C4_DOC)
