---
name: Pricing 页面交接
description: 定价页面开发交接：Pro/Alpha会员、Stripe集成
type: reference
created: 2026-03-15
source: PRICING_PAGE_HANDOVER.md
tags: [pricing, stripe, membership]
---

# StockQueen Pricing 页面 - 交接文档

## 📋 项目概述

为 StockQueen 量化投资平台创建会员定价页面，包含两个会员层级：
- **Pro 版**: $49/月订阅，面向普通投资者
- **Alpha 版**: 定制化服务，面向高净值投资者（$100K+ 可投资资产）

---

## ✅ 已完成工作

### 1. 页面文件

| 文件 | 状态 | 路径 |
|------|------|------|
| `pricing.html` | ✅ 完成 | `site/pricing.html` |
| `success.html` | ✅ 完成 | `site/success.html` |
| `cancel.html` | ✅ 完成 | `site/cancel.html` |
| `member-dashboard.html` | ✅ 完成 | `site/member-dashboard.html` |

### 2. JavaScript 模块

| 文件 | 功能 | 状态 |
|------|------|------|
| `js/stripe-checkout.js` | Stripe 支付集成 | ✅ 基础框架完成 |
| `js/email-automation.js` | 邮件营销自动化 | ✅ 基础框架完成 |

### 3. 设计特点

- **视觉风格**: 深色主题，渐变边框，科技感
- **响应式**: 支持桌面和移动端
- **动画效果**: 悬停缩放、渐变边框
- **配色**: 青色(#22d3ee) + 紫色(#a855f7) 渐变

---

## 📄 页面结构详解

### pricing.html 结构

```
1. Navigation (固定导航栏)
   - Logo: StockQueen
   - 链接: Weekly Report, Pricing, Contact

2. Hero Section
   - 标题: Join StockQueen
   - 副标题: +94.5% returns since 2023
   - 信任标识: 7-day trial, Cancel anytime, Real-time signals

3. Performance Highlight
   - 展示历史业绩数据
   - 4个数据卡片展示

4. Pricing Cards (核心部分)
   ├─ Pro Plan ($49/month)
   │   - 5个功能点
   │   - "Start Free Trial" 按钮
   │   - 7天免费试用
   │
   └─ Alpha Plan (Custom)
       - 6个功能点
       - "Talk to Us" 按钮
       - 弹出咨询表单

5. Fee Structure Note
   - Alpha 服务费用说明
   - 1-2% 年费 + 15-20% 业绩提成

6. FAQ Section
   - 4个常见问题

7. CTA Section
   - 最终转化按钮

8. Footer

9. Alpha Modal (弹出表单)
   - 姓名、邮箱、资产规模、留言
   - 提交后发送邮件通知

10. JavaScript
    - Stripe 配置
    - startCheckout() 函数
    - openAlphaModal() / closeAlphaModal()
    - 表单提交处理
```

---

## ⚠️ 已知问题 & 待完成

### 高优先级

1. **Stripe 支付集成未完成**
   - 当前状态: 前端框架已搭建，但 API 端点不存在
   - 需要: 创建后端 API `/api/create-checkout-session`
   - 配置: 需要真实的 Stripe API Keys
   ```javascript
   STRIPE_CONFIG = {
       PUBLISHABLE_KEY: 'pk_live_...',  // 需要替换
       PRICE_ID: 'price_...',           // 需要替换
       API_ENDPOINT: '/api/create-checkout-session',
       SUCCESS_URL: 'https://stockqueen.tech/success.html',
       CANCEL_URL: 'https://stockqueen.tech/cancel.html'
   }
   ```

2. **后端 API 缺失**
   - 需要创建: `/api/create-checkout-session` (POST)
   - 需要创建: `/api/contact` (POST) - 用于 Alpha 咨询表单
   - 需要创建: Stripe Webhook 处理 `/webhook/stripe`

3. **用户认证系统缺失**
   - 会员中心页面需要登录系统
   - 需要: 注册、登录、密码重置功能

### 中优先级

4. **邮件营销自动化**
   - 框架已创建 (`js/email-automation.js`)
   - 需要: 与 Resend API 集成
   - 需要: 后端定时任务处理邮件队列

5. **会员内容保护**
   - 会员中心页面内容需要登录验证
   - 需要: 付费内容访问控制

### 低优先级

6. **A/B 测试**
   - 不同定价文案测试
   - 按钮颜色/位置测试

---

## 🔧 技术栈

- **前端**: HTML5 + Tailwind CSS (CDN) + Vanilla JavaScript
- **支付**: Stripe.js (待完成集成)
- **邮件**: Resend (待完成集成)
- **部署**: GitHub Pages / Render

---

## 📁 文件位置

```
StockQueen/
├── site/
│   ├── pricing.html              # 主定价页面
│   ├── success.html              # 支付成功页
│   ├── cancel.html               # 支付取消页
│   ├── member-dashboard.html     # 会员中心
│   ├── js/
│   │   ├── stripe-checkout.js    # Stripe 支付逻辑
│   │   └── email-automation.js   # 邮件营销逻辑
│   └── STRIPE_SETUP.md           # Stripe 配置指南
└── PRICING_PAGE_HANDOVER.md      # 本文档
```

---

## 🚀 下一步行动建议

### 方案 A: 快速上线 (推荐)
1. 暂时移除 Stripe 集成，改为"联系订阅"模式
2. 添加邮箱收集表单
3. 手动处理订阅请求
4. 后续再集成自动支付

### 方案 B: 完整实现
1. 创建后端 API (Node.js/Python)
2. 配置 Stripe 账号和产品
3. 集成 Stripe Checkout
4. 创建用户数据库
5. 实现会员认证系统
6. 部署并测试完整流程

---

## 📞 联系方式

- **项目负责人**: bigbigraydeng@gmail.com
- **设计参考**: https://stockqueen.tech (主站)

---

## 📝 备注

- 所有页面使用 Tailwind CSS CDN，无需构建步骤
- 深色主题配色: 背景 #0a0a0a，文字白色，强调色 #22d3ee
- 渐变边框使用 CSS mask 技术实现
- 页面已针对 SEO 优化 (meta tags, description)

---

*文档创建时间: 2026-03-14*
*交接状态: 前端页面完成，后端集成待开发*
