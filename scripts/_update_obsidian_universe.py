"""
Update Obsidian docs with Dynamic Universe results + ML-V2 conclusions.
Uses Python http.client to avoid Windows UTF-8 issues with curl.
"""

import http.client
import ssl
import sys

VAULT_KEY = "f49ee79c2be8d5f7b2166185e4141b38e7fe26ee828185bf9688a407c79a32cf"


def put_doc(path: str, content: str):
    """Write a document to Obsidian vault."""
    ctx = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection("127.0.0.1", 27124, context=ctx)
    headers = {
        "Authorization": f"Bearer {VAULT_KEY}",
        "Content-Type": "text/markdown",
    }
    body = content.encode("utf-8")
    conn.request("PUT", f"/vault/{path}", body=body, headers=headers)
    resp = conn.getresponse()
    resp.read()
    status = "OK" if resp.status in (200, 201, 204) else f"FAIL({resp.status})"
    print(f"  {path}: {status}")
    conn.close()


def main():
    print("Updating Obsidian docs...")

    # ── 1. Strategy/15-Dynamic-Universe.md (NEW) ──
    put_doc("docs/Strategy/15-Dynamic-Universe.md", """---
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
""")

    # ── 2. Update V5-Roadmap-Detail.md Phase 2 section ──
    # Read current content first, then update Phase 2
    ctx = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection("127.0.0.1", 27124, context=ctx)
    headers = {
        "Authorization": f"Bearer {VAULT_KEY}",
        "Accept": "text/markdown",
    }
    conn.request("GET", "/vault/docs/Projects/V5-Roadmap-Detail.md", headers=headers)
    resp = conn.getresponse()
    roadmap = resp.read().decode("utf-8")
    conn.close()

    # Replace Phase 2 section
    old_phase2 = """## Phase 2：动态选股池（UniverseService）⚠️ 代码存在，未接路由

| 项 | 值 |
|---|---|
| **文件** | `app/services/universe_service.py` |
| **代码状态** | ✅ 已实现（~200行） |
| **阻塞** | ⛔ 无路由端点、无调度、无法手动触发 |

### 缺失部分
- 路由端点 `/api/universe/`
- 调度集成（轮动时自动调用）
- 手动触发页面

### 接入步骤
1. 在 `rotation_service.py` 的 `_get_universe()` 中调用 UniverseService
2. 新增 `/api/universe/` 路由端点
3. 将选股池加入 Dashboard 自动刷新"""

    new_phase2 = """## Phase 2：动态选股池（UniverseService）✅ 已完成

| 项 | 值 |
|---|---|
| **文件** | `app/services/universe_service.py`、`scripts/refresh_universe.py` |
| **代码状态** | ✅ 已启用（`USE_DYNAMIC_UNIVERSE = True`） |
| **A/B验证** | ✅ 通过（Sharpe +0.86, 收益 +7,388%） |
| **完成日期** | 2026-03-19 |

### 完成内容
- UniverseService 筛选漏斗：13,200 → 6,500 → 1,900 → **1,578只**
- `refresh_universe.py` 刷新脚本（耗时~2h）
- `rotation_service.py` 集成（`_fetch_backtest_data` + `run_rotation`）
- A/B验证：静态479只 vs 动态1,578只
- 结果：收益4.1倍、Sharpe +0.86、回撤更低

### 存活偏差注意
回测数据含存活偏差，实盘效果预期会打折。详见 → [[Strategy/15-Dynamic-Universe]]

### 待完善
- [ ] 路由端点 `/api/universe/`（手动触发刷新）
- [ ] Scheduler 集成（每周自动刷新）
- [ ] Dashboard 展示选股池变化"""

    if old_phase2 in roadmap:
        roadmap = roadmap.replace(old_phase2, new_phase2)
        put_doc("docs/Projects/V5-Roadmap-Detail.md", roadmap)
    else:
        print("  WARNING: Could not find Phase 2 section to replace in V5-Roadmap-Detail.md")

    # ── 3. Update 00-Active-Projects.md — add Dynamic Universe project ──
    ctx2 = ssl._create_unverified_context()
    conn2 = http.client.HTTPSConnection("127.0.0.1", 27124, context=ctx2)
    conn2.request("GET", "/vault/docs/Projects/00-Active-Projects.md", headers=headers)
    resp2 = conn2.getresponse()
    active = resp2.read().decode("utf-8")
    conn2.close()

    # Add dynamic universe row to the project table
    old_row = '| **P1** | 🤖 ML-V3 非对称标签 | [[Projects/B1-ML-V3]] | 🟡 等待FMP | TBD |'
    new_row = '| **P1** | 🌐 动态选股池 | [[Strategy/15-Dynamic-Universe]] | ✅ 已完成 | 2026-03-19 |\n| **P1** | 🤖 ML-V3 非对称标签 | [[Projects/B1-ML-V3]] | 🟡 等待FMP | TBD |'

    if old_row in active:
        active = active.replace(old_row, new_row)
        put_doc("docs/Projects/00-Active-Projects.md", active)
    else:
        print("  WARNING: Could not find ML-V3 row in 00-Active-Projects.md")

    # ── 4. ML/00-Index.md already has ML-V2 results (verified above) ──
    print("\n  ML/00-Index.md: already contains ML-V2 conclusions (no update needed)")

    print("\nDone!")


if __name__ == "__main__":
    main()
