---
name: 产品与营销
description: Newsletter产品规格、博客SEO、社交媒体、广告计划、Stripe集成
type: reference
created: 2026-03-19
tags: [product, marketing, newsletter, stripe, blog, social, active]
---

# 产品与营销

## 1. Newsletter 产品

### 免费版（回顾型）
| 项 | 值 |
|---|---|
| 价格 | $0 |
| 频率 | 每周六 |
| 内容 | 上周回顾、策略脉搏、精选分析（部分） |
| 发送 | Resend API 自动发送 |
| 注册 | `/api/newsletter/subscribe` |

### 付费版（信号型）
| 项 | 值 |
|---|---|
| 价格 | $49/月 |
| 频率 | 每周六 + 实时信号 |
| 内容 | 完整信号、入场点位、止损建议、AI分析 |
| 支付 | Stripe Checkout |
| 管理 | Stripe Customer Portal |

### 目标市场
| 地区 | 说明 |
|------|------|
| 港台 | 繁体中文受众 |
| 新马 | 东南亚华人 |
| 澳新 | 大洋洲华人（含用户本人时区） |
| 日韩 | 亚太投资者 |

---

## 2. 博客 SEO

### 现有文章（11对 = 22篇 + 2索引）
全部中英双语，存放于 `site/blog/`

| 主题 | SEO关键词 |
|------|----------|
| AI量化交易指南 | AI trading, quant strategy |
| 动量策略 | momentum trading, ETF rotation |
| Bear Market防守 | bear market strategy, defensive |
| 散户量化 | retail quant, algorithmic trading |
| 海外华人投资 | overseas Chinese investment |
| Sharpe比率 | Sharpe ratio explained |
| 美股税收 | US stock tax guide |
| V5选股宇宙 | stock universe, SP100 |
| Walk-Forward | walk forward validation |
| AI vs 人工选股 | AI stock picking |
| 2025市场展望 | 2025 market outlook |

### CMS 编辑流程
```
1. 本地启动 cms/ (Next.js)
2. TipTap 编辑器写文章
3. DataCard 注入实时数据
4. 保存 → 写入 site/blog/
5. Git push → Render 自动部署
```

---

## 3. 社交媒体

### 工具 (`/social` 页面)
- AI 文案生成（DeepSeek）
- 社交图卡生成
- 支持平台：Twitter/X, LinkedIn, 微信公众号

### 发布流程
- 手动运行 `scripts/social_publish.py`
- 或通过 `/social` 页面生成 → 手动复制发布

---

## 4. 广告计划（🔵 PLANNED）

| 渠道 | 文档 | 状态 |
|------|------|------|
| Google Ads | `site/ads/google-ads-setup.md` | 📋 方案已写 |
| Facebook Ads | `site/ads/facebook-ads-setup.md` | 📋 方案已写 |
| Twitter Ads | `site/ads/twitter-ads.md` | 📋 方案已写 |

---

## 5. Stripe 集成

| 端点 | 说明 |
|------|------|
| `POST /api/payments/create-checkout` | 创建结账会话 |
| `POST /api/payments/webhook` | Stripe事件回调 |
| `GET /api/payments/status` | 订阅状态查询 |
| `POST /api/payments/portal` | 客户自助门户 |
| `GET /api/payments/health` | 健康检查 |

### 初始化
- `scripts/stripe_setup.py` 创建产品和价格
- Webhook 处理: `checkout.session.completed`, `customer.subscription.*`
