---
name: 多因子打分系统详解
description: 9因子评分引擎完整文档：权重/公式/Regime适配/大盘股调整/权重归一化
type: reference
created: 2026-03-19
updated: 2026-03-22
tags: [strategy, multi-factor, scoring, momentum, technical, fundamental]
---

# 多因子打分系统详解

## 概览

StockQueen 使用 **9 因子加权评分** 体系对候选标的打分，总分范围 [-10, +10]。

**文件**: `app/services/multi_factor_scorer.py`

---

## 1. 因子权重

### 1.1 默认权重（中盘股/ETF）— IC验证后 (2026-03-21)

| # | 因子 | 权重 | 旧权重 | 分类 | 数据来源 | IC依据 |
|---|------|------|--------|------|---------|--------|
| 1 | **Momentum** 动量 | 20% | ~~25%~~ | 始终可用 | 价格历史 | IC弱有效，稳定 |
| 2 | **Technical** 技术指标 | 5% | ~~15%~~ | 始终可用 | 价格/成交量 | IC全负↓↓ |
| 3 | **Trend** 趋势 | 10% | 10% | 始终可用 | 均线系统 | IC弱正 |
| 4 | **Relative Strength** 相对强度 | 8% | ~~10%~~ | 始终可用 | vs SPY | IC不显著 |
| 5 | **Fundamental** 基本面 | 12% | ~~15%~~ | 数据依赖 | Massive（公司概况+TTM比率） | 无法IC验证 |
| 6 | **Earnings** 盈利质量 | 22% | ~~10%~~ | 数据依赖 | Massive（财报历史） | t=5.21最强↑↑ |
| 7 | **Cashflow** 现金流 | 13% | ~~5%~~ | 数据依赖 | Massive（现金流表） | IC=+0.062最高↑↑ |
| 8 | **Sentiment** AI情绪 | 5% | 5% | 数据依赖 | 知识库RAG | 维持 |
| 9 | **Sector Wind** 板块顺风 | 5% | 5% | 数据依赖 | 板块收益 | 维持 |

### 1.2 大盘股专用权重

大盘蓝筹股（AAPL, MSFT 等 ~100只）使用优化权重：

| 因子 | 中盘默认 | 大盘股 | 调整原因 |
|------|----------|--------|---------|
| Momentum | 20% | **15%** | 大盘动量幅度小，信号弱 |
| Technical | 5% | **8%** | 机构驱动，技术面略正（中盘反而负） |
| Relative Strength | 8% | **20%** | 龙头相对强度是最有效选股因子 |
| Fundamental | 12% | **22%** | 大盘基本面数据完整可靠 |

---

## 2. 各因子评分公式

### 2.1 Momentum 动量因子 [-1, +1] — 权重 20%

**Regime 自适应时间窗口权重：**

| Regime | 1周 | 1月 | 3月 | 偏向 |
|--------|-----|-----|-----|------|
| Strong Bull | 15% | 35% | **50%** | 重视长期趋势 |
| Bull | 20% | 40% | 40% | 均衡 |
| Choppy | **35%** | 40% | 25% | 偏向短期反转 |
| Bear | **40%** | 40% | 20% | 快速响应 |

```
raw_momentum = w1w × ret_1w + w1m × ret_1m + w3m × ret_3m
score = raw_momentum - 0.50 × annualized_volatility(22d)
normalized = clamp(score × 3.0, -1, +1)
```

**波动率惩罚**: 0.50（高波动个股自动降分）

### 2.2 Technical 技术指标因子 [-1, +1] — 权重 5%

5个技术信号投票（每个 ±1），合计后归一化：

| 指标 | 多头(+1) | 空头(-1) |
|------|---------|---------|
| RSI(14) | < 30 超卖 | > 70 超买 |
| MACD(12,26,9) | 柱状图 > 0 | 柱状图 < 0 |
| Bollinger(20,2σ) | 位置 < 0.2 | 位置 > 0.8 |
| OBV(20) | 趋势上升 | 趋势下降 |
| ADX(14) | > 25 时放大趋势方向 | |

