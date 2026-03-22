---
created: 2026-03-19
source_date: 2026-03-15
source: site/weekly-report/content/week-11-2026-v4-update.md
tags: [walkforward, index, stockqueen]
---

# Walk-Forward 验证体系

> StockQueen 策略验证核心文档库
> 创建日期：2026-03-19 | 源数据日期：2026-03-15

---

## 文档索引

| 文档 | 内容 | 创建日期 |
|------|------|---------|
| [[01-Methodology]] | Walk-Forward 验证的设计原理、窗口划分、优化指标 | 2026-03-19 |
| [[02-Iteration-History]] | V1到V4四轮迭代的参数变化、指标演进、关键决策 | 2026-03-19 |
| [[03-V4-Final-Results]] | 宝典V4 锁定参数、6窗口 OOS 结果、拼接业绩 | 2026-03-19 |
| [[04-Bias-Corrections]] | 三项偏差修正详解 + 五项已知局限的诚实披露 | 2026-03-19 |
| [[05-V5-Next-Steps]] | 动态选股池、Regime仓位、因子权重优化等下一步计划 | 2026-03-19 |
| [[06-Sub-Strategy-WF-Validation]] | MR/ED 子策略 Walk-Forward 验证结果（V5 标准） | 2026-03-19 |

---

## 速查关键指标

### 宝典V4 趋势策略（已锁定）

| 指标 | 宝典V4 最终值 |
|------|----------|
| 累计收益（188周OOS拼接） | **494.4%** |
| 年化收益 | **63.7%** |
| 夏普比率 | **2.33** |
| 最大回撤 | **-20.8%** |
| 过拟合衰减 | **0.23** |
| 锁定参数 | TOP_N=6, HB=0.0, ATR_STOP=1.5, Trailing=1.5xATR |

### 子策略验证结果（2026-03-19）

| 策略 | OOS 夏普 | 衰减 | 判定 | 备注 |
|------|---------|------|------|------|
| 均值回归 (MR) | 0.959 | -0.475 | ✅ PASS | RSI=28 稳定，负衰减说明无过拟合 |
| 事件驱动 (ED) | 0.393 | 0.128 | ⚠️ MARGINAL | 2021 FOMO 市场结构性失效，降权监控 |

---

## 数据来源

- 周报原文：`site/weekly-report/content/week-11-2026-v4-update.md`
- Walk-Forward 脚本（V4）：`scripts/walk_forward_test.py`
- Walk-Forward 脚本（V5 子策略）：`scripts/walk_forward_v5_full.py`
- 敏感性分析脚本：`scripts/sensitivity_test.py`
- 结果文件（V4）：`scripts/stress_test_results/walk_forward_v4.json`
