---
name: Mid-week Replacement Strategy
description: 周中退出后的补位逻辑：提高资金利用率，从备选名单补仓，含信号有效性验证（ATR漂移检测）
created: 2026-03-20
updated: 2026-03-21
tags: [strategy, rotation, capital-efficiency, bear-market, implemented]
status: implemented
---

# 周中补位机制（Mid-week Replacement）

> **状态**: 已实现并生产运行 ✅
> **触发时机**：周中某仓因 SL/TP 止损/止盈退出后，出现空槽
> **目的**：避免 5-6 个交易日空仓，提高资金利用率

---

## 问题背景

```
周轮动 SL/TP 退出 → 释放了一个仓位
周中（非周六）Daily Entry Check 每天检查，但只处理 pending_entry
只有 Weekly Rotation (周六 10:00 NZT) 才会选新仓
→ 周一退出 → 到周六 = 5-6 天空仓，浪费资金
```

**解决方案**：用 Job 4b Mid-week Replacement Check，从本周快照备选名单补位。

---

## 执行流程

```
NZT 09:45  Daily Exit Check（原有）
    → 退出信号触发，status 变为 closed
NZT 09:47  Mid-week Replacement Check（Job 4b）
    ↓
1. 统计空槽 = TOP_N - (active + pending_entry)
    ↓
2. 读取最新 rotation_snapshot.scores（按分数降序）
    ↓
3. 过滤已占用 ticker，得到备选列表
    ↓
4. 逐一验证候选，ATR漂移检测：
    ├── 当前价 > 信号价 + 1 ATR → 追高风险，跳过
    ├── 当前价 < 信号价 - 1 ATR → 信号失效，跳过
    └── 通过 → 以当前价重算 SL/TP → 创建 pending_entry
         ↓
5. 等待 09:40 NZT Daily Entry Check 完成 MA5 + 成交量确认入场
```

---

## 信号有效性验证（ATR漂移检测）

### 漂移阈值规则

| 漂移程度 | 判断 | 处理 |
|---------|------|------|
| `drift < 0.5 ATR` | 有效，价格基本未动 | 直接建仓 |
| `0.5 ~ 1.0 ATR` | 有效，价格小幅漂移 | 按当前价重算 SL/TP |
| `drift > 1.0 ATR（上方）` | 追高风险，信号失效 | 跳过 |
| `drift > 1.0 ATR（下方）` | 下跌过深，信号失效 | 跳过 |

### 代码位置
```python
# app/services/rotation_service.py:1266
async def run_midweek_replacement() -> list[dict]:
```

---

## SL/TP 重算逻辑

以**当前市场价格**为基准，按体制动态倍数重算：

```python
new_sl = current_price - stop_mult  * atr14
new_tp = current_price + target_mult * atr14
```

体制对应倍数：
| 体制 | stop_mult | target_mult |
|------|-----------|-------------|
| strong_bull | 1.5 | 4.0 |
| bull | 1.5 | 3.0 |
| choppy | 1.2 | 2.5 |
| bear | 1.0 | 2.0 |

---

## 相关 Job 时序

```
09:45 Daily Exit Check  → 关闭退出仓位
09:47 Midweek Replacement → 补位候选 → pending_entry
次日09:40 Daily Entry Check → MA5确认 → 执行入场
```

---

## 效率提升估算

- 无补位：周中退出后平均等待 3 天空仓
- 有补位：次日即可入场，空仓缩短至 ~1 天
- 预估资金利用率提升 ~15-20%（按每周平均补位1次计算）

---

## 相关文档

- [[Strategy/03-Rotation-Logic]] — 轮动核心逻辑
- [[Strategy/10-Stop-Loss-Take-Profit]] — ATR止损止盈计算
- [[Scheduler-Jobs]] — Job 4b 调度时序