```
net = long_votes - short_votes
normalized = clamp(net / 3.0, -1, +1)
```

### 2.3 Trend 趋势因子 [0, +1]

渐进式均线奖励（累加制）：

| 条件 | 奖分 |
|------|------|
| Close > MA10 | +0.17 |
| Close > MA20 | +0.33 |
| Close > MA50 | +0.33 |
| MA20 上升中 | +0.17 |
| **满分** | **1.00** |

### 2.4 Relative Strength 相对强度 [-1, +1] — 权重 8%

```
alpha = ticker_21d_return - SPY_21d_return
normalized = clamp(alpha × 10, -1, +1)
```
±10% 相对表现 → ±1.0 满分

### 2.5 Fundamental 基本面质量 [-1, +1] — 权重 12%

| 指标 | 优秀 | 良好 | 差 |
|------|------|------|-----|
| PEG < 1.0 | +0.30 | +0.15 (PEG<1.5) | -0.20 (PEG>3) |
| ROE > 20% | +0.25 | +0.15 (>15%) | -0.15 (负) |
| 营收增长 > 30% | +0.25 | +0.10 (>15%) | -0.20 (负增长) |
| 分析师目标 > +20% | +0.20 | — | -0.15 (<-10%) |
| 利润率 > 20% | +0.10 | — | -0.10 (负) |

> 数据来源：Massive 公司概况（profile）+ TTM财务比率（ratios-ttm）

### 2.6 Earnings 盈利质量 [-1, +1] — 权重 22%

| 指标 | 优秀 | 良好 | 差 |
|------|------|------|-----|
| Beat率 ≥ 75% | +0.40 | +0.15 (≥50%) | -0.30 (<25%) |
| 最新Surprise > 10% | +0.30 | +0.15 (>5%) | -0.30 (<-10%) |
| EPS增长 > 20% | +0.20 | — | -0.15 (<-10%) |

> 数据来源：Massive 财报历史（earnings）

### 2.7 Cashflow 现金流 [-1, +1] — 权重 13%

| 指标 | 加分 | 扣分 |
|------|------|------|
| FCF > 0 | +0.30 | -0.30 |
| 经营现金流 > 0 | +0.15 | -0.30 |
| FCF增长 > 20% | +0.25 | -0.15 (<-20%) |
| 连续4季FCF为正 | +0.20 | — |

> 数据来源：Massive 现金流表（cash-flow-statement）

### 2.8 Sentiment AI情绪 [-1, +1]

直接传递知识库 RAG 系统的 AI 情绪评分。来源：
- DeepSeek API 新闻分类
- OpenAI Embedding 语义搜索
- 知识库聚合评分

### 2.9 Sector Wind 板块顺风 [-1, +1]

```
sector_return = 该板块过去1月收益
normalized = clamp(sector_return × 20, -1, +1)
```
±5% 月收益 → ±1.0 满分

---

## 3. 权重自动归一化

当某些因子数据不可用时（如 ETF 没有基本面数据），系统自动重分配权重：

```
示例：ETF 缺失 fundamental + earnings + cashflow (权重 0.12+0.22+0.13=0.47)
可用权重: 0.20 + 0.05 + 0.10 + 0.08 + 0.05 + 0.05 = 0.53
归一化: momentum = 0.20/0.53 = 0.377, trend = 0.10/0.53 = 0.189 ...
```

确保总权重始终 = 100%

---

## 4. 最终评分

```
total = Σ (factor_score × normalized_weight × 10)
范围: [-10, +10]
```

**选股流程**: Score → RS过滤(>-2%) → 流动性过滤(>50万) → 板块集中度(≤2) → Top 6

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `app/services/multi_factor_scorer.py` | 核心评分引擎（~600行） |
| `app/services/massive_client.py` | Massive 数据客户端（行情+基本面+财报） |
| `app/config/rotation_watchlist.py` | 选股参数和阈值 |
| `app/services/rotation_service.py` | 排名和选股逻辑 |
| `app/services/knowledge_service.py` | RAG情绪/基本面数据源 |
