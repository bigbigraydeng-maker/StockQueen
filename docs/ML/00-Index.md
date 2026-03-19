---
name: ML Enhancement Index
description: ML增强层文档索引
created: 2026-03-19
updated: 2026-03-20
tags: [ml, xgboost, ranking, index]
---

# ML 增强层

StockQueen Step 2：基于 XGBoost 的攻击型排序模型，优化选股能力。

## 核心定位

> **混合策略矩阵负责防守（regime/VIX/现金/止损），ML 负责进攻（找高增长赢家）。**

## 🟢 当前生产状态（2026-03-20）

**ML-V3A 已上线**：非对称标签 XGBRanker，滑动18个月窗口每月1日自动重训。

| 指标 | 值 |
|------|----|
| 生产模型 | `models/ml_ranker/ml_ranker.pkl` |
| 标签 | 非对称 z-score（正×1.5, 负×0.5）|
| 平均 Sharpe vs Baseline | **+0.83** |
| 平均回撤改善 | **-13.5pp（砍半）** |
| 下次自动重训 | 每月1日 13:00 NZT |
| Bear 熊市 | **自动关闭**（池子仅5只防御ETF，特征失效）|

### ML 启用条件

| Regime | ML 重排 | 理由 |
|--------|--------|------|
| `strong_bull` / `bull` | ✅ 启用 | 50-100+ 只成长股，区分度高 |
| `choppy` | ✅ 启用 | 30-50 只混合池，有区分度 |
| `bear` | ❌ 关闭 | 仅5只防御ETF，攻击型特征无意义 |

## 文档列表

| 文档 | 内容 |
|------|------|
| [[ML/01-Architecture]] | 两层架构设计、攻防分工、集成方式 |
| [[ML/02-Training-Validation]] | Walk-Forward 训练流程、A/B 测试方法论 |
| [[ML/03-Feature-Engineering]] | 特征定义（22维）、攻击型特征设计 |
| [[ML/04-AB-Test-Results]] | V1/V2/V3A 完整 A/B 结果 |

## 快速链接

- 核心代码：`app/services/ml_scorer.py`（`build_training_data(asymmetric=True)`）
- 集成入口：`app/services/rotation_service.py`（`run_ml_retrain()` / `ml_enhance`）
- 手动重训端点：`POST /rotation/ml/retrain?months_lookback=18`
- V3A 训练脚本：`scripts/ml_train_ab_test_v3.py`
- 模型存储：`models/ml_ranker/ml_ranker.pkl`
- V3A结果：`scripts/stress_test_results/ml_ab_test_results_ml-v3a.json`

## 开发状态

- [x] ML-V1（防御型）→ 结论：降回撤但降收益，方向错误
- [x] ML-V2（攻击型 XGBRanker）→ Sharpe +0.14 但收益 -7%，牛市仍落后
- [x] ML-V3A（非对称标签）→ Sharpe +0.83，回撤砍半，**✅ 已上线生产**
- [x] 月度自动重训系统（每月1日 13:00 NZT 滑动18个月窗口）
- [ ] ML-V3B（Regime-aware 子模型）— 备选，V3A 已够用暂不做
- [ ] 特征扩展：财报超预期（FMP EPS）、新闻情绪（AV NEWS_SENTIMENT）作为新特征

## 版本演进一览

| 版本 | 标签 | 目标函数 | 特征 | Sharpe差值 | 收益差值 | 状态 |
|------|------|---------|------|-----------|---------|------|
| V1 | 绝对收益 | reg:squarederror | 17维 | +0.06 | -7.3% | 退役 |
| V2 | 截面z-score | rank:pairwise | 22维 | +0.14 | -7.0% | 退役 |
| **V3A** | **非对称z-score** | rank:pairwise | 22维 | **+0.83** | -4.3% | **✅ 生产** |
