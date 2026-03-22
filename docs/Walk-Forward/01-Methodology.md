---
created: 2026-03-19
source_date: 2026-03-15
source: site/weekly-report/content/week-11-2026-v4-update.md
tags: [walkforward, methodology, stockqueen]
---

# Walk-Forward 验证方法论

---

## 什么是 Walk-Forward 验证？

Walk-Forward 是量化策略验证的金标准。核心思想：**用过去的数据训练参数，然后在完全没见过的未来数据上测试**——模拟真实交易中"只能看到历史"的约束。

与简单回测的区别：
- ❌ **简单回测**：用全部数据优化参数 → 过拟合 → 实盘翻车
- ✅ **Walk-Forward**：滚动训练+测试 → 验证参数稳定性 → 接近真实业绩

---

## StockQueen 的实现设计

### 窗口划分
- **训练窗口**：8个月（用于参数优化）
- **测试窗口**：8个月（OOS，参数冻结后"盲测"）
- **窗口数量**：6个重叠窗口
- **覆盖期间**：2021年7月 至 2026年3月（约4.5年）

### 参数搜索网格
每个窗口搜索 25 种组合：
- `TOP_N`（持仓数量）：5 个候选值
- `HOLDING_BONUS`（持有加分）：5 个候选值
- 固定参数：`ATR_STOP=1.5`, `Trailing=1.5xATR`, `Trailing_Activate=0.5xATR`

### 优化指标
- 在训练集上按 **夏普比率** 排序选最优参数
- 然后用该参数在 OOS 窗口上"盲跑"

### 核心原则
> **参数绝不在其训练数据上评估。**
> 训练集选参数，OOS 测表现，两者严格隔离。

---

## 过拟合衰减（Overfitting Decay）

衡量训练集表现到 OOS 的"缩水"程度：

```
Decay = 1 - (OOS Sharpe / Training Sharpe)
```

| Decay 值 | 含义 |
|----------|------|
| < 0.2 | 极低衰减，策略非常稳健 |
| 0.2 - 0.4 | 适度衰减，存在真实 edge |
| 0.4 - 0.6 | 较高衰减，edge 可疑 |
| > 0.6 | 严重过拟合，策略不可靠 |

**V4 的 Decay = 0.23** → 适度衰减，确认真实 edge。

---

## 拼接 OOS 业绩

将 6 个窗口的 OOS 段按时间顺序拼接，形成一条"从未被训练数据污染"的连续业绩曲线。

- 拼接总长度：**188 周**
- 这条曲线最接近"如果从 2022 年开始真实运行策略"的表现

---

## 相关文件

- 脚本：`scripts/walk_forward_test.py`
- 结果 JSON：`scripts/stress_test_results/walk_forward_v4.json`
- 策略矩阵回测：`scripts/stress_test_results/` 目录下多个 JSON
