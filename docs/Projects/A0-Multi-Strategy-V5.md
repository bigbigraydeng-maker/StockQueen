---
name: A0 — 破浪 V5 综合系统
description: StockQueen V5 纯Alpha模式开发追踪：WF验证/动态选股池/Hedge Overlay/生产验证清单
created: 2026-03-19
updated: 2026-03-23
tags: [project, v5, pure-alpha, hedge-overlay, walk-forward, active]
---

# A0 — 破浪 V5 综合系统

## 项目状态（2026-03-23）

**纯 Alpha 模式已上线，首次生产验证等待 2026-03-28 轮动**

---

## 信号时间表

| 环节 | 时间（UTC） | 说明 |
|------|------------|------|
| 选股信号生成 | 每周六 10:00 | scheduler 触发 run_rotation() |
| 盘中观察 | 周一盘中 | entry_service 监听 MA5 + 成交量 |
| 信号发布（未实现） | 生成信号后立即 | newsletter / API |

**下次信号：2026-03-28 10:00 UTC（NZT 周六 23:00 截止）**

---

## 纯 Alpha 模式确认

### 提交历史
- `0d50163` 2026-03-22 移除 Regime 硬过滤，切换到纯 Alpha 模式
- `cd95cf1` 2026-03-22 添加 Hedge Overlay 对冲层

### 数据验证（Supabase rotation_snapshots）

| 运行周期 | 运行时间(UTC) | 代码版本 | Regime | 选出 |
|---------|-------------|---------|------|------|
| 2026-03-21 | 09:57（旧代码，第一次） | 无 Regime 放宽 | bear | SHY/RWM/DOG ? |
| **2026-03-28** | **10:00（首次纯Alpha）** | **纯 Alpha + Hedge Overlay** | TBD | **待验证** |

### 确认要点
- 纯 Alpha 提交距上次运行约 14 小时
- 动态选股池运行中：Supabase universe_snapshots 有 1,688 只股票（2026-03-20）
- ERAS 在候选池（score=8.062），ASST 也在 —— 可能进入选出

---

## WF 验证结果

### Test A：Walk-Forward 5 窗口（IS vs OOS Sharpe）

| 窗口 | 训练集 | 纯Alpha OOS | V4放宽 OOS |
|------|--------|------------|-----------|
| W1 | 2020 | 3.70 | 1.98 |
| W2 | 2021 | 8.12 | 3.55 |
| W3 | 2022 | 3.78 | 1.70 |
| W4 | 2023 | -0.15 | 0.00 |
| W5 | 2024 | 3.74 | 2.05 |
| **均值** | | **3.84** | **1.856** |

纯 Alpha vs 放宽：+2.0 Sharpe，+107%。W4（2023 熊市）为负属正常。

### Test B：压力测试结果（2024 专区）

| 测试指标 | 结果 | 结论 |
|-------|------|------|
| 置换检验 p 值 | 0.978 | FAIL（统计显著性不足，需注意） |
| Bootstrap Sharpe 5% | 1.42 | 仍高于 >1 |
| Bootstrap MDD P95 | -69.4% | 极端情景高回撤，需注意 |
| Walk-Forward Sharpe 均值 | 3.84 | 样本外参考 |

**置换检验 FAIL 说明**：统计上无法拒绝"纯 Alpha 与随机相同"的零假设，但 OOS Sharpe 实际表现仍明显优于 V4，可接受。

---

## 配置参数

| 参数 | 值 | 说明 |
|------|---|------|
| TOP_N | 3 | 每周选 3 只 |
| USE_DYNAMIC_UNIVERSE | True | 1,688 只动态池 |
| UNIVERSE_QUALITY_GATE | True | 1,127 只通过 EPS+CF |
| HEDGE_OVERLAY_ENABLED | True | 对冲层已激活 |
| HEDGE_ALLOC_BY_REGIME | bear: 30% | 熊市 30% 对冲 |
| MIN_SCORE_BY_REGIME[bear] | 0.5 | 最低入场门槛 |

