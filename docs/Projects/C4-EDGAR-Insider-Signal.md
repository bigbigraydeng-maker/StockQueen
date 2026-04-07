---
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
