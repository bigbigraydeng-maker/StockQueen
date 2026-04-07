---
name: Strategy Index
description: 策略文档总索引：核心策略系统/轮动逻辑/风控/子策略/AI/回测结果
type: reference
created: 2026-03-19
updated: 2026-03-21
tags: [index, strategy]
---

# Strategy 策略文档总索引

## 核心参数

| # | 文档 | 说明 |
|---|------|------|
| 01 | [[01-Current-Strategy-Overview]] | 当前策略总览 |
| 02 | [[02-Factor-System]] | 因子系统设计 |
| 03 | [[03-Rotation-Logic]] | 轮动逻辑 |
| 04 | [[04-Risk-Management]] | 风控参数规范 |
| 05 | [[05-Stock-Pool]] | 选股池说明 |
| 06 | [[06-Multi-Strategy-Matrix]] | 多策略矩阵 |
| 07 | [[07-Known-Issues]] | 已知问题 |
| 08 | [[08-V4-vs-V5-Comparison]] | V4 vs V5 对比 |
| 09 | [[09-Regime-System]] | Regime 体制系统 |

## 深度专题

| # | 文档 | 说明 |
|---|------|------|
| 10 | [[10-Stop-Loss-Take-Profit]] | 止盈止损详解（ATR/Trailing/体制对比） |
| 11 | [[11-Multi-Factor-Scoring]] | 9因子评分系统详解（权重/公式/Regime调节） |
| 12 | [[12-AI-Components]] | AI与机器学习系统（DeepSeek/RAG/XGBoost/Claude） |
| 13 | [[13-Sub-Strategies]] | 子策略详解：均值回归 + 事件驱动 |
| 14 | [[14-Stock-Pool-Universe]] | 选股池完整说明（5类池 + Regime筛选规则） |
| 15 | [[15-Backtest-Results]] | 回测结果与参数稳定性（WF 6窗口OOS） |
| 16 | [[16-Midweek-Replacement]] | 周中补位机制（ATR漂移验证 + 效率优化） |
| 17 | [[17-Sub-Tranche-Exit-Strategy]] | Sub-Tranche 出场策略（D1项目文档） |
| DU | [[15-Dynamic-Universe]] | 动态选股池（1578只，USE_DYNAMIC_UNIVERSE=True） |

## 快速导航

- **止盈止损怎么算？** → [[10-Stop-Loss-Take-Profit]]
- **因子权重有哪些？** → [[11-Multi-Factor-Scoring]]
- **AI/ML 做什么？** → [[12-AI-Components]]
- **均值回归什么时候开？** → [[13-Sub-Strategies]]
- **Bear 市买什么？** → [[14-Stock-Pool-Universe]]
- **回测数据来源？** → [[15-Backtest-Results]]
- **Regime 如何切换？** → [[09-Regime-System]]
- **周中出场补位怎么做？** → [[16-Midweek-Replacement]]
- **当前锁参数据？** → TOP_N=3, HOLDING_BONUS=0.0, ATR_STOP=1.5（WF验证锁定）
