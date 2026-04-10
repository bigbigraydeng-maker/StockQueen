---
name: 铃铛策略（盘中动能）执行与迭代
description: 杠杆账户 30min 多因子评分、自动开仓、止损/括号止盈、池子分层与入场确认
type: reference
created: 2026-04-02
updated: 2026-04-02
tags: [intraday, bell, momentum, trading, active]
status: ACTIVE
---

# C5 — 铃铛策略（盘中动能）

## 目标

在美东交易时段，对固定股票池做 **30 分钟** 量价因子评分，在 **Tiger 杠杆账户** 上可选自动执行；与 **宝典 V5 日频** 解耦。

## 当前实现（代码入口）

| 模块 | 路径 |
|------|------|
| 参数 | `app/config/intraday_config.py` |
| 股票池 | `app/config/intraday_universe.py` |
| 评分 | `app/services/intraday_service.py`、`intraday_scorer.py` |
| 执行 | `app/services/intraday_trader.py` |
| 建仓确认 | `app/services/intraday_entry_confirm.py` |
| 动能落库 | `app/services/intraday_momentum_store.py`（`intraday_rounds` / `intraday_momentum_daily`） |
| 调度 | `app/scheduler.py`（`intraday_scoring`、5min 减仓等） |

## 2026-04-02 已落地

1. **池子分层**：`INTRADAY_AUTO_ENTRY_DENY` — ETF + 超大盘仍参与评分与 SPY 相对强弱，**禁止自动开仓**，减轻「大盘股 30min 信号滞后、上行空间不足」问题。
2. **入场确认**（可 `ENTRY_CONFIRM_ENABLED` 关闭）：近 N 根 30min **阳线比例** + **收盘价距近 N 根最高价** 不过远，减轻追高。
3. **ATR 止盈倍数**：`TAKE_PROFIT_ATR_MULT` 降至 **1.8**（仅在**关闭**括号止盈、Pass C 生效时有意义）。
4. 其他已有机理：括号止盈 +0.5%、软件止损约 −0.3%、空位立即全市场重扫、`intraday_scores` + 动能表。

## Roadmap（下一步）

| 优先级 | 项 | 说明 |
|--------|----|------|
| P1 | 池子量化筛选 | `scripts/refresh_intraday_universe.py`：ADV、20 日日内振幅、ATR% 阈值，人工确认后覆写名单 |
| P2 | 10～15min 主周期或 TopN 短周期确认 | 全池降周期成本高；优先对候选拉 5～10min 二次确认 |
| P3 | 分层括号止盈 | 高波动 vs 低波动不同 `ENTRY_BRACKET_TAKE_PROFIT_PCT` |
| P4 | 回踩 VWAP 入场 | 状态机：高分 → 等待回踩 → 下单 |

## 相关文档

- [[Data-Infrastructure]] — `intraday_scores` / `intraday_rounds` / `intraday_momentum_daily`
- [[LEVERAGE_ACCOUNT_SETUP]]（若存在）— 杠杆账户与 Lab
