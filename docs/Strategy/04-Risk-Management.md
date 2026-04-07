---
created: 2026-03-19
source_date: 2026-03-22
source: app/config/rotation_watchlist.py, app/services/rotation_service.py
tags: [strategy, risk, stoploss, trailing, stockqueen]
---

# 风控体系

---

## 风控层级

```
Layer 0: Hedge Overlay — choppy/bear 独立对冲仓位（反向ETF）
Layer 1: 体制过滤 ——— 熊市自动切换到防守ETF池
Layer 2: VIX减仓 ——— VIX > 25 全局降仓
Layer 3: 相对强度过滤 — RS < -2% 不入选
Layer 4: 板块集中度 —— 同板块最多2只
Layer 5: ATR硬止损 ——— 入场 - 1.5 x ATR
Layer 6: Trailing Stop — 浮盈后跟踪止盈
Layer 7: 时间止损 ——— 均值回归策略8天上限
```

---

## ATR 硬止损

| 参数 | 值 |
|------|-----|
| ATR_PERIOD | 14 天 |
| STOP_MULT | 1.5 |
| 止损价 | entry_price - 1.5 x ATR(14) |

**示例**:
- 入场价 $100, ATR(14) = $3.00
- 止损价 = $100 - 1.5 x $3 = **$95.50**
- 最大单笔亏损 = 4.5%

---

## Trailing Stop（追踪止盈）

| 参数 | 值 |
|------|-----|
| TRAILING_STOP_ATR_MULT | 1.5 |
| TRAILING_ACTIVATE_ATR | 0.5 |

### 逻辑

```
浮盈 = current_price - entry_price

if 浮盈 >= 0.5 x ATR:       # 激活条件（低门槛）
    trailing_stop = highest_price_since_entry - 1.5 x ATR
    effective_stop = max(hard_stop, trailing_stop)
else:
    effective_stop = hard_stop  # 还在硬止损阶段
```

### 示例
- 入场 $100, ATR = $3
- 硬止损 = $95.50
- 股价涨到 $101.50（浮盈 $1.50 = 0.5 x ATR）→ trailing 激活
- 股价涨到 $110 → trailing_stop = $110 - $4.50 = **$105.50**
- 股价回落到 $105.50 → 触发止盈出场，锁定 +5.5%

---

## ATR 目标价（止盈参考）

| 参数 | 值 |
|------|-----|
| ATR_TARGET_MULTIPLIER | 3.0 |
| 目标价 | entry_price + 3.0 x ATR(14) |

> 目标价仅作参考，实际出场依赖 trailing stop 或下周轮动排名。

---

## VIX 全局减仓

| VIX 水平 | 仓位乘数 | 效果 |
|----------|---------|------|
| > 35 (恐慌) | x 0.70 | 30% 现金缓冲 |
| > 25 (高压) | x 0.85 | 15% 现金缓冲 |
| < 25 (正常) | x 1.00 | 满仓运作 |

VIX 减仓作用在**所有策略之上**，是最外层的风控网。

---

## 滑点模型

| 参数 | 值 |
|------|-----|
| BACKTEST_SLIPPAGE | 0.001 (0.1%) |
| 适用场景 | 每次新建仓 + 每次平仓 |
| 往返成本 | 0.2% |

年化交易成本估算:
- TOP_N=6, 每周轮动 1-3 只
- 约 100-150 次年交易
- 年化成本: **约 2-3%**

---

## 各策略风控参数对比

| 参数 | V4 轮动 | 均值回归 | 事件驱动 |
|------|---------|---------|---------|
| ATR止损倍数 | 1.5 | 2.0 | 1.5 |
| Trailing Stop | 1.5x ATR | 无 | 无 |
| 最大持仓 | 6 | 3 | 4 |
| 板块限制 | 2 | 2 | 2 |
| 时间止损 | 无（周轮动） | 8天 | 无 |
| 体制限制 | 全体制 | 仅 bull | 全体制 |

---

## 历史止损触发统计 (V4 回测)

| 类型 | 触发次数 | 占比 |
|------|---------|------|
| ATR 硬止损触发 | 42 次 | ~22% 的出场 |
| Trailing Stop 触发 | 18 次 | ~9% 的出场 |
| 轮动排名出局 | ~130 次 | ~69% 的出场 |

---

## Hedge Overlay 独立对冲层（V5 新增 2026-03-22）

> 架构升级：反向ETF不再与个股竞争 Top-N 名额，改为独立的第4个 slot。

### 设计哲学

```
┌─────────────────────────────────────┐
│  Layer 1: Alpha 选股（不变）         │
│  纯评分 Top-3，不错过大牛股          │
├─────────────────────────────────────┤
│  Layer 2: Hedge Overlay（新增）      │
│  独立于选股，按 regime 信号渐进对冲   │
│  不占 Top-3 名额，独立仓位           │
└─────────────────────────────────────┘
```

### 对冲仓位分配

| Regime | 对冲比例 | 动作 |
|--------|---------|------|
| strong_bull | 0% | 全仓进攻 |
| bull | 0% | 全仓进攻 |
| choppy | 10% | 小仓对冲 |
| bear | 30% | 加大对冲 |

### 反向ETF选择逻辑

自动选择**原指数最弱**的反向ETF：

| 反向ETF | 对标指数 |
|---------|---------|
| SH | SPY (S&P 500) |
| PSQ | QQQ (Nasdaq 100) |
| RWM | IWM (Russell 2000) |
| DOG | DIA (Dow 30) |

**弱度计算**: `weakness = -(0.4 × 1周回报 + 0.6 × 1月回报)`

### 收益混合公式

```
最终收益 = (1 - hedge_alloc) × alpha收益 + hedge_alloc × 对冲收益
```

### 回测验证（2018-2026）

| 区间 | 基线收益 | 对冲收益 | MDD改善 | Sharpe改善 |
|------|---------|---------|---------|-----------|
| **2022 Bear** | +64% | +83% | -4.8% | +0.46 |
| 2023 Recovery | +7% | +11.5% | -1.2% | +0.09 |
| 2024 Bull | +157.7% | +129.6% | -0.9% | -0.33 |
| **2025 YTD** | +323.2% | +318% | -5.6% | +0.19 |

### 对冲活动统计（全周期）

- 全程 411 周中 138 周启用对冲（33.6%）
- bear 周: 99 周, choppy 周: 39 周
- 最常用: RWM (65周), PSQ (58周), SH (15周)

### 配置参数

| 参数 | 值 | 来源 |
|------|-----|------|
| HEDGE_OVERLAY_ENABLED | True | rotation_watchlist.py |
| HEDGE_ALLOC_BY_REGIME | {choppy: 0.10, bear: 0.30} | rotation_watchlist.py |

> **代码位置**: `app/config/rotation_watchlist.py` L93-102, `app/services/rotation_service.py` 回测+生产函数