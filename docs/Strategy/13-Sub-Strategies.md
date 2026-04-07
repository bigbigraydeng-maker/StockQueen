---
name: 子策略详解：均值回归 + 事件驱动
description: Mean Reversion入场条件/退出信号/参数 + Event Driven财报策略完整逻辑
type: reference
created: 2026-03-19
updated: 2026-03-23
tags: [strategy, mean-reversion, event-driven, sub-strategy, RSI, bollinger]
---

> 注：原 06-Multi-Strategy-Matrix 内容已合并至此文档。

# 子策略详解

## 三策略体系

StockQueen 采用 **三策略组合**，由 Regime 动态分配资金：

| 策略 | 定位 | 适用Regime | 文件 |
|------|------|-----------|------|
| V4 趋势轮动 | 核心策略 | strong_bull, bull | rotation_service.py |
| 均值回归 | 震荡市补充 | bull only | mean_reversion_service.py |
| 事件驱动 | 全天候 | 全部 | event_driven_service.py |

### Regime 资金分配矩阵

| Regime | V4 | 均值回归 | 事件驱动 | 现金 |
|--------|-----|---------|---------|------|
| Strong Bull | **70%** | 0% | 30% | 0% |
| Bull | **60%** | 10% | 30% | 0% |
| Choppy | 30% | **50%** | 20% | 0% |
| Bear | 20% | 0% | 30% | **50%** |

**文件**: `app/services/portfolio_manager.py:46-51`

---

## 1. 均值回归策略 (Mean Reversion)

### 1.1 核心理念
在超卖条件下买入，等待价格回归均值后卖出。只在 **bull** regime 激活。

### 1.2 入场条件（三条件全满足）

| 条件 | 阈值 | 说明 |
|------|------|------|
| RSI(14) | < 28 | 深度超卖（从32收紧至28） |
| BB位置 | < 0.05 | 接近布林下轨（极端位置） |
| 量比 | > 1.5× | 成交量突增（恐慌性抛售信号） |

**文件**: `app/services/mean_reversion_service.py:45-70`

### 1.3 退出信号（任一触发）

| 条件 | 阈值 | 说明 |
|------|------|------|
| RSI 回升 | > 55 | 回到中性区域 |
| BB 回归 | 回到中轨 | 均值回归完成 |
| 时间止损 | > 8 天 | 长期不回归则认输 |
| ATR 止损 | entry - 2.0×ATR | 硬止损保护 |

### 1.4 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| MAX_POSITIONS | 3 | 同时最多3只 |
| ATR_STOP_MULT | 2.0 | 宽止损（容忍均值回归波动） |
| MAX_HOLD_DAYS | 8 | 时间止损 |
| 最低成交量 | 100万/天 | 流动性门槛 |

### 1.5 适用场景
- ✅ **Bull**: 市场整体上行，个股暂时超卖 → 大概率反弹
- ❌ **Strong Bull**: 强趋势市不做逆势（分配0%）
- ❌ **Choppy**: 50%分配给均值回归（通过portfolio_manager）
- ❌ **Bear**: 下跌市超卖可能继续跌（分配0%）

> **注意**: Choppy regime 下 MR 分配50%，但只有 regime == "bull" 时才真正激活入场逻辑

---

## 2. 事件驱动策略 (Event Driven)

### 2.1 核心理念
在盈利公告前买入历史 beat 率高的股票，赚取财报发布后的正向跳空。

### 2.2 入场条件

| 条件 | 阈值 | 说明 |
|------|------|------|
| 距财报发布 | ≤ 3天 | 进入事件窗口 |
| EPS Beat率 | ≥ 70% | 过去4季度至少3次超预期 |
| 最近Surprise | ≥ 2% | 上次超预期幅度足够 |
| 最低成交量 | 200万/天 | 高流动性要求（避免财报跳空大滑点） |

**文件**: `app/services/event_driven_service.py:43-63`

### 2.3 退出信号

| 条件 | 说明 |
|------|------|
| **财报后次日开盘** | 核心退出：发布日后第一个交易日 open 卖出 |
| ATR 止损 | entry - 1.5×ATR（紧止损，财报前波动大） |

### 2.4 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| MAX_POSITIONS | 4 | 同时最多4只（strong_bull 时自动减半为2） |
| ATR_STOP_MULT | 1.5 | 紧止损 |
| ENTRY_WINDOW | 3天 | 财报前3天窗口 |
| MIN_BEAT_RATE | **0.60** | 60%历史beat率（WF验证最优值，原0.70） |
| MIN_SURPRISE | 2% | 最近一次surprise幅度 |
| 最低成交量 | 200万/天 | 最高流动性要求 |

> **2026-03-19 更新**：MIN_BEAT_RATE 由 0.70 降至 0.60（Walk-Forward 5/5 窗口最优）；
> strong_bull regime 下 MAX_POSITIONS 自动减半（防 FOMO 牛市 ED 失效）。
> WF 验证结果：MARGINAL（OOS 夏普 0.393，衰减 0.128），已纳入组合但降权重监控。
> 详见 [[Walk-Forward/06-Sub-Strategy-WF-Validation]]

### 2.5 适用场景
- ✅ **所有 Regime**: 财报驱动的价格变动与大盘趋势相对独立
- 资金分配: 20%~30%（根据regime调整）

---

## 3. 策略冲突解决

当同一标的出现在多个策略中时：

**优先级**: V4 趋势 > 事件驱动 > 均值回归

**文件**: `app/services/portfolio_manager.py:123-150`

---

## 4. VIX 全局调节

所有策略的资金分配在最终执行前，统一经过 VIX 减杠杆：

| VIX 水平 | 乘数 | 效果 |
|----------|------|------|
| > 35 | × 0.70 | 保留 30% 现金缓冲 |
| > 25 | × 0.85 | 保留 15% 现金缓冲 |
| < 25 | × 1.00 | 正常执行 |

**文件**: `app/services/portfolio_manager.py:53-58`

---

## 5. 策略相关性

三策略之间低相关性是组合价值的基础：

| 对比 | 相关性 | 原因 |
|------|--------|------|
| V4 轮动 vs 均值回归 | 低 | 一个追涨，一个抄底 |
| V4 轮动 vs 事件驱动 | 低 | 一个看趋势，一个看催化剂 |
| 均值回归 vs 事件驱动 | 极低 | 完全不同的触发逻辑 |

---

## 6. 策略冲突解决

当同一标的出现在多个策略中时：

**优先级**：V4 趋势 > 事件驱动 > 均值回归

**文件**：`app/services/portfolio_manager.py:123-150`

---

## 关键文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `app/services/mean_reversion_service.py` | ~600行 | 均值回归完整逻辑 |
| `app/services/event_driven_service.py` | ~800行 | 事件驱动完整逻辑 |
| `app/services/portfolio_manager.py` | ~500行 | 三策略资金分配 + VIX调节 |
| `app/services/rotation_service.py` | ~2600行 | V4趋势核心逻辑 |
