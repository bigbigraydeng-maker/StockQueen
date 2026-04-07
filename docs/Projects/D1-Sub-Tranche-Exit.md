---
name: D1 — Sub-Tranche 出场优化
description: ML驱动的Tranche B出场机制：镜像主策略入场，用Exit Scorer提前锁定利润，不增加额外资金
created: 2026-03-20
updated: 2026-03-21
tags: [project, sub-tranche, ml-exit, profit-locking, v5, active]
---

# D1 — Sub-Tranche 出场优化

## 项目背景

**问题**：主策略 ATR Trailing Stop（1.5×ATR）每笔盈利单平均吐回 1–2% 利润。
**动机**：眼看利润从峰值回撤，作为 trader 需要一个机制来锁住这部分。
**约束**：主策略骨架不能动（回测验证过的参数），不能影响整体策略的完整性。

**解决方案**：Sub-Tranche 机制 — 将每笔仓位拆为两份额，15% 的 Tranche B 由 ML Exit Scorer 驱动，争取在利润峰值附近提前出场。

---

## ✅ 实际进度（2026-03-21 核实）

> Obsidian 文档严重落后，以下为代码库实际状态：

### Phase 1 — 数据 + 标签 ✅ 完成
- [x] 生成训练集：`scripts/exit_scorer_training_data.csv`
- [x] 5,599 行样本（2018-2026），label=1: 795（14.2%），label=0: 4,804
- [x] 特征：pnl_drawdown_from_peak / unrealized_pnl_pct / rsi_14 / atr_ratio 等

### Phase 2 — 模型训练 ✅ 完成
- [x] XGBoost Classifier 训练：`models/exit_scorer/exit_scorer.pkl`
- [x] Walk-Forward 验证（5窗口）：avg F1=0.42，avg Precision=0.39，avg Recall=0.47
- [x] 生产阈值：**THRESHOLD=0.65**（代码锁定，D1规格一致）
- [x] 特征文件：`models/exit_scorer/feature_names.json`

### Phase 3 — 系统集成 ✅ 完成（信号采集模式）
- [x] `app/services/exit_scorer.py` — 每日推理服务
- [x] Scheduler **Job 4e**：Tue-Sat 09:46 NZT 自动运行
- [x] 信号写入 `exit_scorer_signals` 表（Supabase）
- [x] **当前模式：信号采集，不执行交易**

### Phase 4 — 验证观测期 🟡 进行中
- [ ] 累积足够信号数据（目前表为空，阈值0.65较严，信号少）
- [ ] 对比：ML 出场时机 vs ATR 最终出场价
- [ ] 连续 4 周观测后决定是否开启 Tranche B 实际执行

---

## ❌ 尚未开发（Phase 3 剩余 + 执行层）

| 功能 | 说明 |
|------|------|
| Tranche B 实际平仓 | 85%/15% 拆仓 + 信号触发时 Tiger 自动卖出 15% |
| `sub_trades` 表 | Supabase 独立记录 Tranche B 交易（表尚未创建） |
| `portfolio_manager.py` Tranche 分配 | 建仓时自动拆分逻辑 |

> 开启条件：观测期满 4 周，且 exit_prob > 0.65 信号精度可接受

---

## 关键决策（2026-03-20 定稿）

| 决策点 | 结论 |
|--------|------|
| 入场方式 | 完全镜像主策略，自动化 |
| 资金来源 | 总资金内 15%，不额外注资 |
| 运行方式 | 全自动，每日盘后与主策略同步 |
| 当前状态 | 信号采集模式，等待观测期数据 |

---

## 关键参数

| 参数 | 当前值 | 可调范围 |
|------|--------|---------|
| `SUB_RATIO` | 0.15 | 0.10–0.20 |
| `EXIT_THRESHOLD` | **0.65** | 0.60–0.75 |
| `MIN_PNL_TO_ACTIVATE` | +0.5% | +0.3–+1.0% |
| `FORWARD_WINDOW` | 3天 | 2–5天 |

---

## 关联文档

- [[Strategy/17-Sub-Tranche-Exit-Strategy]]
- [[ML/05-Exit-Scorer]]
- [[ML/00-Index]]
