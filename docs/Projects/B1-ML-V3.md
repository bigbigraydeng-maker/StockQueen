---
name: Project B1 - ML-V3
description: ML 增强层第三版：非对称标签 + Regime-aware 改造
created: 2026-03-19
updated: 2026-03-19
tags: [project, ml, v3, xgboost, active]
status: planning
---

# 🤖 Project B1：ML-V3 攻击型改造

## 为什么做这个

ML-V2 已证明方向正确（Sharpe +0.14），但**牛市中仍系统性拖累收益（-7.0%）**。
根本原因：22个特征权重均匀（~0.050 each），模型未真正学到"攻击信号比基础信号更重要"。

> 详细 A/B 分析 → [[ML/04-AB-Test-Results]]

---

## 🎯 目标

| 指标 | ML-V2（当前）| ML-V3（目标）|
|------|------------|------------|
| 平均 OOS 收益 vs Baseline | -7.0% ❌ | **≥ 0%（不拖累）** |
| 平均 OOS Sharpe vs Baseline | +0.14 ✅ | **+0.10 以上** |
| 牛市窗口收益（W2/W4/W5）| 系统性落后 | **最多落后 5%** |
| 模型上线实盘 | 否 | 通过后上线 |

---

## 🗺️ 三个改进方案

### 方案 A：非对称标签（推荐先试，最简单）

**原理**：在标签层面告诉模型"上行比下行更值钱"

```python
# 当前 ML-V2：截面 z-score（对称）
y = (ret - mean) / std

# ML-V3 方案A：非对称放大
y_raw = (ret - mean) / std
y = y_raw * 1.5 if y_raw > 0 else y_raw * 0.5
```

**预期效果**：模型在排序时优先把"涨得最猛"的票放前面

---

### 方案 B：Regime-aware 子模型（复杂度中等）

**原理**：牛市和熊市各自训练一个 XGBRanker

```
训练时分组：
  - bull/strong_bull 窗口 → 训练 bull_ranker（专注找爆发票）
  - bear/choppy 窗口 → 训练 bear_ranker（专注找稳定票）

推理时：
  if current_regime in [bull, strong_bull]: 用 bull_ranker
  else: 用 bear_ranker
```

---

### 方案 C：削减基础特征，强化攻击特征（快速实验）

**原理**：从 22 维去掉权重最低的基础特征，减少"稳定偏好"的噪音

```
待移除候选（ML-V2 中权重最低）：
  - volatility（和 upside_vol 重叠）
  - trend_score（和 rs_score 重叠）
  - regime_* one-hot（模型已隐式学到）

攻击特征比例：5/22(23%) → 目标 5/15(33%)
```

---

## ✅ 项目 Checklist

### Phase 0：前置条件
- [ ] **等待 FMP 迁移完成**（更大选股池 → ML 训练数据更丰富）
- [ ] 确认 `scripts/ml_train_ab_test.py` 可正常运行
- [ ] 确认 `scripts/stress_test_results/ml_ab_test_results_ml-v2.json` 存在（Baseline 对比基准）

### Phase 1：方案 A 实现（非对称标签）
- [ ] 修改 `scripts/ml_train_ab_test.py` 中标签计算逻辑
  - [ ] 找到 `cross_sectional_zscore` 计算处（约第 180 行）
  - [ ] 添加非对称放大：`y = y * 1.5 if y > 0 else y * 0.5`
  - [ ] 新增参数 `asymmetric: bool = True`（默认开启，可关闭对比）
- [ ] 更新输出文件名：`ml_ab_test_results_ml-v3a.json`
- [ ] 本地运行 5 窗口 A/B 测试（预计耗时 15-30 分钟）
- [ ] 对比结果：牛市窗口（W2/W4/W5）收益是否改善

### Phase 2：方案 B 实现（如方案 A 不够）
- [ ] 在训练数据中添加 `regime_group` 列（bull / non-bull）
- [ ] 实现双模型训练逻辑：`train_regime_aware_ranker()`
- [ ] 修改 `ml_scorer.py` 推理逻辑支持 regime-aware 切换
- [ ] 模型保存路径：`models/ml_ranker/bull_ranker.pkl` + `bear_ranker.pkl`
- [ ] 运行 A/B 测试对比

### Phase 3：方案 C 实现（特征裁剪，可与A/B叠加）
- [ ] 分析 ML-V2 最终窗口特征重要性（已记录在 [[ML/04-AB-Test-Results]]）
- [ ] 移除 `volatility`, `trend_score`, `regime_*` one-hot（共 6 个）
- [ ] 重新训练并运行 A/B 测试
- [ ] 对比 22 维 vs 16 维的排序质量（NDCG 指标）

### Phase 4：上线决策
- [ ] 任一方案通过上线标准（OOS 收益 ≥ Baseline，Sharpe ≥ Baseline）
- [ ] 更新 `ml_scorer.py` 到生产版本
- [ ] 在 `rotation_service.py` 中将 `ml_enhance` 默认改为 `True`
- [ ] Render 部署更新
- [ ] 写入 Obsidian 归档：[[ML/04-AB-Test-Results]] 添加 V3 结果

### Phase 5：归档
- [ ] 将本文档移至 `docs/Archive/` 目录
- [ ] 更新 [[Projects/00-Active-Projects]] 状态为 ✅
- [ ] 更新 [[ML/00-Index]] 开发状态勾选项

---

## ⚠️ 风险与注意事项

| 风险 | 说明 | 缓解措施 |
|------|------|---------|
| 选股池太小（<100只）| 训练数据不足，ML 无法学到足够区分度 | 等 FMP 迁移完成后再做 |
| 方案A过拟合牛市 | 非对称标签可能使熊市崩盘保护减弱 | 必须在 W1(2020 COVID) 窗口验证 |
| 与 Regime 防守层冲突 | ML 激进排序 vs bear 减仓保护 | ML 边界严格：仅排序 Top 10，不影响仓位 |

---

## 📎 相关文档

- [[ML/00-Index]] — ML 总索引
- [[ML/01-Architecture]] — 架构设计（ML边界定义）
- [[ML/02-Training-Validation]] — 训练流程
- [[ML/03-Feature-Engineering]] — 22维特征定义
- [[ML/04-AB-Test-Results]] — V1/V2 详细结果
- [[Projects/00-Active-Projects]] — 返回项目总览
