---
name: ML Feature Engineering
description: 22维特征定义、攻击型特征设计
created: 2026-03-19
updated: 2026-03-19
tags: [ml, features, xgboost, feature-engineering]
---

# ML 特征工程

## 特征向量（22维）

所有特征从现有 `compute_multi_factor_score()` 输出 + OHLCV 数据提取，**无需额外API调用**。

ML-V2 新增 5 个攻击型特征（#18-22），专门用于识别高增长突破票。

---

## 基础特征（17维，来自评分引擎）

### 动量特征（5个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 1 | ret_1w | momentum.ret_1w | [-1, +1] | 5日收益 |
| 2 | ret_1m | momentum.ret_1m | [-1, +1] | 21日收益 |
| 3 | ret_3m | momentum.ret_3m | [-1, +1] | 63日收益 |
| 4 | volatility | momentum.vol | [0, +inf) | 21日年化波动率 |
| 5 | momentum_score | momentum.score | [-1, +1] | 加权动量综合分 |

### 技术特征（5个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 6 | rsi | technical.rsi | [0, 100] | RSI(14) |
| 7 | macd_hist | technical.macd_hist | (-inf, +inf) | MACD 柱状图 |
| 8 | bb_pos | technical.bb_pos | [0, 1] | 布林带位置 |
| 9 | adx | technical.adx | [0, 100] | ADX(14) 趋势强度 |
| 10 | technical_score | technical.score | [-1, +1] | 技术综合分 |

### 趋势与相对强度（2个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 11 | trend_score | trend.score | [0, 1] | 渐进式均线对齐 |
| 12 | rs_score | relative_strength.score | [-1, +1] | vs SPY 超额收益 |

### Regime 上下文（4个，one-hot）

| # | 名称 | 值 | 说明 |
|---|------|------|------|
| 13 | regime_strong_bull | 0/1 | 强牛 |
| 14 | regime_bull | 0/1 | 正常牛 |
| 15 | regime_choppy | 0/1 | 震荡 |
| 16 | regime_bear | 0/1 | 熊市 |

### 综合分（1个）

| # | 名称 | 来源 | 范围 | 说明 |
|---|------|------|------|------|
| 17 | rule_score | total_score | [-10, +10] | 9因子加权总分 |

---

## 攻击型特征（5维，ML-V2 新增）

这些特征专门设计来识别「即将爆发」的高增长票。

| # | 名称 | 计算方式 | 范围 | 攻击含义 |
|---|------|---------|------|---------|
| 18 | momentum_accel | ret_1w / abs(ret_1m) | [-5, +5] | **动量加速** — 近期加速上涨 = 爆发前兆 |
| 19 | volume_surge | avg_vol_5d / avg_vol_20d | [0, 5] | **放量突破** — 资金正在涌入 |
| 20 | new_high_pct | close / 52周最高价 | [0, 1] | **新高逼近** — 接近1.0 = 即将突破 |
| 21 | upside_vol | std(正收益日) * sqrt(252) | [0, +inf) | **上行波动** — 好的波动（涨得猛）|
| 22 | drawdown_from_peak | (close - peak) / peak | [-1, 0] | **浅回撤** — 接近0 = 底部扎实 |

### 攻击特征详解

**动量加速 momentum_accel**

```
当 ret_1w=5%, ret_1m=8% -> accel = 0.05/0.08 = 0.625
当 ret_1w=5%, ret_1m=3% -> accel = 0.05/0.03 = 1.667（加速中！）
```

高值说明最近一周加速上涨，可能正在突破关键位。

**放量突破 volume_surge**

```
avg_vol_5d = 200万股, avg_vol_20d = 100万股 -> surge = 2.0
```

突然放量 = 机构资金入场，突破信号。

**新高逼近 new_high_pct**

```
close = 98, 52w_high = 100 -> pct = 0.98
```

接近 1.0 说明即将创新高，阻力小，上涨空间大。

**上行波动 upside_vol**

只统计正收益日的波动率。高 upside_vol = 涨的时候涨得猛（好的波动），
与 volatility（所有日的波动率，包含暴跌）形成对比。

**浅回撤 drawdown_from_peak**

```
close = 95, 63d_peak = 100 -> dd = -0.05（仅回撤5%）
close = 70, 63d_peak = 100 -> dd = -0.30（回撤30%，趋势可能已破）
```

接近0 = 强势票，仅轻微回调。

---

## 设计取舍

### 为什么选这些特征

1. **零额外API调用**：全部从现有 OHLCV + 评分输出提取
2. **无前视风险**：特征只用截至当日的历史数据
3. **Regime 作为特征**：让模型在不同市场环境下学到不同的排序偏好
4. **规则分数包含**：给 ML 访问第一层综合分作为 baseline

### 刻意排除的特征

- 基本面数据（PEG/ROE）— 回测中不可用，会造成前视偏差
- 情绪数据 — 无历史归档
- 板块因子 — 太稀疏
- 盈利数据 — 已包含在 rule_score 中

### 未来可扩展

- 板块 one-hot 编码
- 收益率在全池的百分位排名
- 价格距 MA200 的距离
- 换手率变化

---

## 提取管道

```python
from app.services.ml_scorer import extract_features

# 输入：评分引擎输出 + OHLCV 数据
scorer_result = compute_multi_factor_score(closes, volumes, ...)
features = extract_features(
    scorer_result, regime="bull",
    closes=closes, volumes=volumes, highs=highs
)
# 输出：numpy array shape (22,)
```

## 相关文档

- [[ML/00-Index]] — ML 文档索引
- [[ML/01-Architecture]] — 架构设计
- [[ML/02-Training-Validation]] — 训练与验证
- [[Strategy/11-Multi-Factor-Scoring]] — 第一层评分系统（特征来源）
