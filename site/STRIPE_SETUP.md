# Stripe 支付集成指南

## 🎯 功能概述

实现 StockQueen Pro 会员订阅系统：
- $49/月 订阅计划
- 7天免费试用
- 自动续费
- 随时取消

## 🚀 快速开始

### 1. 注册 Stripe 账号

1. 访问 https://stripe.com
2. 注册账号并完成验证
3. 进入 Dashboard

### 2. 获取 API Keys

在 Stripe Dashboard → Developers → API keys：

```bash
# 测试环境
STRIPE_TEST_PUBLISHABLE_KEY=pk_test_...
STRIPE_TEST_SECRET_KEY=sk_test_...

# 生产环境
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_SECRET_KEY=sk_live_...
```

### 3. 创建产品和价格

在 Stripe Dashboard → Products：

**产品名称**: StockQueen Pro
**描述**: AI-powered quantitative trading signals

**价格设置**:
- 价格: $49.00
- 计费周期: Monthly
- 试用周期: 7 days

或者使用 Stripe CLI：

```bash
# 创建产品
stripe products create --name="StockQueen Pro" --description="AI-powered quantitative trading signals"

# 创建价格（替换 product_id）
stripe prices create --product=prod_xxx --unit-amount=4900 --currency=usd --recurring={"interval":"month"} --trial-period-days=7
```

### 4. 配置 Webhook

在 Stripe Dashboard → Developers → Webhooks：

**Endpoint URL**: `https://api.stockqueen.tech/webhook/stripe`

**监听事件**:
- `checkout.session.completed`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `customer.subscription.deleted`

## 📁 文件结构

```
site/
├── js/
│   └── stripe-checkout.js      # Stripe Checkout 前端
├── api/
│   └── create-checkout-session.js  # 后端 API（Serverless）
├── pricing.html                # 已创建
├── success.html               # 支付成功页
├── cancel.html                # 支付取消页
└── member-dashboard.html      # 会员中心
```

## 🔧 前端集成

### 在 pricing.html 中添加 Stripe Checkout

```html
<!-- 在 <head> 中添加 -->
<script src="https://js.stripe.com/v3/"></script>

<!-- 替换原来的按钮 -->
<button id="checkout-button" class="...">
    开始免费试用
</button>

<script>
const stripe = Stripe('pk_test_...'); // 你的 publishable key

document.getElementById('checkout-button').addEventListener('click', async () => {
    const response = await fetch('/api/create-checkout-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priceId: 'price_xxx' })
    });
    const session = await response.json();
    stripe.redirectToCheckout({ sessionId: session.id });
});
</script>
```

## 🔒 后端 API（Serverless 函数）

### 方案 1: Vercel Serverless Functions

创建 `api/create-checkout-session.js`:

```javascript
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);

module.exports = async (req, res) => {
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
        const session = await stripe.checkout.sessions.create({
            mode: 'subscription',
            payment_method_types: ['card'],
            line_items: [{
                price: req.body.priceId,
                quantity: 1,
            }],
            subscription_data: {
                trial_period_days: 7,
            },
            success_url: `${process.env.DOMAIN}/success.html?session_id={CHECKOUT_SESSION_ID}`,
            cancel_url: `${process.env.DOMAIN}/cancel.html`,
        });

        res.status(200).json({ id: session.id });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
};
```

### 方案 2: Render Web Service

在现有 API 中添加路由：

```python
# app/routers/payments.py
from fastapi import APIRouter, Request
import stripe

router = APIRouter()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

@router.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    data = await request.json()
    
    session = stripe.checkout.Session.create(
        mode='subscription',
        payment_method_types=['card'],
        line_items=[{
            'price': data['priceId'],
            'quantity': 1,
        }],
        subscription_data={
            'trial_period_days': 7,
        },
        success_url=f"{DOMAIN}/success.html?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{DOMAIN}/cancel.html",
    )
    
    return {"id": session.id}
```

## 📧 邮件营销集成

### 方案: Resend + Supabase

1. **用户注册时** → 发送欢迎邮件
2. **订阅成功时** → 发送确认邮件
3. **试用即将结束** → 发送提醒邮件
4. **付款失败时** → 发送提醒邮件

### Webhook 处理

```javascript
// api/webhook/stripe.js
const resend = new Resend(process.env.RESEND_API_KEY);

export default async function handler(req, res) {
    const event = stripe.webhooks.constructEvent(
        req.body,
        req.headers['stripe-signature'],
        process.env.STRIPE_WEBHOOK_SECRET
    );

    switch (event.type) {
        case 'checkout.session.completed':
            // 发送欢迎邮件
            await resend.emails.send({
                from: 'StockQueen <onboarding@resend.dev>',
                to: customerEmail,
                subject: 'Welcome to StockQueen Pro!',
                html: welcomeEmailTemplate,
            });
            break;
            
        case 'invoice.payment_failed':
            // 发送付款失败提醒
            await resend.emails.send({
                from: 'StockQueen <onboarding@resend.dev>',
                to: customerEmail,
                subject: 'Payment Failed - Action Required',
                html: paymentFailedTemplate,
            });
            break;
    }

    res.status(200).json({ received: true });
}
```

## 🧪 测试支付流程

### 使用 Stripe 测试卡号

| 卡号 | 场景 |
|------|------|
| 4242 4242 4242 4242 | 成功支付 |
| 4000 0000 0000 0002 | 卡片被拒绝 |
| 4000 0000 0000 9995 | 余额不足 |

### 测试 Webhook 本地

```bash
# 安装 Stripe CLI
stripe login

# 转发 webhook 到本地
stripe listen --forward-to localhost:3000/api/webhook/stripe
```

## 📝 环境变量配置

添加到 `.env`：

```bash
# Stripe
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...

# Domain
DOMAIN=https://stockqueen.tech
```

## 🎨 UI 组件

### 支付成功页 (success.html)

```html
<!DOCTYPE html>
<html>
<head>
    <title>Welcome to StockQueen Pro</title>
</head>
<body>
    <div class="success-container">
        <h1>🎉 Welcome to StockQueen Pro!</h1>
        <p>Your 7-day free trial has started.</p>
        <a href="/member-dashboard.html" class="btn">Access Member Dashboard</a>
    </div>
</body>
</html>
```

### 会员中心 (member-dashboard.html)

- 实时信号展示
- 历史报告存档
- 账户管理（取消订阅）
- 社区入口

## 📊 监控和分析

在 Stripe Dashboard 中查看：
- 转化率
- 月度经常性收入 (MRR)
- 流失率
- 试用转化率

## 🔗 参考链接

- [Stripe Checkout 文档](https://stripe.com/docs/checkout/quickstart)
- [Stripe Webhooks](https://stripe.com/docs/webhooks)
- [Stripe 测试卡号](https://stripe.com/docs/testing#cards)
