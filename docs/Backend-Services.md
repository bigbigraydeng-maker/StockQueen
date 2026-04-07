---
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
