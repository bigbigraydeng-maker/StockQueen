---
name: Sub-Tranche 出场优化策略
description: 用 ML 出场信号将每笔仓位拆分为 Tranche A（主策略）+ Tranche B（早出场锁利润），同总资金内运作
created: 2026-03-20
updated: 2026-03-23
tags: [strategy, sub-tranche, exit-optimization, ml, profit-locking]
---

# Sub-Tranche 出场优化策略

## 核心定位

> **主策略骨架不动，在每笔仓位内拆出一个 ML 驱动的 Tranche，争取在峰值附近提前锁定利润。**

这不是独立子账号，而是同一笔资金内的**双份额机制**：

```
每笔仓位 = Tranche A（85%）+ Tranche B（15%）
  Tranche A → 跟随主策略 ATR Trailing Stop，不动
  Tranche B → 跟随 ML 出场评分，独立提前出场
```

### 存在的核心价值

主策略的 Trailing Stop = 1.5 × ATR14 from 最高价。  
这意味着每笔盈利单**平均吐回 1–2% 的利润**才触发出场。

Tranche B 的使命就是：**抓住这 0.5–1% 的差值**，复利累积形成真实 alpha。

---

## 策略结构

### 资金分配

| 参数 | 值 | 说明 |
|------|-----|------|
| `SUB_RATIO` | **15%** | Tranche B 占每仓的比例 |
| 主策略 Tranche A | 85% | 完全跟随现有逻辑，绝不改动 |
| 独立资金 | 无 | Sub Tranche 在总资金内，不额外注资 |

**示例**（总资金 $100K，TOP_N=5，每仓 $20K）：
- Tranche A = $17,000 → 跟随 ATR Trailing Stop
- Tranche B = $3,000 → 跟随 ML 出场信号

### 入场规则

**完全镜像主策略**：rotation_service 触发建仓时，A/B 两份额同时按比例自动入场。  
不引入任何独立选股逻辑。

### 出场规则

| | Tranche A | Tranche B |
|-|-----------|-----------|
| 出场信号 | 主策略 ATR Trailing Stop（不变） | ML Exit Scorer ≥ THRESHOLD |
| 出场时机 | 盘后自动（现有逻辑） | 盘后自动（新增逻辑） |
| 主策略 ATR 止损触发时 | 平仓 | 若 B 尚未出场，同步平仓 |

**激活条件**（防止一入场就被扫出）：  
`unrealized_pnl_pct > +0.5%` 时，ML 出场评分才生效。

### 重新入场

**V1 版本（当前）**：Tranche B 出场后等待主策略下次入场信号，不独立重新入场。  
**V2 版本（未来）**：评估 ML 是否有能力判断回调底部并重建仓。

---

## 关键参数

| 参数 | 初始值 | 说明 |
|------|--------|------|
| `SUB_RATIO` | 0.15 | B 份额占比 |
| `EXIT_THRESHOLD` | 0.65 | ML 出场概率触发线 |
| `MIN_PNL_TO_ACTIVATE` | +0.5% | 最低浮盈门槛，激活 ML 扫描 |
| `FORWARD_WINDOW` | 3天 | ML 标签预测窗口 |

---

## 风险控制

### 最坏情况分析

| 场景 | 对总组合影响 |
|------|------------|
| ML 完全失效（Tranche B 每笔都早出） | 最多拖累总组合 15% × 主策略持仓利润 |
| Tranche B 亏损 | B 占 15%，总组合最大额外亏损 ≤ 1.5%（相对主策略） |
| ML 完全正确 | 每笔省下约 1–2% 吐回，复利可观 |

### 可接受亏损上限

```
Sub Tranche 月亏损超过 5–7%（仓内）→ 暂停 ML 出场，退回全量 ATR 止盈
```

---

## P&L 核算

- Tranche A 和 Tranche B **分别记录**盈亏，合并入总收益曲线
- 月末对比：Tranche B 是否持续优于"持有到 ATR 止盈"的基准
- 评估指标：`B_exit_price vs A_exit_price`（B 出场早且价格更高 = 有效）

---

---

## 当前上线状态（2026-03-23）

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1 — 数据标签 | ✅ 完成 | 5,599 行样本（2018-2026） |
| Phase 2 — 模型训练 | ✅ 完成 | XGBoost，avg F1=0.42 |
| Phase 3 — 系统集成 | ✅ 完成（信号采集模式）| Job 4e 每日 09:46 NZT 运行 |
| Phase 4 — 验证观测期 | 🟡 进行中 | 信号写入 exit_scorer_signals，暂不执行交易 |
| Tranche B 实际执行 | 🔲 待开发 | 观测期满 4 周后决定是否开启 |

> **当前结论**：策略文档和代码设计完整，但 **Tranche B 实际拆仓/平仓功能尚未开发**。
> 现在运行的是信号采集模式，ML 出场评分每日产出但不触发任何订单。
> 详见项目追踪：[[Projects/D1-Sub-Tranche-Exit]]

## 关联文档

- [[ML/05-Exit-Scorer]] — ML 出场评分模型设计
- [[Projects/D1-Sub-Tranche-Exit]] — 项目开发计划
- [[Strategy/10-Stop-Loss-Take-Profit]] — 主策略 ATR Trailing Stop 详情
- [[Strategy/13-Sub-Strategies]] — 现有三策略体系
