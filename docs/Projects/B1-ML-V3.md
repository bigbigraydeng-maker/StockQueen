---
name: Project B1 - ML-V3
description: ML 增强层第三版：非对称标签 + Regime-aware 改造
created: 2026-03-19
updated: 2026-03-20
tags: [project, ml, v3, xgboost, completed]
status: completed
---

# 🤖 Project B1：ML-V3 攻击型改造 ✅ 已完成

> **完成日期：2026-03-20**
> 详细结果 → [[ML/04-AB-Test-Results]]

## 最终结果（V3A 非对称标签）

| 指标 | ML-V2（旧）| ML-V3A（上线）|
|------|------------|------------|
| 平均 Sharpe vs Baseline | +0.14 | **+0.83** ✅ |
| 平均收益 vs Baseline | -7.0% | -4.3%（动态池） |
| 平均回撤改善 | 小幅 | **-13.5pp（砍半）** ✅ |
| W5(2024) 收益 | +17.5% | **+104.4%** ✅ |
| W5(2024) Sharpe | 1.34 | **3.07** ✅ |
| 生产上线 | 否 | **是** ✅ |

---

## 为什么做这个

ML-V2 已证明方向正确（Sharpe +0.14），但**牛市中仍系统性拖累收益（-7.0%）**。
根本原因：22个特征权重均匀（~0.050 each），模型未真正学到"攻击信号比基础信号更重要"。

---

## ✅ 完整 Checklist

### Phase 0：前置条件
- [x] 动态选股池已完成（500-600只 >> 训练数据大幅丰富）
- [x] `scripts/ml_train_ab_test.py` 可正常运行
- [x] V2 基准文件存在：`ml_ab_test_results_ml-v2.json`

### Phase 1：方案 A 实现（非对称标签）✅
- [x] 修改 `app/services/ml_scorer.py` 中 `build_training_data()`
  - [x] 添加 `asymmetric: bool = False` 参数
  - [x] 实现：`z_score = z_raw * 1.5 if z_raw > 0 else z_raw * 0.5`
- [x] 新增脚本：`scripts/ml_train_ab_test_v3.py`
- [x] 结果保存至：`ml_ab_test_results_ml-v3a.json`
- [x] 5窗口 Walk-Forward A/B 测试完成（耗时约90分钟）
- [x] 关键验证：W5 Sharpe 3.07，回撤 8.1%，收益 +104.4%

### Phase 2：方案 B（Regime-aware）
- [ ] 暂不实施（V3A 已足够优秀）

### Phase 3：方案 C（特征裁剪）
- [ ] 暂不实施（V3A 回撤改善已超预期）

### Phase 4：上线 ✅
- [x] `ml_scorer.py` 支持非对称标签（asymmetric参数）
- [x] `rotation_watchlist.py` 新增 `USE_ML_ENHANCE=True` / `ML_RERANK_POOL=10`
- [x] `rotation_service.py` 集成 ML 重排到 `run_rotation()` 生产路径
  - [x] 添加 `_get_live_ml_ranker()` 懒加载单例
  - [x] `_score_ticker()` 支持 `ml_store` 参数存储完整 scorer_result
  - [x] `run_rotation()` 在选股后注入 `ml_rerank_candidates()`

### Phase 5：归档 ✅
- [x] `ML/04-AB-Test-Results.md` 更新 V3A 全部结果
- [x] `Projects/00-Active-Projects.md` 状态改为 ✅
- [x] 本文档状态更新为 completed

---

## 上线配置

```python
# app/config/rotation_watchlist.py
USE_ML_ENHANCE: bool = True
ML_RERANK_POOL: int = 10

# 生产路径：run_rotation() → _score_ticker(ml_store=...) → ml_rerank_candidates()
# 模型路径：models/ml_ranker/ml_ranker.pkl（懒加载，首次调用时读入）
```

---

## 相关文档

- [[ML/04-AB-Test-Results]] — V1/V2/V3A 完整结果
- [[ML/00-Index]] — ML 总索引
- [[ML/03-Feature-Engineering]] — 22维特征定义
- [[Projects/00-Active-Projects]] — 返回项目总览
