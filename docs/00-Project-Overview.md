---
name: StockQueen Project Overview
description: 项目总览和文档导航：所有分类文档的入口
type: reference
created: 2026-03-19
tags: [index, overview, project]
---

# StockQueen 项目文档总览

## 文档分类

### 📊 Strategy 量化策略
核心策略体系：9因子评分、轮动逻辑、风控、Regime 体制系统。
→ [[docs/Strategy/00-Index|Strategy Index]]

### 🔬 Walk-Forward 回测验证
Walk-Forward 方法论、迭代历史、宝典V4 最终结果、偏差修正。
→ [[docs/Walk-Forward/00-Index|Walk-Forward Index]]

### 💹 Trading 交易执行
订单管理、止盈止损机制、自动挂单流程。
→ [[docs/Trading/00-Index|Trading Index]]

### 🌐 Frontend 前端网站
Blog 系统、CMS 设计、SEO 审计、定价页面。
→ [[docs/Frontend/00-Index|Frontend Index]]

### 🏗️ Infrastructure 基础设施
Render 部署、Supabase 数据库、环境配置。
→ [[docs/Infrastructure/00-Index|Infrastructure Index]]

---

## 项目架构

```
StockQueen
├── app/              # FastAPI 后端
│   ├── routers/      # API 路由
│   ├── services/     # 业务逻辑（轮动、regime、通知）
│   ├── templates/    # Jinja2 模板（Dashboard UI）
│   └── scheduler.py  # APScheduler 定时任务
├── site/             # 静态前端网站
├── scripts/          # 工具脚本（回测、分析）
├── database/         # SQL 建表脚本
└── docs/             # 📁 你正在看的文档
```

## 关键链接

- 生产 API: `api.stockqueen.tech`
- 静态网站: `www.stockqueen.tech`
- 数据库: Supabase (PostgreSQL)
- 数据源: Massive (行情 + 基本面 + 财报)
- 部署: Render (Web Service + Static Site)