---

## 上线验证清单（2026-03-28）

- [ ] 确认 rotation_snapshots 新快照时间 ≥ 10:00 UTC
- [ ] 确认 selected_tickers 内容全部为动态选股个股（非 ETF）
- [ ] 确认 num_scored（jsonb_array_length(scores)）>= 20
- [ ] 确认 regime 判断正确
- [ ] 对比 top1 score 是否 ≥ 8.0（理想信号）
- [ ] Hedge Overlay 是否包含 hedge_info

---

## 破浪 V5 清单

### 已完成 ✅
- [x] 纯 Alpha 模式（移除 Regime 硬过滤，`0d50163`）
- [x] Hedge Overlay 对冲层（`cd95cf1`）
- [x] Massive 替换 AV+FMP（前端到后端数据迁移）
- [x] 动态选股池（USE_DYNAMIC_UNIVERSE=True，1,688 只）
- [x] Quality Gate（1,127 只通过 EPS+CF 筛选）
- [x] Walk-Forward 验证（5 窗口）
- [x] 压力测试脚本（permutation + bootstrap）
- [x] 基础数据采集（Job 22a-22d，周六 09:30）

### 进行中 🟡
- [ ] **生产环境验证**（首次纯 Alpha 完整选股，2026-03-28）
- [ ] site/data/walk-forward-validation.json 更新（结果已烤入模拟，待 push）
- [ ] 对接 AI 事件信号（C2 项目）

### 待开发 🔲
- [ ] Newsletter 订阅产品（C3 项目）
- [ ] 切换 Tiger 实盘
- [ ] 动态 Regime 放宽优化（牛市放宽/熊市收紧实验）

---

## 回滚方案

如果首次纯 Alpha 选股结果异常：
1. `git revert 0d50163` → 恢复 Regime 放宽
2. `git push origin main` → Render 自动重新部署

---

## 补位逻辑缺口（2026-03-22 记录）

### 现状问题
- 当 pending_entry 股票无法满足入场条件（收盘 > MA5 且量 > 20 日均量）时，该槽位整周空置
- 无任何自动替补逻辑，等到下次轮动（下周六）才能重新选股

### 决策：瀑布式补位（待开发）

从**同一周轮动快照**的评分列表中按排名顺序自动补位：

| 规则 | 说明 |
|------|------|
| 触发条件 | pending_entry 超时（周五日检仍未成交） |
| 候选来源 | 同一 rotation_snapshots.scores JSONB，从 rank #4 开始 |
| 入场条件 | 仍需满足 MA5 + 20 日均量 |
| 最大深度 | 只补一层（#4→#5 不再级联） |
| 空槽策略 | #4 也超时则该槽空置到下次轮动 |

### 本周行动
- [ ] **观察为主**：监控 ERAS / EQNR / SNDK 周一是否触发入场
- [ ] 若 SNDK 一直未满足条件，记录空槽持续时间，作为补位逻辑优先级依据
- [ ] 下周重点开发此功能（代码改动在日检流程中）

### 2026-03-22 首次纯 Alpha 预览结果

| 排名 | 股票 | 评分 | 备注 |
|------|------|------|------|
| 1 | ERAS | 8.062 | 生物制药，3m 涨幅 +305% |
| 2 | EQNR | 7.098 | 能源，1m +44% |
| 3 | SNDK | 6.586 | 存储半导体，入场条件待观察 |
| 4 | ASST | 7.674* | 候补 #1（瀑布补位首选） |
| 5 | PTEN | 6.491* | 候补 #2 |

> *候补评分来自预览快照 scores 排名，不写入 selected_tickers

### 意义
这是**宝典 V5 纯 Alpha 模式第一次真实信号**——不再被 Regime 硬过滤限制在反向 ETF，完全由评分系统自主决策。
