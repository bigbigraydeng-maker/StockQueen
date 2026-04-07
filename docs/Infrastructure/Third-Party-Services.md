---
name: 第三方服务配置
description: Resend 邮件 + Stripe 支付集成配置参考
type: reference
created: 2026-03-15
source: site/RESEND_SETUP.md, site/STRIPE_SETUP.md
tags: [resend, stripe, infrastructure, config]
---

# 第三方服务配置

## Resend 邮件服务

- StockQueen 团队邮箱：bigbigraydeng@gmail.com
- 服务: [Resend](https://resend.com)
- 环境变量: `RESEND_API_KEY`, `FROM_EMAIL`, `CONTACT_EMAIL`

## Stripe 支付集成

- [Stripe 测试卡号](https://stripe.com/docs/testing#cards)
- 环境变量: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- 定价页面详情见 [[Pricing-Page]]
