---
name: StockQueen 项目生命周期仪表板
updated: 2026-03-23
tags: [dashboard, lifecycle, active, dormant, planned, index]
---

# 📊 StockQueen 项目生命周期仪表板

---

## 🚦 状态摘要（2026-03-23 周日）

| 状态 | 说明 |
|------|------|
| ✅ 模拟实盘运行中 | 宝典V4 + ML-V3A + 动态选股池 + Tiger Paper Trading |
| ✅ 今日完成 | **Scheduler/Data-Worker 拆分**（WORKER_ROLE 环境变量，`af26f03`） |
| 🟡 待部署 | Render 新建 `stockqueen-data-worker` Background Worker |
| 🟡 进行中 | D1 Sub-Tranche（Phase 4 观测期）/ C3 Stripe 付费墙 |
| 🟡 进行中 | Massive 数据源迁移（替换 AV + FMP） |

### Render 服务架构（4 服务）

| 服务 | 类型 | WORKER_ROLE | 任务数 | 状态 |
|------|------|------------|--------|------|
| `stockqueen-api` | Web Service | — | — | ✅ 运行中 |
| `stockqueen-scheduler` | Background Worker | `scheduler` | 16 | 🟡 待设 WORKER_ROLE |
| `stockqueen-data-worker` | Background Worker | `data-worker` | 21 | 🟡 待创建 |
| `stockqueen-site` | Static Site | — | — | ✅ 运行中 |

### 当前持仓（Tiger Paper）

| 代码 | 入场价 | 浮盈 | Tiger状态 |
|------|--------|------|---------|
| SH  | $37.13 | +1.38% | filled ✅ |
| PSQ | $31.15 | +1.23% | filled ✅ |
| RWM | $16.20 | +0.79% | filled ✅ |
| SHY | $82.63 | -0.17% | filled ✅ |

---

## 🟢 ACTIVE（生产运行中）

→ 后端服务详见 [[Backend-Services]]

| 关键模块 | 说明 | 状态 |
|---------|------|------|
| rotation_service | 宝典V4 趋势轮动（TOP_N=3，WF锁定）| 生产运行 |
| universe_service | 动态选股池（PIT WF已验证，USE_DYNAMIC_UNIVERSE=True）| 生产运行 |
| ml_ranker | ML-V3A 非对称标签排序（2026-03-20上线）| 生产运行 |
| multi_factor_scorer | 9因子评分引擎 | 生产运行 |
| portfolio_manager | 三策略资金管理 | 生产运行 |
| mean_reversion_service | MR 均值回归 | 生产运行 |
| event_driven_service | ED 事件驱动 | 生产运行 |
| news_scanner_service | 盘后AI事件扫描 | 生产运行 |
| tiger_order_service | Tiger Paper Trading 自动下单 | 模拟盘运行 |
| **scheduler (拆分)** | **交易路径16任务 + 数据采集21任务，WORKER_ROLE分流** | **代码就绪** |
| sector heatmap | 板块热力图 (33→21归并, normalize_sector) | 生产运行 |

→ 前端页面详见 [[Frontend-Website]]
→ Render 部署详见 [[Infrastructure/Render-Setup]]

---

## 💤 DORMANT（已存在但未激活）

| 模块 | 激活条件 |
|------|----------|
| Sub-Tranche 出场（D1）| Phase 4 观测期，信号积累中 |
| Stripe 付费墙（C3）| 待开发 |

---

## 🗺️ PLANNED（破浪剩余）

| 项目 | 优先级 | 状态 |
|------|--------|------|
| D1 Sub-Tranche Tranche B 执行层 | P1 | 🟡 观测期后 |
| C3 Stripe 付费墙 | P2 | 🟡 进行中 |
| Massive 数据源迁移 | P1 | 🟡 进行中 |
| A0 综合策略 V5 整合 | P0 | 🔵 规划中 |
| Newsletter推广 | P3 | 🔲 迁移后 |

---

## 📚 文档导航

| 领域 | 文档 |
|------|------|
| 破浪项目追踪 | [[Projects/00-Active-Projects]] |
| V5路线图 | [[Projects/V5-Roadmap-Detail]] |
| Render 部署 | [[Infrastructure/Render-Setup]] |
| 调度任务总表 | [[Scheduler-Jobs]] |
| WF结果 | [[Walk-Forward/08-PIT-WF-Results-V4]] |
| Walk-Forward索引 | [[Walk-Forward/00-Index]] |
| 策略文档 | [[Strategy/00-Index]] |
| ML文档 | [[ML/00-Index]] |
