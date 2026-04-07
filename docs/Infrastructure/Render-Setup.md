---
name: Render 部署配置指南
description: StockQueen Render 部署指南 - API/Scheduler/Data-Worker/静态站配置说明
type: infrastructure
created: 2026-03-15
updated: 2026-03-23
source: RENDER_SETUP.md
tags: [render, deploy, infrastructure, worker-role]
---

# StockQueen Render 部署配置指南

## 架构概览

```
stockqueen.tech（自定义域名）
    ├── api.stockqueen.tech → Render Web Service（后端 API + Dashboard）
    ├── www.stockqueen.tech → Render Static Site（前端营销网站）
    ├── stockqueen-scheduler → Render Background Worker（交易关键路径）
    └── stockqueen-data-worker → Render Background Worker（数据采集/分析/ML）
```

### Worker 拆分架构（2026-03-23 实施）

通过 `WORKER_ROLE` 环境变量，同一份 `app/scheduler.py` 代码在两个 Worker 上运行不同任务子集：

| 服务 | WORKER_ROLE | 任务数 | 职责 |
|------|------------|--------|------|
| `stockqueen-scheduler` | `scheduler` | 16 | 交易信号/订单/轮动 |
| `stockqueen-data-worker` | `data-worker` | 21 | 数据采集/分析/ML/Newsletter |

**本地开发**: `WORKER_ROLE` 不设或设为 `all`，全部 37 个任务都注册。

> commit: `af26f03` — feat(scheduler): WORKER_ROLE 环境变量拆分 scheduler/data-worker

---

## 服务清单

### 1. API Service (Web)

| 配置项 | 值 |
|--------|-----|
| **Name** | `stockqueen-api` |
| **Type** | Web Service |
| **Runtime** | Python 3.11 |
| **Build Command** | `pip install --no-cache-dir -r requirements.txt && python scripts/download_fonts.py; git fetch --unshallow 2>/dev/null \|\| true; python scripts/generate_changelog.py` |
| **Start Command** | `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 300` |
| **Plan** | Starter+ |

### 2. Scheduler Worker（交易关键路径）

| 配置项 | 值 |
|--------|-----|
| **Name** | `stockqueen-scheduler` |
| **Type** | Background Worker |
| **Runtime** | Python 3.11 |
| **Build Command** | `pip install --no-cache-dir -r requirements.txt` |
| **Start Command** | `python -m app.scheduler` |
| **Plan** | Starter |
| **WORKER_ROLE** | `scheduler` |

**注册的 16 个任务**:
- Market Data Pipeline, Regime Monitor, D+1 Confirmation
- Daily Entry/Exit Check, ML Exit Scorer, Midweek Replacement
- Sub-Strategy Scan (MR+ED)
- Tiger Order Sync, Intraday Trailing Stop, Unfilled Order Mgr
- Geopolitical Scan x2
- Weekly Rotation, Refresh JSON x2

### 3. Data Worker（数据采集/分析/ML）

| 配置项 | 值 |
|--------|-----|
| **Name** | `stockqueen-data-worker` |
| **Type** | Background Worker |
| **Runtime** | Python 3.11 |
| **Build Command** | `pip install --no-cache-dir -r requirements.txt` |
| **Start Command** | `python -m app.scheduler` |
| **Plan** | Starter（ML Retrain 内存不够则升 Standard） |
| **WORKER_ROLE** | `data-worker` |

**注册的 21 个任务**:
- Signal/News Outcome Collector
- AI Event Scan (C2), EDGAR Insider Scan (C4)
- News Pipeline, AI Sentiment, ETF Flow
- Earnings Report, 13F Holdings
- Universe Refresh, FMP 基本面 x4
- Pattern Stats, Sector Rotation
- Newsletter Preview/Send
- Auto Param Tune, ML Monthly Retrain
- Knowledge Cleanup

**额外环境变量**（相比 scheduler）：
- `FMP_API_KEY`
- `RESEND_API_KEY`, `RESEND_AUDIENCE_ID`

### 4. Marketing Website (Static)

| 配置项 | 值 |
|--------|-----|
| **Name** | `stockqueen-site` |
| **Type** | Static Site |
| **Publish Directory** | `site` |
| **Plan** | Free |

---

## 环境变量

在 Render Dashboard → 各服务 → **Environment** 中配置：

```bash
# 所有服务共用
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

# Scheduler + Data Worker
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_RECEIVE_ID=...
FEISHU_WEBHOOK_URL=...
TIGER_ID=...
TIGER_ACCOUNT=...
TIGER_PRIVATE_KEY=...
ALPHA_VANTAGE_KEY=...

# Data Worker 额外
FMP_API_KEY=...
RESEND_API_KEY=...
RESEND_AUDIENCE_ID=...

# Worker 角色
WORKER_ROLE=scheduler  # 或 data-worker
```

---

## DNS 配置

| 类型 | 主机记录 | 值 |
|------|---------|-----|
| CNAME | `api` | `stockqueen-api.onrender.com` |
| CNAME | `www` | `stockqueen-site.onrender.com` |
| A | `@` | `76.76.21.21` |

---

## 部署验证

部署后检查各服务日志：
- scheduler 应显示: `role=scheduler, registered 16/37 jobs`
- data-worker 应显示: `role=data-worker, registered 21/37 jobs`

```bash
# 测试 API
curl https://api.stockqueen.tech/health
```

---

## 故障排除

| 问题 | 排查方法 |
|------|---------|
| 任务重复执行 | 检查两个 Worker 的 WORKER_ROLE 是否正确设置 |
| 任务未执行 | 确认 job_id 在对应的 SCHEDULER_JOBS/DATA_WORKER_JOBS 集合中 |
| ML Retrain OOM | Data Worker 升级到 Standard plan |
| 域名无法访问 | 检查 DNS 记录 |
| SSL 证书问题 | 删除自定义域名重新添加 |

---

## 相关链接

- Render Dashboard: https://dashboard.render.com
- render.yaml: 项目根目录 `render.yaml`
- 调度任务总表: [[Scheduler-Jobs]]
