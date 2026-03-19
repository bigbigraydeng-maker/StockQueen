---
name: ML Enhancement Index
description: ML增强层文档索引
created: 2026-03-19
updated: 2026-03-19
tags: [ml, xgboost, ranking, index]
---

# ML 增强层

StockQueen Step 2：基于 XGBoost 的攻击型排序模型，优化选股能力。

## 核心定位

> **混合策略矩阵负责防守（regime/VIX/现金/止损），ML 负责进攻（找高增长赢家）。**

## 文档列表

| 文档 | 内容 |
|------|------|
| [[ML/01-Architecture]] | 两层架构设计、攻防分工、集成方式 |
| [[ML/02-Training-Validation]] | Walk-Forward 训练流程、A/B 测试方法论 |
| [[ML/03-Feature-Engineering]] | 特征定义（22维）、攻击型特征设计 |

## 快速链接

- 核心代码：`app/services/ml_scorer.py`
- 集成入口：`app/services/rotation_service.py`（`ml_enhance` 参数）
- 训练脚本：`scripts/ml_train_ab_test.py`
- 模型存储：`models/ml_ranker/ml_ranker.pkl`
- ML-V1结果：`scripts/stress_test_results/ml_ab_test_results.json`
- ML-V2结果：`scripts/stress_test_results/ml_ab_test_results_ml-v2.json`

## 开发状态

- [x] ML scorer 模块 ML-V1（防御型，reg:squarederror）
- [x] ML-V1 A/B 测试完成 → 结论：降回撤但降收益，方向错误
- [x] ML scorer 模块 ML-V2（攻击型，rank:pairwise + 攻击特征）
- [x] ML-V2 A/B 测试完成 → 结论见下
- [ ] ML-V3 设计（待定方向：非对称标签 / regime-aware）
- [ ] 根据结果决定是否上线实盘

## ML-V2 A/B 测试结论（2026-03-19）

**Sharpe改善但收益仍下降，攻击型改造力度不够。**

| 指标 | ML-V1 | ML-V2 |
|------|-------|-------|
| 平均Sharpe差值 | +0.06 | **+0.14** ✅ |
| 平均收益差值 | -7.3% | **-7.0%** ≈持平 |
| 回撤改善 | 5/5窗口 | 5/5窗口 ✅ |

**核心发现**：ML在崩盘环境（W1 2020）大幅跑赢，但在牛市中系统性拖累收益。
详见 → [[ML/04-AB-Test-Results]]

## ML-V1 → ML-V2 改造记录

| 维度 | ML-V1（防御型）| ML-V2（攻击型）|
|------|-----------|-----------|
| 标签 | 绝对收益 next_1w_return | 截面z-score（相对排名）|
| 目标函数 | reg:squarederror | rank:pairwise |
| 模型 | XGBRegressor | XGBRanker |
| 特征 | 17维（基础特征）| 22维（+5攻击型特征）|
| 学到的 | 选安全票 | 选爆发票 |
| ML-V1 结果 | Sharpe +0.06，收益 -7.3% | Sharpe +0.14，收益 -7.0% |
