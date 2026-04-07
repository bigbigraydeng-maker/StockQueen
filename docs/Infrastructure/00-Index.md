---
name: Infrastructure Index
description: 基础设施文档索引：部署、运维、环境配置、第三方服务
type: reference
created: 2026-03-19
updated: 2026-03-21
tags: [index, infrastructure]
---

# Infrastructure 基础设施

部署、运维和环境配置相关文档。

## 文档列表

| 文档 | 说明 |
|------|------|
| [[Render-Setup]] | Render 部署配置指南（API/静态站/DNS/SSL） |
| [[Third-Party-Services]] | 第三方服务配置（Resend 邮件 + Stripe 支付） |

## 关键环境

- 生产 API: `api.stockqueen.tech` (Render Web Service)
- 静态站: `www.stockqueen.tech` (Render Static Site)
- 数据库: Supabase (`jktlsvocfzhhsxninttg`)
- 数据源: Massive（行情 + 基本面 + 财报，统一 API Key）
