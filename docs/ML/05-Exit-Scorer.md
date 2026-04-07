---
name: ML Exit Scorer — Tranche B 出场优化模型
description: 预测当前持仓3日后利润是否缩水，驱动 Tranche B 提前出场锁定利润
created: 2026-03-20
updated: 2026-03-20
tags: [ml, exit-scoring, profit-locking, xgboost, tranche-b]
---

# ML Exit Scorer

## 核心定位

> **现有 ML Ranker 负责"选谁入场"，Exit Scorer 负责"什么时候出场"。**

两个模型职责完全分离，互不干扰：

| 模型 | 问题 | 作用 |
|------|------|------|
| ML Ranker（现有，V3A） | 哪只股票未来涨幅最大？ | 入场排序 |
| **ML Exit Scorer（新建）** | 这笔持仓3日后利润会缩水吗？ | Tranche B 出场信号 |

---

## 预测目标

这是一个**持仓收益衰减预测**问题：

```python
# 持有第 N 天，计算未来3日涨跌幅
forward_3d_return = (price_t+3 - price_t) / price_t

# 对反向 ETF（RWM/DOG/PSQ/SH 等）：
# forward_3d_return < -1.0% → 利润缩水 → label = 1（出场）
# forward_3d_return >= -1.0%              → label = 0（继续持）

# 对防御 ETF（SHY/TLT/GLD 等）：
# 波动率更低，阈值放宽至 -0.3%
```

---

## 特征设计（10维）

| 特征 | 计算方式 | 直觉含义 |
|------|---------|---------|
| `unrealized_pnl_pct` | `(price - cost) / cost` | 当前账面盈利% |
| `pnl_peak_pct` | 持仓期间最高账面盈利% | 峰值有多高 |
| `pnl_drawdown_from_peak` | `(peak - current) / cost` | **核心特征**：从峰值回撤多少% |
| `days_held` | 持仓天数 | 持仓时间 |
| `rsi_14` | 标的 RSI(14) | 超买/超卖状态 |
| `atr_ratio` | `(price - atr_stop) / (atr * 1.5)` | 距 ATR 止损的安全距离 |
| `price_vs_ma5` | `price / ma(5) - 1` | 短期价格偏离 |
| `spy_3d_return` | SPY 最近3日涨跌% | 大盘方向（反向ETF的直接驱动）|
| `vix_level` | VIX 当日收盘 | 波动率环境 |
| `etf_type` | 0=防御ETF，1=反向ETF | 两类行为模式不同 |

**最关键特征**：`pnl_drawdown_from_peak`  
利润从峰值开始回撤时，往往是提前出场的最强信号。

---

## 训练数据

### ⚠️ 现有数据状况（2026-03-20 调研结论）

经代码调查，现有本地 JSON 文件 **不包含** 逐笔 trade 的价格记录：

| 文件 | 有什么 | 缺什么 |
|------|--------|--------|
| `scripts/stress_test_results/ml_ab_test_results_ml-v3a.json` | 窗口级 Sharpe/回撤/胜率 | 无逐笔 entry/exit 价格 |
| `trade_log`（回测内部） | 每周 holdings 增减（added/removed） | 无价格、无 P&L |
| `weekly_details`（回测内部） | 组合级周收益% | 无单票每日持仓状态 |

**已有但未输出**：`active_stops` 字典（在 `rotation_service.py` 内部）已追踪每笔持仓的 `entry_price`、`high_since_entry`、`atr`、`stop`，只是没有输出到文件。

### 数据生成方案

需新建 `scripts/generate_exit_scorer_data.py`，在回测引擎内钩入每日持仓快照：

```python
# 在现有 run_backtest() 的 ATR stop-loss 循环内，新增每日记录：
daily_snapshots.append({
    "date": daily_date,
    "ticker": t,
    "entry_price": info["entry"],
    "current_price": daily_close,
    "high_since_entry": info["high"],
    "atr": info["atr"],
    "days_held": days_held,
    "regime": regime,
    "etf_type": etf_type_map.get(t, 0),
})

# 后处理：计算 forward_3d_return + label
# 合并 SPY/VIX 数据 + RSI/MA5 → 完整特征矩阵
# 估算样本量：45 个月 × 5 只 × 平均10天 ≈ 22,500 条
```

**数据来源**：AV API 历史价格（回测引擎已拉取并缓存，直接复用）

---

## 模型架构

```
XGBoost Classifier（与现有 ml_ranker 同框架）

输入：10 维特征向量（当前持仓状态）
输出：exit_probability（0~1，利润缩水概率）

触发条件：
  exit_probability > 0.65（初始阈值）
  AND unrealized_pnl_pct > +0.5%（最低浮盈）
  → 触发 Tranche B 出场
```

**模型文件**：`models/exit_scorer/exit_scorer.pkl`（待生成）  
**训练脚本**：`scripts/train_exit_scorer.py`（待建）  
**数据生成脚本**：`scripts/generate_exit_scorer_data.py`（待建）

---

## 评估标准

| 指标 | 计算方式 | 目标 |
|------|---------|------|
| `exit_improvement` | `B_exit_price - A_exit_price` | B 平均出价 > A |
| `early_exit_rate` | Tranche B 早于 A 出场且价格更高的比例 | > 60% |
| `alpha_captured` | B 出场后到 A 出场期间的价格变动 | 负值 = B 规避了回撤 |

---

## 与现有 ML 系统的关系

```
现有 ML Ranker（ml_scorer.py）
  ↑ 入场阶段，对候选股票评分排序
  → Bear 体制下自动关闭（池子只有5只防御ETF，无区分度）

ML Exit Scorer（新建，exit_scorer.py）
  ↑ 持仓阶段，对当前仓位每日评分
  → Bear 体制下：依然运行（仍然持有反向 ETF，出场优化有价值）
  → 不受 Regime 限制
```

---

## 开发计划

| 阶段 | 核心工作 | 关键文件 |
|------|---------|---------|
| **Week 1** | 写 `generate_exit_scorer_data.py`，钩入回测引擎生成每日快照，验证约 22K 条样本 | `rotation_service.py` L2371-2465（active_stops 循环） |
| **Week 2** | XGBoost 训练 + Walk-Forward 验证，确认 exit_improvement > 0 | `scripts/train_exit_scorer.py` |
| **Week 3** | 接入主系统，Tranche B 自动平仓 + 分开记录 P&L | `portfolio_manager.py`, `exit_scorer.py` |
| **Week 4** | 纸交易观察，调整 THRESHOLD | — |

---

## 关联文档

- [[Strategy/17-Sub-Tranche-Exit-Strategy]] — Tranche 分配策略设计
- [[Projects/D1-Sub-Tranche-Exit]] — 项目开发追踪
- [[ML/01-Architecture]] — 现有 ML 架构
- [[ML/03-Feature-Engineering]] — 现有特征工程（入场侧）
