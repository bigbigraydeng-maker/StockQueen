---
name: Phase 1.5 幸存者偏差修复计划
created: 2026-03-19
updated: 2026-03-21
tags: [walkforward, survivorship-bias, v5, phase1.5, roadmap]
---

# Phase 1.5：幸存者偏差修复（上线前必做）

← [[Walk-Forward/05-V5-Next-Steps|V5 Next Steps]] | [[Walk-Forward/06-Sub-Strategy-WF-Validation|子策略验证]]

---

## 背景与决策（2026-03-19）

用户确认采用方案 B：**修复幸存者偏差后再上线**。

### 当前 WF 的偏差来源

```
walk_forward_v5_full.py
  └─ _fetch_backtest_data("2018-01-01", "2024-12-31")
       └─ RC.USE_DYNAMIC_UNIVERSE = True
            └─ UniverseService().get_universe_items()
                 └─ 读取 .cache/universe/universe_latest.json
                      ← 这是「2026年3月今天」筛选出来的 ~500 只
```

**问题**：用 2026 年还活着的 500 只股票，回测 2018-2024 年的表现。
- 2021 年后才上市的股票被错误纳入 2018 年的回测
- 已退市的垃圾股（通常是大跌后退市）被完全排除

### 当前结果的可信度评估

| 策略 | 当前 OOS 夏普 | 偏差影响 | 修正后预期范围 |
|------|------------|---------|------------|
| V4 趋势 | 2.33 | 中等（ETF 为主，无退市偏差） | 1.6~2.0 |
| MR 均值回归 | 0.959 | 较高（更依赖个股） | 0.6~0.8 |
| ED 事件驱动 | 0.393 | 较高（个股更多） | 0.2~0.4 |

---

## 实现方案：两层架构

### Tier 1 — 快速修复（2-3天，现在执行）

**目标**：消除 Future IPO Bias（最主要的幸存者偏差来源）

**方法**：
```python
# universe_service.py 新增方法
async def get_pit_universe(self, as_of_year: int) -> list:
    """
    Point-in-Time Universe: 返回 {as_of_year}-01-01 时真实上市的股票
    调用 Massive LISTING_STATUS 接口
    过滤：NYSE/NASDAQ + IPO < as_of_year-01-01 - 365天
    """
```

**修改 rotation_service._fetch_backtest_data**：
```python
# 为每个 WF 年份构建当年的正确股票名单
# 与已有 OHLCV 缓存取交集
# 不再使用 universe_latest.json（2026年的）
```

**API 消耗**：7次 LISTING_STATUS 调用（2018-2024 各一次），每次返回 ~7000 行，极快

**消除偏差**：Future IPO Bias（将可信度提升 60-70%）
**未消除**：已退市股票数据缺失（Tier 2 解决）

---

### Tier 2 — 完整修复（Phase 5 Massive 迁移后）

**目标**：获取已退市股票的历史 OHLCV，彻底消除幸存者偏差

| 维度 | 数值 |
|------|------|
| 已退市但历史上存在的股票 | ~1500-2000 只/年 |
| 额外 API 调用需求 | ~14,000 次 |
| 旧速率（AV 75次/分） | 约 21 小时，不可行 |
| Massive 速率（750次/分） | 约 2 小时，可行 ✅ |

**结论**：Tier 2 在 Phase 5 Massive 迁移完成后即可执行（不再阻塞）

---

## 开发清单（Tier 1）

- [ ] `app/services/universe_service.py`
  - [ ] 新增 `async def get_pit_universe(as_of_year: int) -> list`
  - [ ] 缓存为 `.cache/universe/universe_pit_{YYYY}.json`

- [ ] `app/services/rotation_service.py`
  - [ ] 修改 `_fetch_backtest_data` 接受 `pit_year` 参数
  - [ ] WF 模式下按年份加载对应 PIT universe

- [ ] `scripts/walk_forward_v5_full.py`
  - [ ] 每个窗口使用对应年份的 PIT universe
  - [ ] 重跑全部 5 个窗口

- [ ] 更新 Obsidian 结果文档（本文档 + [[Walk-Forward/03-V4-Final-Results]]）

---

## 路线图定位

```
Phase 1   Walk-Forward（初步验证）  ✅ 完成（含偏差）
Phase 1.5 幸存者偏差修复 Tier 1    ✅ 完成
Phase 2   动态选股池接入             ✅ 完成
Phase 3   AI 事件信号                ✅ 完成
Phase 4   订阅产品                   ✅ 完成
Phase 5   Massive 数据源迁移         🟡 进行中
Phase 1.5 幸存者偏差修复 Tier 2    ⏳ Phase 5 完成后立即执行
```

## 推荐执行顺序

```
现在（进行中）
  → Phase 5 Massive 迁移（massive_client.py 开发）
  → 迁移完成后立即执行 Phase 1.5 Tier 2（退市股历史数据）

已完成
  → Phase 1.5 Tier 1（PIT Step1，重跑 WF）
  → 宝典V4 模拟实盘（4仓已开）

上线后（第1-3个月）
  → Phase 1.5 Tier 2 完整验证
  → Newsletter 正式对外推广
```

---

## 关键决策点（Phase 1.5 Tier 1 完成后）

> **修正后 WF 结果的分叉**：
> - V4 OOS 夏普 > 1.5 → 上线，正常仓位
> - V4 OOS 夏普 1.0~1.5 → 上线，减仓 30%，3个月复查
> - V4 OOS 夏普 < 1.0 → 暂停，排查因子/时间段问题
> - MR/ED 夏普降幅 > 50% → 降权重或暂停该子策略
