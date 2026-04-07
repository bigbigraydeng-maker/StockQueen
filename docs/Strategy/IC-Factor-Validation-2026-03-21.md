---
name: 因子 IC 验证结果（2026-03-21）
description: 9因子IC验证完整结果：中盘/大盘IC对比、权重调整依据、Walk-Forward对比测试、PurgedKFold实现
created: 2026-03-21
updated: 2026-03-23
tags: [strategy, factor, IC, walk-forward, validation]
---

# 因子 IC 验证结果（2026-03-21）

> 本次完成：因子有效性 IC 分析 + 权重调整 + Walk-Forward 对比测试

---

## 背景

使用信息系数（IC = Spearman 相关系数）客观验证 9 个因子的预测能力，替代此前手动调参的权重方案。

**工具链：**
- `scripts/prefetch_fundamentals.py` — 预拉取 445 只股票的盈利/现金流数据
- `scripts/pure_alpha_stress_test.py` — 每周截面 IC 计算（支持 --universe / --sector）
- `scripts/purged_kfold_demo.py` — PurgedKFold 信息泄漏演示

---

## 中盘股 IC 结果（2022-2025，329 只，159 个截面）

| 因子 | 旧权重 | 4周IC | t 统计量 | 结论 |
|------|--------|-------|---------|------|
| earnings（盈利质量） | 10% | +0.041 | **5.21** | 最强信号，严重低权 ↑↑ |
| cashflow（现金流） | 5% | **+0.062** | 2.75 | IC 最高，n=45 偏小 ↑↑ |
| momentum（动量） | 25% | +0.049 | 3.14 | 弱有效，稳定 |
| trend（趋势） | 10% | +0.017 | 1.70 | 弱正信号 |
| relative_strength（相对强度） | 10% | +0.012 | 1.02 | 接近零 |
| technical（技术指标） | 15% | **-0.012** | **-1.72** | **负信号，有害因子** ↓↓ |
| fundamental（基本面） | 15% | N/A | — | AV 无时间序列数据，无法 IC 验证 |

**核心发现：**
- technical 因子 IC 持续为负 —— 15% 权重在主动拖低选股质量
- earnings t 统计量 5.21 是所有因子最高，但仅被分配 10% 权重
- cashflow n=45（vs earnings n=159）是早期季度数据稀疏所致，非数据缺失

---

## 大盘股 IC 结果（2022-2025，95 只，159 个截面）

| 因子 | 4周IC | t 统计量 | 结论 |
|------|-------|---------|------|
| momentum（动量） | -0.034 | -2.05 | **负信号** — 大盘动量反转效应 |
| earnings（盈利质量） | -0.026 | -2.88 | **负信号** — 买传闻卖事实效应 |
| technical（技术指标） | +0.006 | +0.56 | 略正（机构技术交易） |
| 其他因子 | ~0 | <1.0 | 全部无显著预测力 |

**核心发现：**
- 大盘股截面多因子排名**完全失效**
- 原因：把 AAPL vs JPM vs NEE 放在同一排名毫无意义（跨行业不可比）
- **正确方向：行业内相对强度选股，而非全局排名**（V5 路线图 Phase 2.2b）

---

## 权重调整（中盘股 FACTOR_WEIGHTS，已推送生产）

| 因子 | 旧权重 | 新权重 | 变化 | 依据 |
|------|--------|--------|------|------|
| momentum | 25% | **20%** | ↓ | IC 弱有效但稳定，适度降权 |
| technical | 15% | **5%** | ↓↓ | IC 全负（-0.012），有害因子 |
| trend | 10% | 10% | — | IC 弱正（+0.017），维持 |
| relative_strength | 10% | **8%** | ↓ | IC 不显著（t=1.02） |
| fundamental | 15% | **12%** | ↓ | 无法 IC 验证，适度降权 |
| earnings | 10% | **22%** | ↑↑ | t 统计量 5.21，最强信号 |
| cashflow | 5% | **13%** | ↑↑ | IC=+0.062，最高 |
| sentiment | 5% | 5% | — | 维持 |
| sector_wind | 5% | 5% | — | 维持 |

**核心变化**：earnings+cashflow 合计 15% → 35%，technical 15% → 5%
**代码位置**：`app/services/multi_factor_scorer.py:22-32`

> 完整权重说明见 [[Strategy/02-Factor-System]] 和 [[Strategy/11-Multi-Factor-Scoring]]

---

## 技术改进

### 1. PurgedKFold 实现
- 演示：普通 KFold 准确率 46%（含泄漏）vs PurgedKFold 50%（干净）
- 金融时间序列必须使用 Purge + Embargo 防止标签重叠泄漏
- 脚本：`scripts/purged_kfold_demo.py`

### 2. momentum_weights 参数加入 run_rotation_backtest
- 链路：`scripts/pure_alpha_stress_test.py` → `run_rotation_backtest` → `multi_factor_scorer`
- Walk-Forward Phase B 动量子权重搜索功能已可用

### 3. 回测自动加载 fundamentals_cache.json
- 当磁盘缓存无基本面数据时，自动从 `scripts/stress_test_results/fundamentals_cache.json` 加载
- 445 只股票盈利/现金流数据现已在回测中可用

---

## 相关文档

- [[Strategy/02-Factor-System]] — 因子权重详表
- [[Strategy/11-Multi-Factor-Scoring]] — 多因子打分系统详解
- [[Walk-Forward/10-Full-Strategy-WF-2026-03-22]] — Walk-Forward 最新结果
- [[Projects/V5-Roadmap-Detail]] — V5 路线图
