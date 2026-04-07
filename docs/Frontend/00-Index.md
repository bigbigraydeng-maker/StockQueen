---
name: Frontend Index
description: 前端文档索引：网站、SEO、CMS、博客、定价页
type: reference
created: 2026-03-19
tags: [index, frontend]
---

# Frontend 前端网站

网站、博客、CMS 和营销页面相关文档。

## 文档列表

| 文档 | 说明 |
|------|------|
| [[Blog-Management-System]] | Blog 管理系统设计（热点监控→创作→发布→分发） |
| [[CMS-Design]] | 可视化 CMS 系统设计（Notion 风格编辑器） |
| [[CMS-Development-Guide]] | CMS 开发交接文档（Next.js 14 项目结构/API/部署） |
| [[SEO-GEO-Audit]] | SEO/GEO 质量审计报告（广告投放准备） |
| [[Pricing-Page]] | Pricing 页面交接文档（Pro/Alpha 会员 + Stripe） |

## 技术栈

- 静态站: `site/` 目录，纯 HTML/Tailwind/HTMX
- 后台 Dashboard: FastAPI + Jinja2 模板
- CMS: Next.js 14 + TipTap 编辑器
- 博客: 静态页面 + Resend 邮件
