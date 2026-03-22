---
name: V5 下一步行动计划
updated: 2026-03-21
tags: [v5, next-steps, walkforward, roadmap]
---

# V5 下一步行动（2026-03-19 通宵更新）

← [[Walk-Forward/00-Index]] | [[Projects/00-Active-Projects]]

---

## 阶段状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | Walk-Forward 初步验证 | ✅ 完成（含偏差，已存档） |
| Phase 1.5 Tier 1 | 幸存者偏差修复 | ✅ 今日完成 |
| Phase 2 | 动态选股池路由 + Scheduler | 🔵 今晚目标 |
| Phase 3 | AI 事件信号 | ✅ 完成 |
| Phase 4 | 订阅产品 | ✅ 完成（暂缓推广） |
| Phase 5 | Massive 数据源迁移 | 🟡 进行中 |

---

## Phase 1.5 Tier 1 完成内容（2026-03-19）

### 新增代码
- `app/services/universe_service.py`
  - 新增 `async def get_pit_universe(as_of_year: int) -> list`
  - 调用 Massive LISTING_STATUS 接口
  - Step1 过滤：NYSE/NASDAQ + IPO满365天
  - 永久缓存：`.cache/universe/universe_pit_{YYYY}.json`

- `scripts/walk_forward_v5_full.py`
  - 接入 `universe_filter` 参数（PIT过滤集合）
  - 训练期：2018 PIT（5197只）；测试期：对应年份 PIT

### WF 结果（修正后）

| 指标 | 值 |
|------|----|
| 平均 OOS Sharpe | **3.104** |
| 旧版（含偏差） | 2.33 |
| 最弱窗口 | 1.97（2022熊市） |
| 全窗口 best top_n | **3** |
| 判定 | **PASS ✅ 绿灯上线** |

→ 详见 [[Walk-Forward/08-PIT-WF-Results-V4]]

---

## Phase 2 今晚目标

### 2.1 Universe 手动触发路由（`/api/universe/refresh`）

```python
# app/routers/rotation.py 新增
@router.post("/api/universe/refresh")
async def trigger_universe_refresh():
    svc = UniverseService()
    result = await svc.refresh_universe()
    return {"status": "ok", "count": result["final_count"]}
```

### 2.2 Scheduler 每周六 NZT 06:00 自动刷新

```python
# app/scheduler.py 新增 job
scheduler.add_job(
    refresh_universe_job,
    CronTrigger(day_of_week="sat", hour=6, minute=0, timezone="Pacific/Auckland"),
    id="universe_weekly_refresh",
)
```

---

## 生产参数待决策

| 参数 | 当前值 | 新WF建议 | 建议行动 |
|------|--------|---------|---------|
| `TOP_N` | 6 | **3** | 改为3，总仓位控30% |
| `USE_DYNAMIC_UNIVERSE` | False | True | Phase2完成后开启 |

---

## 后续里程碑

```
今晚：Phase 2 + top_n=3 + merge main + push Render
本周：MR/ED WF → 上线（30%仓位，top_n=3）
进行中：Massive 迁移 → Tier 2 幸存者偏差完整修复 → Newsletter推广
```
