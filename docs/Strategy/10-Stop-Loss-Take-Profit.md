---
name: 止盈止损策略详解
description: ATR静态止损/止盈（regime-aware）+ Trailing Stop + 均值回归/事件驱动止损 + 实时监控机制
type: reference
created: 2026-03-19
updated: 2026-03-20
tags: [strategy, stop-loss, take-profit, trailing-stop, risk, ATR, regime]
---

# 止盈止损策略详解

## 概览

StockQueen 采用**多层止盈止损架构**，不同子策略有独立的止损参数，同时共享 VIX 全局减杠杆机制。

```
交易风控层
├── 入场前 → check_all_risk_limits()
├── 静态止损 → entry - ATR_STOP_MULT(regime) × ATR14   ← Regime-Aware
├── 静态止盈 → entry + ATR_TARGET_MULT(regime) × ATR14  ← Regime-Aware
├── Trailing Stop → 盈利 ≥ 0.5×ATR 激活，跟随最高价 - 1.5×ATR
├── 实时监控 → 每5分钟 intraday check (order_service.py)
├── 每日检查 → 盘后 daily exit check (rotation_service.py)
└── VIX 全局减杠杆 → VIX>25: ×0.85, VIX>35: ×0.70
```

---

## 1. V4 趋势策略止损

### 1.1 Regime-Aware ATR 止损/止盈（2026-03-20 更新）

熊市保守ETF（TLT/GLD/SHY）和反向ETF（SH/PSQ/RWM）持有时间长会受到 ETP 每日衰减侵蚀，
因此止盈倍数按市场机制动态调整，快打快撤。止损同样收紧，R:R 始终维持 2:1。

| 市场机制 | 止损倍数 | 止盈倍数 | R:R | 适用资产 |
|---------|---------|---------|-----|---------|
| `strong_bull` | 1.5x ATR | 4.0x ATR | 2.67:1 | 进攻型ETF+大盘股 |
| `bull` | 1.5x ATR | 3.0x ATR | 2:1 | 全池（WF锁定值） |
| `choppy` | 1.2x ATR | 2.5x ATR | 2.08:1 | 偏防御，反弹幅度有限 |
| `bear` | 1.0x ATR | 2.0x ATR | 2:1 | TLT/GLD/SHY/反向ETF |

**配置文件**: `app/config/rotation_watchlist.py`
```python
ATR_STOP_BY_REGIME  = {"strong_bull":1.5, "bull":1.5, "choppy":1.2, "bear":1.0}
ATR_TARGET_BY_REGIME = {"strong_bull":4.0, "bull":3.0, "choppy":2.5, "bear":2.0}
```

**生效位置**（已全部改为 regime-aware）:
- `rotation_service.py:run_daily_entry_check()` — 入场信号止盈止损
- `order_service.py:sync_tiger_orders()` — Tiger 成交后重算
- `web.py:api_tiger_sync_orders()` — 手动同步Tiger时重算
- `web.py:weekly_report` — 周报价格目标显示

### 1.2 Trailing Stop（尾随止损）— 不随 regime 变化

- **激活条件**: 盈利 ≥ 0.5 × ATR（Walk-Forward 锁定）
- **跟随距离**: highest_price - 1.5 × ATR
- **逻辑**: 当 trailing_sl > static_sl 时替代静态止损
- **文件**: `app/services/rotation_service.py:1148-1155`

```
价格走势示意（bear 机制，ATR=$2，止盈=2.0x）：
入场 $100, ATR=$2
├── 静态止损: $98 (100-1.0×2)   ← 比 bull 更紧
├── 静态止盈: $104 (100+2.0×2)  ← 比 bull 更小，快速锁利
├── Trailing 激活: $101 (盈利≥$1=0.5×ATR)
│   └── highest=$103 → trailing_sl=$100 (103-1.5×2)
│       已超过静态止损 $98，trailing 接管
```

### 1.3 退出优先级

1. **Trailing Stop** > **静态止损** > **静态止盈** > **轮动出场**
2. 实际执行: `effective_sl = max(static_sl, trailing_sl)`

---

## 2. 均值回归策略止损

| 参数 | 值 | 说明 |
|------|-----|------|
| ATR止损倍数 | 2.0 | 宽松止损（均值回归需要容忍波动） |
| 时间止损 | 8天 | 超过8天未回归则强制退出 |
| RSI止盈 | RSI > 55 | 回到中性区域即止盈 |
| BB止盈 | 回到BB中轨 | 均值回归完成 |
| **文件** | `app/services/mean_reversion_service.py:55-58` | |

---

## 3. 事件驱动策略止损

| 参数 | 值 | 说明 |
|------|-----|------|
| ATR止损倍数 | 1.5 | 紧止损（财报前波动大，控制风险） |
| 退出时机 | 财报后次日开盘卖出 | 不隔夜持有避免跳空风险 |
| **文件** | `app/services/event_driven_service.py:51` | |

---

## 4. 实时监控机制

### 4.1 盘中5分钟检查
- **函数**: `run_intraday_trailing_stop()`
- **文件**: `app/services/order_service.py:677-837`
- **频率**: 美股交易时段每5分钟
- **检查内容**: 止损/止盈/Trailing Stop 全部条件
- **触发动作**: 立即下 MKT SELL 市价卖单

### 4.2 盘后每日检查
- **函数**: `run_daily_exit_check()`
- **文件**: `app/services/rotation_service.py:1100-1192`
- **频率**: 每交易日收盘后
- **额外检查**: 轮动出场（被踢出 TOP N）

### 4.3 订单同步
- **函数**: `sync_tiger_orders()`
- **文件**: `app/services/order_service.py:420-622`
- **功能**: 与 Tiger 券商 API 对账，根据实际成交价 + 当前 regime 重算 SL/TP

---

## 5. 全局风险参数

| 参数 | 值 | 文件位置 |
|------|-----|---------|
| 全局最大持仓 | 2 | settings.py:116 |
| 每笔风险额 | 10% 权益 | settings.py:117 |
| 最大回撤 | 15% | settings.py:118 |
| 连续亏损上限 | 2次 | settings.py:119 |
| VIX>25 减杠杆 | ×0.85 | portfolio_manager.py:56 |
| VIX>35 减杠杆 | ×0.70 | portfolio_manager.py:55 |

---

## 6. 仓位规模

### 6.1 等权分配（默认）
```
shares = floor(account_equity / max_positions / entry_price)
单仓上限: 50% 总权益
```
- **文件**: `app/services/order_service.py:369-397`

### 6.2 基于风险的仓位
```
risk_amount = equity × 10%
shares = floor(risk_amount / (entry - stop_loss))
```
- **文件**: `app/services/risk_service.py:75-102`

---

## 关键常数速查

| 参数 | V4趋势(bull) | V4趋势(bear) | 均值回归 | 事件驱动 |
|------|-------------|-------------|---------|---------|
| ATR止损倍数 | 1.5 | 1.0 | 2.0 | 1.5 |
| ATR止盈倍数 | 3.0 | 2.0 | N/A (RSI) | N/A (次日开盘) |
| Trailing激活 | 0.5×ATR | 0.5×ATR | 无 | 无 |
| Trailing距离 | 1.5×ATR | 1.5×ATR | 无 | 无 |
| 最大持仓 | 6 | 6 | 3 | 4 |
| 最低成交量 | 50万 | 50万 | 100万 | 200万 |

> **Bull 参数通过 Walk-Forward 6窗口验证锁定，Bear/Choppy 倍数为 2026-03-20 新增 regime-aware 机制**
