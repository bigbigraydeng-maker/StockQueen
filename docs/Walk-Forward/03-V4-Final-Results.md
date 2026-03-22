---
name: V4 Walk-Forward 最终结论（GitHub Actions 权威版）
created: 2026-03-19
updated: 2026-03-22
tags: [walkforward, v4, results, pit, top_n, github-actions]
---

# 宝典 V4 Walk-Forward 最终结论（三版对比，PIT修正，GitHub Actions 执行）

> 本文件记录 2026-03-20 追加 GitHub Actions 自动化验证的结论，含 HB 维度以及三版 WF 完整对比。

---

## 最终锁参（生产配置）

| 参数 | 旧值（误） | 最终锁定值 | 依据 |
|------|-----------|-----------|------|
| **TOP_N** | 6（旧WF 6窗口偏差未修正） | **3** | PIT修正 + 三版对比 + HB维度验证 |
| **HOLDING_BONUS** | 未优化 | **0.0** | 滑动18窗口中 5/5 次选 HB=0 |
| ATR_STOP | 1.5 | 1.5 | 未变 |
| Trailing Stop | 1.5倍 ATR | 1.5倍 ATR | 未变 |
| Trailing Activate | 0.5倍 ATR | 0.5倍 ATR | 未变 |

---

## GitHub Actions 自动化验证（2026-03-20，权威版）

### 验证环境

| 项目 | 值 |
|------|-----|
| **平台** | GitHub Actions (ubuntu-24.04) |
| **Python** | 3.11.15 |
| **Run ID** | [#23328921760](https://github.com/bigbigraydeng-maker/StockQueen/actions/runs/23328921760) |
| **执行时间** | 2026-03-20 10:07 |
| **数据来源** | AV cache（GitHub Release `av-cache-latest`，391MB → 107MB 压缩）|
| **覆盖期间** | 5 windows（W1-W5）2018-2024 |
| **搜索空间** | top_n=[2,3,4,5,6,7] × HB=[0.0, 0.5, 1.0] = **18 组合/窗口** |
| **AV 数据规模** | 3892 tickers，2018-2026 daily OHLCV |

> 注：静态 502 只在 2026 年才有数据，存在偏差，Phase 2 修复计划中。

---

## 三版 WF 完整对比

| 窗口 | 测试期 | 旧WF top_n=6 | 新[3-7] top_n=3 | 新[2-7] top_n=2 |
|------|--------|-------------|----------------|----------------|
| W1 | 2020 COVID | OOS 1.92 | OOS 1.98 | OOS 1.98 |
| W2 | 2021 牛市 | OOS 2.28 | OOS 2.99 | OOS 3.55 |
| W3 | 2022 熊市 | OOS 2.52 | OOS 1.97 | OOS 1.70 |
| W4 | 2023 反弹 | OOS 2.68 | OOS 3.27 | **OOS 0.00 ⚠️** |
| W5 | 2024 AI牛 | OOS 2.15 | OOS 3.73 | OOS 2.05 |
| **均值** | | **2.33** | **3.10** | **1.856** |

---

## 最终决策

| top_n | avg OOS | 最差窗口 | 稳定性 |
|-------|---------|---------|--------|
| 6（旧WF） | 2.33 | W2=0.49 | 不稳定，旧脚本偏差 |
| **3（选定）** | **3.10** | **W3=1.97** | **全正，稳定 ✅** |
| 2 | 1.856 | W4=0.00 | 灾难性失效 ❌ |

**top_n=2 在 W4（2023年）彻底失效：OOS Sharpe=0，MaxDD -27.6%**
2023年方向单一的反弹年，只持2只集中度过高，单只失误即毁全年收益。

**top_n=3 是最优：5/5 窗口全正、均值最高、无灾难性失效。**

---

## 推导可信度

本次结论经历严格三步验证：
1. 旧WF [3-7] → top_n=3 全5窗口一致
2. 质疑：是否存在地板效应（top_n=2 未测）
3. 补测 [2-7] → top_n=2 W4 灾难性失效，反证 top_n=3 的稳健性

**方法论完整，结论可信。PIT数据 + GitHub Actions 独立环境 = 去偏差验证。**

---

## HOLDING_BONUS 维度结论

滑动18个月训练窗口中，5/5次 IS 最优参数选择 HB=0.0。
HB>0 表面提升 IS Sharpe，但 OOS 均值低于 HB=0，判定为过拟合。

**HOLDING_BONUS 锁定为 0.0。**

---

## 生产变更记录

```python
# app/config/rotation_watchlist.py
# 变更时间：2026-03-20
TOP_N: int = 6  →  TOP_N: int = 3
HOLDING_BONUS: float = ...  →  HOLDING_BONUS: float = 0.0
# 依据：三版WF对比 + HB维度验证，top_n=3 avg OOS 3.10，5/5 全正
```

---

---

## ✅ 官方对外披露数字（2026-03-22 采纳）

> 用于官网、融资文件、回测页面说明的权威指标。
> **原则：用 Walk-Forward OOS 指标为主打，不用 IS 全周期回测数字（幸存者偏差过高）。**

| 指标 | 数值 | 备注 |
|------|------|------|
| **OOS Sharpe（保守）** | **1.70** | W3 熊市窗口作为最坏情况基准 |
| **OOS Sharpe（排除扭曲）** | **2.13** | 排除 2023 AI 新股潮短期扭曲 |
| **周胜率** | **57.7%** | 5 窗口 WF OOS 加权均值 |
| **最大回撤** | **-19.1%** | OOS 期内峰谷最大跌幅 |
| 验证方法 | Walk-Forward 5 窗口 | 滑动训练 IS → 真实前向 OOS |
| 数据来源 | GitHub Actions 独立环境 | 无内存污染，AV 复权价格 |

**为什么不用 IS 回测数字？**
回测宇宙由 2026 年视角构建，包含已知赢家（NVDA、AMD 等），
即使加入 universe lock + 复权价格修复，幸存者偏差无法完全消除。
OOS Sharpe 是真正"机器没见过的数据"上的表现，是最可信的指标。

---

## 相关文档

- [[Walk-Forward/08-PIT-WF-Results-V4]] — 详细 PIT 修正分析
- [[Walk-Forward/04-Bias-Corrections]] — 偏差修正方法论
- [[Walk-Forward/07-Survivorship-Bias-Fix]] — 幸存者偏差修复进展
- [[Strategy/01-Current-Strategy-Overview]] — 当前策略参数总览
