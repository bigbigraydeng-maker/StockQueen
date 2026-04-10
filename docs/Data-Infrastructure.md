---
name: 数据基础设施
description: Supabase数据库表、外部API、缓存层、数据流向
type: reference
created: 2026-03-19
updated: 2026-04-02
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

### 盘中动能（铃铛 / 多因子）
| 表 | 说明 | 写入频率 |
|---|------|---------|
| `intraday_scores` | 每轮每票因子明细（Top50 落库） | 每 30min（交易时段） |
| `intraday_rounds` | 每轮元数据（轮次、时间、本批写入条数、Top5 JSON） | 同上 |
| `intraday_momentum_daily` | **按交易日 + ticker 聚合**：最新/最佳/最差名次、`rank_history`（最近若干轮） | 同上（upsert） |

> 迁移文件：`supabase/migrations/20260402120000_intraday_momentum_tracking.sql`（仅新增表）。  
> 写入逻辑：`app/services/intraday_momentum_store.py`，在 `intraday_scores` 插入成功后调用。  
> 股票池分层（仅评分、禁止自动开仓）：`app/config/intraday_universe.py` 中 `INTRADAY_AUTO_ENTRY_DENY`。

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
