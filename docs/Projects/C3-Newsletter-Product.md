---
name: Project C3 - Newsletter Subscription Product
description: Resend + Stripe Newsletter 订阅产品规格：免费版/付费版 + 目标市场华人市场
created: 2026-03-16
updated: 2026-03-21
tags: [project, newsletter, stripe, subscription, product]
status: in-progress
---

# Project C3 — Newsletter 订阅产品

> **状态**: Lab 功能已完成 ✅ / Stripe 付费墙待开发 🔲

## 产品定位

> 面向海外散户投资者，提供**量化策略信号订阅服务**。目标市场：港台新马澳新日韩

| 版本 | 内容 | 价格 | 发送频率 |
|------|------|------|---------|
| **免费版** | 每周回顾（上周表现+市场状态+精选分析） | $0 | 每周六 |
| **付费版 Pro** | 实时入场/出场信号 + 完整持仓明细 | **$49/月** | 盘后实时 |

**目标市场**：香港、台湾、新加坡、马来西亚（中文版）；澳洲、新西兰（双语）
**推广渠道**：Google Ads + Facebook/Instagram Ads

---

## 完成状态 Checklist

### Lab 功能（/lab C3 面板）
- [x] `GET /htmx/lab-c3-status` — 展示订阅人数、Resend 连接状态、Stripe 状态
- [x] `POST /htmx/lab-newsletter-preview` — Lab 页预览生成的 Newsletter HTML（free-zh 版本）
- [x] `POST /htmx/lab-newsletter-test-send` — 向测试成员发送测试邮件
- [x] `lab.html` C3 面板（HTMX 每 120s 刷新）

### Newsletter 生成器（`scripts/newsletter/`）
- [x] `data_fetcher.py` — 调后端 API 获取持仓/信号数据 + 快照对比生成「新信号」
- [x] `ai_content_generator.py` — AI 生成内容（Claude claude-opus-4-5 优先，DeepSeek 备用）
- [x] `renderer.py` — 渲染 4 版邮件 HTML（free-zh / free-en / paid-zh / paid-en）
- [x] `social_generator.py` — 生成 8 平台社交内容（Facebook-zh/en / Twitter / LinkedIn / 微信 / 小红书等，2种语言）
- [x] `sender.py` — Resend API 批量发送（每批 50 人，按 audience tag 区分）

### Scheduler 集成
- [x] Job 20: 每周六 12:00 NZT 自动生成 + 发送 Newsletter

---

## 待开发

- [ ] **Stripe 订阅集成** — $49/月 Checkout + Webhook 同步 Resend 联系人标签（free/paid/churned）
- [ ] **7天免费试用** — 新用户自动付费版 → 到期降级
- [ ] **社交媒体自动发布** — Twitter/Facebook API 自动发帖
- [ ] **网站付费墙**（Phase 2）

---

## 定价方案

| 方案 | 价格 | 折扣 |
|------|------|------|
| 月付 | $49/月 | — |
| 季付 | $129/季 | 省12% |
| 年付 | $399/年 | 省32% |

**Phase 计划**：
- Phase 1（前3个月）：全免费，积累用户，发完整版内容
- Phase 2（第4个月起）：开始收费，新用户7天免费试用
- 付费工具：Stripe（已有 payments.py）

---

## 技术架构

### 数据流
```
scripts/newsletter/generate.py
  → data_fetcher.py（FastAPI /api/public/* ）
  → ai_content_generator.py（Claude / DeepSeek）
  → renderer.py（Jinja2 HTML × 4版）
  → sender.py（Resend API 分标签发送）
  → social_generator.py（8平台内容输出到 output/social/）
```

### 输出目录
```
output/newsletters/
  free-zh.html, free-en.html
  paid-zh.html, paid-en.html
output/social/
  facebook-zh.txt, facebook-en.txt
  twitter-en.txt, linkedin-en.txt
  wechat-zh.md
```

### Stripe 集成方案
- `app/routers/payments.py` — 已有 Stripe Checkout Session 骨架
- Webhook → 同步 Resend 联系人标签（free/paid/churned）
- 7天试用 → 到期自动降级

---

## 推广预算规则

| 条件 | 动作 |
|------|------|
| CPL < $2.00 且日订阅 > 10人 | 日预算 +20%，上限 $80/天 |
| CPL $2.00-4.00 | 维持 |
| CPL > $6.00 连续3天 | 暂停，换文案/受众 |

---

## 相关文档

- [[Backend-Services]] — payments.py Stripe 路由
- [[Projects/00-Active-Projects]] — C3 项目状态追踪
