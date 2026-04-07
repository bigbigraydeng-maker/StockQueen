---
name: 选股池与标的分类
description: 完整股票池定义：进攻型ETF/防守型ETF/反向ETF/大盘股/中盘股 + Regime筛选规则
type: reference
created: 2026-03-19
updated: 2026-03-23
tags: [strategy, stock-pool, universe, ETF, large-cap, regime-filter]
---

# 选股池与标的分类

## 概览

StockQueen 将全部标的分为 **5 大类**，由 Regime 决定哪些类别参与选股。

**文件**: `app/config/rotation_watchlist.py`

---

## 1. 标的分类

### 1.1 进攻型 ETF（14只）

| 类别 | 标的 |
|------|------|
| 指数 | SPY, QQQ, IWM |
| 板块 | XLK, XLF, XLE, XLV, XLI, XLC, SOXX, IBB, ARKK |
| 国际 | VWO, EFA |

### 1.2 防守型 ETF（3只）

| 标的 | 说明 |
|------|------|
| TLT | 美国长期国债 |
| SHY | 短期国债（现金替代） |
| GLD | 黄金 |

### 1.3 反向 ETF（4只，仅 Bear regime）

| 标的 | 说明 |
|------|------|
| SH | Short S&P 500 |
| PSQ | Short Nasdaq 100 |
| RWM | Short Russell 2000 |
| DOG | Short Dow 30 |

### 1.4 大盘蓝筹股（~100只）

全部为 **2015 年前上市**的成熟公司，数据完整。

| 板块 | 标的 |
|------|------|
| Mega-Tech (7) | AAPL, MSFT, NVDA, AMZN, META, GOOG, TSLA |
| 金融 (14) | JPM, GS, V, MA, BLK, BAC, WFC, C, SCHW, MS, AIG, MET, PRU, TRV |
| 医疗 (7) | UNH, LLY, ABBV, TMO, JNJ, PFE, MRK |
| 工业 (9) | CAT, DE, HON, UPS, RTX, GE, BA, LMT, MMM |
| 消费 (8) | COST, WMT, HD, MCD, NKE, SBUX, PG, KO |
| 能源 (5) | XOM, CVX, COP, EOG, SLB |
| 材料 (3) | LIN, APD, FCX |
| 公用事业 (3) | NEE, DUK, SO |
| 通信 (4) | DIS, CMCSA, NFLX, T |
| 房地产 (2) | AMT, PLD |

**大盘股使用专用因子权重**（见 [[11-Multi-Factor-Scoring]]）

### 1.5 中盘股

S&P 100 成分股（排除大盘池已有的标的），从 `sp100_watchlist.py` 加载。

---

## 2. Regime 筛选规则

| Regime | 可选标的 | 排除 |
|--------|---------|------|
| **Strong Bull** | 进攻ETF + 大盘 + 中盘 | 防守ETF, 反向ETF |
| **Bull** | 进攻ETF + 大盘 + 中盘 | 防守ETF, 反向ETF |
| **Choppy** | 防守ETF + 进攻ETF + 大盘 | 中盘, 反向ETF |
| **Bear** | 防守ETF + 反向ETF | 进攻ETF, 大盘, 中盘 |

**文件**: `app/services/rotation_service.py:1878-1896`

---

## 3. 流动性与质量过滤

| 过滤条件 | 阈值 | 说明 |
|---------|------|------|
| 20日均成交量 | ≥ 500,000 | 回测和实盘通用 |
| 相对强度 | > -2% vs SPY | 排除严重跑输大盘的标的 |
| 板块集中度 | ≤ 2只/板块 | 避免过度集中 |
| 最低评分 | > 0.0 | 不选负分标的 |

---

## 4. 选股流程

```
1. Regime 决定可选标的类别
2. 全部候选标的 → 多因子评分 [-10, +10]
3. 过滤: RS > -2%, Volume > 50万, Score > 0
4. 排序: 按总分降序
5. 板块集中度限制: 每板块 ≤ 2只
6. 选 Top 6
7. 权重分配: 按评分加权（SCORE_WEIGHTED_ALLOC=True）
```

---

## 5. V4 vs V5 股票池对比

| 属性 | V4 | V5 |
|------|-----|-----|
| 来源 | 手动精选 | AV LISTING_STATUS 自动扫描 |
| 大盘蓝筹 | ~100 手选 | 同（ETF/大盘定义保留） |
| 中盘成长 | ~120 手选 | 动态扫描（Quality Gate 后 ~1,127 只） |
| 总数 | ~220 | 1,688（Quality Gate 前）/ 1,127（Quality Gate 后） |
| 动态过滤 | 无 | 按日期过滤 IPO/退市 |
| 幸存者偏差 | **有** | 大幅缓解 |
| 缓存 | 无 | `.cache/universe/universe_latest.json` |
