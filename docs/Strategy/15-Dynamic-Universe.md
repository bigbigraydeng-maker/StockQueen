---
name: Dynamic Universe
description: 动态选股池设计、筛选逻辑、A/B验证结果
created: 2026-03-19
updated: 2026-03-19
tags: [strategy, universe, dynamic, screening]
---

# 动态选股池（Dynamic Universe）

← [[Strategy/00-Index|返回策略索引]]

---

## 核心思路

静态池（479只手工挑选）覆盖面有限，容易错过高增长机会。
动态池从全美上市股票中自动筛选，每周刷新，扩大alpha来源。

## 筛选漏斗

| 步骤 | 过滤条件 | 数量 |
|------|---------|------|
| Step 0 | AV LISTING_STATUS 全部活跃股票 | ~13,200 |
| Step 1 | 交易所过滤（NYSE/NASDAQ/ARCA） | ~6,500 |
| Step 2 | 日均量 > 50万 + 价格 > $5 | ~1,900 |
| Step 3 | 市值 > $2B（AV OVERVIEW API） | **~1,578** |

### 配置参数（RotationConfig）

```python
UNIVERSE_MIN_MARKET_CAP = 500_000_000   # $500M（实际用 $2B）
UNIVERSE_MIN_AVG_VOLUME = 500_000       # 20日均量
UNIVERSE_MIN_LISTED_DAYS = 365          # 上市满1年
UNIVERSE_MIN_PRICE = 5.0                # 最低股价
USE_DYNAMIC_UNIVERSE = True             # 已启用
```

## 行业分布（2026-03-19）

| 行业 | 数量 |
|------|------|
| TECHNOLOGY | 258 |
| HEALTHCARE | 253 |
| FINANCIAL SERVICES | 212 |
| INDUSTRIALS | 192 |
| CONSUMER CYCLICAL | 186 |
| ENERGY | 111 |
| REAL ESTATE | 105 |
| BASIC MATERIALS | 79 |
| COMMUNICATION SERVICES | 71 |
| CONSUMER DEFENSIVE | 65 |
| UTILITIES | 46 |

## A/B 验证结果（2026-03-19）

回测期间：2020-01-01 至 2026-03-01

| 指标 | 静态池 (479) | 动态池 (1,578) | 差值 |
|------|-------------|---------------|------|
| **总收益** | +2,355.9% | +9,744.3% | +7,388.4% |
| **年化收益** | 75.5% | 124.0% | +48.5% |
| **Sharpe** | 2.29 | 3.15 | +0.86 |
| **最大回撤** | -25.8% | -24.0% | -1.8% |
| **胜率** | 56.4% | 54.0% | -2.4% |
| **Alpha vs SPY** | +2,183% | +9,571% | +7,388% |

### 关键发现

- 动态池新发现 **376只有效标的**
- 收益 4.1 倍提升，Sharpe +0.86，回撤更低
- 新标的包含：CVNA、MSTR、CRDO、VST、DELL、ANF 等高增长股

### 存活偏差警告

> **重要**：以上数据含存活偏差（Survivorship Bias）。
> 动态池用今天的市值筛选，天然偏向"过去5年涨了很多的股票"。
> 实际前向表现预期会打折。建议从启用日起跟踪实盘表现。

## 刷新机制

- 脚本：`scripts/refresh_universe.py`
- 缓存：`.cache/universe/universe_latest.json`
- 服务：`app/services/universe_service.py`
- 建议频率：每周一次（盘前）
- 耗时：~2小时（受AV API速率限制）

## 相关文档

- [[Strategy/00-Index]] — 策略文档索引
- [[Projects/V5-Roadmap-Detail#Phase-2]] — V5路线图 Phase 2

## 自动化集成（2026-03-19 完成）

### Scheduler
- **Job 18**: 每周六 09:00 NZT（轮动前1小时）
- 自动调用 UniverseService.refresh_universe()
- 刷新完成后飞书推送通知

### Dashboard
- HTMX widget 在评分表上方显示选股池状态
- 显示：股票数量、行业分布Top 5、更新时间
- 超过7天未更新显示黄色警告，14天显示红色

### API 端点
| 端点 | 方法 | 鉴权 | 用途 |
|------|------|------|------|
| /api/admin/refresh-universe | POST | X-Admin-Token | 手动触发刷新 |
| /api/universe/status | GET | 无 | 查看当前状态 |
| /htmx/universe-status | GET | 无 | Dashboard卡片 |
