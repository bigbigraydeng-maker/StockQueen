# StockQueen Facebook / Meta Ads Setup Guide

## 基础信息
- **Meta Pixel ID**: 837012746071305 ✅ (已安装)
- **GA4**: G-NDZYLB3YGE ✅
- **目标市场**: 港台新马澳新日韩 + 英语投资者

---

## 1. Meta Business Suite 初始配置

### Step 1: 验证 Pixel 事件
在 Meta Events Manager 确认以下事件已激活：
| 事件 | 触发页面 | 状态 |
|------|---------|------|
| `PageView` | 所有页面 | ✅ 已配置 |
| `Lead` | subscribe.html (订阅成功) | ✅ 已配置 |
| `InitiateCheckout` | subscribe.html (点击付费按钮) | ✅ 已配置 |
| `Purchase` | payment-success.html | ✅ 已配置 |

### Step 2: 开启 Conversions API（提升追踪准确率）
Meta Events Manager → 数据源 → Pixel → 设置 → Conversions API
→ 选择"通过合作伙伴集成" → 推荐通过 Render 后端实现服务端事件

### Step 3: 创建自定义受众
在 Meta Ads Manager → 受众：

**受众 A: 网站访客（再营销）**
- 类型: 网站自定义受众
- 规则: 过去 30 天访问过 stockqueen.tech 的用户
- 用途: Retargeting 活动

**受众 B: 已订阅用户（排除 + 种子受众）**
- 类型: 客户列表自定义受众
- 来源: 从 Resend 导出邮件列表上传
- 用途: 1) 从免费活动中排除 2) 创建 Lookalike

**受众 C: Lookalike — 1% 相似受众**
- 基于: 受众 B（已订阅用户）
- 比例: 1%（精准）
- 地区: 分别创建 TW/HK/SG/MY 和 AU/NZ/US 两个版本

---

## 2. 活动结构

```
广告账户
├── 活动1: 免费Newsletter — 英语用户 (Lead)
│   ├── 广告组1: 兴趣定向 — 投资/金融科技
│   ├── 广告组2: Lookalike 1% (EN市场)
│   └── 广告组3: Retargeting (已访问未订阅)
│
├── 活动2: 免费Newsletter — 中文用户 (Lead)
│   ├── 广告组1: 兴趣定向 — 港台新马股票投资
│   ├── 广告组2: Lookalike 1% (中文市场)
│   └── 广告组3: Retargeting 中文
│
└── 活动3: Premium升级 (Purchase)
    ├── 广告组1: 免费订阅者再营销 (已订阅未付费)
    └── 广告组2: Lookalike — 付费用户相似受众
```

---

## 3. 活动1: 免费Newsletter — 英语用户

**活动设置**:
- 目标: 转化 (Conversions)
- 优化事件: Lead
- 预算类型: 广告组层级每日预算 $20-25/天

### 广告组1: 兴趣定向 (Cold Audience)
**受众**:
- 地区: Australia, New Zealand, Singapore, Japan, South Korea
- 年龄: 25-55
- 语言: English
- 兴趣:
  - Stock market, Investing, Stock trader
  - Financial technology, FinTech
  - Quantitative analysis
  - Exchange-traded fund, Index fund
  - Bloomberg, CNBC, Wall Street Journal (媒体兴趣)
- 排除: 已订阅用户受众B

**广告创意 A — 业绩驱动（图片广告）**:
```
主图: 策略 vs SPY 收益曲线对比图（2022-2026）
标题: Our AI Trading Strategy: +536% vs SPY's +70%
正文:
Every Saturday, StockQueen delivers AI-powered quantitative signals
to 1,000+ investors across Asia-Pacific.

✅ Market regime analysis (Bull/Bear/Choppy)
✅ Weekly portfolio performance vs S&P 500
✅ AI-driven sector rotation insights

Free. No credit card. Unsubscribe anytime.

CTA按钮: Subscribe Now
落地页: https://stockqueen.tech/subscribe.html?utm_source=facebook&utm_medium=paid_social&utm_campaign=cold_en_lead&utm_content=performance_chart
```

**广告创意 B — 社会证明（轮播广告）**:
```
卡片1:
  图: 2022熊市防御图
  标题: 2022 Bear Market: We returned +12.5%
  描述: While SPY fell -17.5%

卡片2:
  图: 2023收益数字
  标题: 2023: +79.9% return
  描述: AI bull market + recovery

卡片3:
  图: 2024收益数字
  标题: 2024: +77.5% return
  描述: Broad market rally, alpha vs QQQ +49.4%

卡片4 (CTA):
  图: 邮件订阅界面截图
  标题: Get Free Weekly Signals
  描述: Join investors across AU/NZ/SG
CTA: Subscribe Free
```

**广告创意 C — 简洁问题钩子（竖版视频/图文）**:
```
图/视频文案:
"Tired of stock tips that never explain WHY?

StockQueen is different.

Every week we show you:
→ What regime the market is in
→ Why we're holding what we hold
→ Full P&L transparency

+536% since Jan 2022.
Free newsletter. No BS."

CTA: Get Free Access
```

---

### 广告组2: Retargeting (已访问未订阅)
**受众**: 受众A（过去30天访客）- 排除受众B（已订阅）
**预算**: $10/天
**创意**:
```
标题: You're Almost There, [First Name]
正文:
You visited StockQueen this week.

This Saturday's signal report includes:
• Market regime: BEAR (defensive mode active)
• 3 new position signals
• This week's deep-dive analysis

Don't miss it — it's free.

CTA: Subscribe Now
```

---

## 4. 活动2: 免费Newsletter — 中文用户

**广告组: 兴趣定向**:
- 地区: Hong Kong, Taiwan, Singapore, Malaysia
- 语言: Chinese (Traditional), Chinese (Simplified)
- 年龄: 25-55
- 兴趣:
  - 股票, 投資, 理財
  - 美股, 港股
  - 量化交易, 程序化交易
  - 巴菲特, 价值投资 (对比钩子)
  - 富途牛牛, 老虎证券 (竞品用户)

**广告创意 A**:
```
图: 收益曲线对比图（中文标注）
标题: 免费AI量化周报 | 累计收益536%
正文:
每周六，StockQueen量化模型将交易信号送达您的邮箱。

📊 市场状态识别（牛市/熊市/震荡）
📈 策略收益 vs SPY实时对比
💡 AI驱动的量化洞察分析

2022年至今累计收益536.8%，远超SPY的69.8%。
免费订阅，随时退订。

CTA: 立即订阅
落地页: https://stockqueen.tech/subscribe-zh.html?utm_source=facebook&utm_medium=paid_social&utm_campaign=cold_zh_lead
```

**广告创意 B（熊市防御对比钩子）**:
```
标题: 2022年大熊市，我们赚了12.5%
正文:
2022年美联储激进加息，大多数人亏损累累。

SPY全年跌17.5%
纳指跌33%
而StockQueen策略全年+12.5%

不是运气——是量化模型提前识别了熊市信号，
自动切换到防御性配置。

每周免费分析，看懂市场比大多数人早一步。

CTA: 免费订阅
```

---

## 5. 活动3: Premium升级活动

**目标**: 将免费用户转化为付费（$49-399/月）
**受众**: 已订阅免费newsletter的用户（自定义受众）
**预算**: $15/天
**优化事件**: Purchase

**广告文案（英文）**:
```
标题: You're Getting Free Signals. Upgrade for Full Access.
正文:
As a StockQueen newsletter subscriber, you already get:
✅ Market regime analysis
✅ Portfolio overview

But Premium members get:
🔓 Exact entry prices for every trade
🔓 Stop-loss & take-profit levels
🔓 Full position details
🔓 Deep-dive quant analysis every week

$49/mo with 7-day free trial.

CTA: Start Free Trial
落地页: https://stockqueen.tech/subscribe.html?utm_source=facebook&utm_medium=paid_social&utm_campaign=upsell_premium#premium
```

**广告文案（中文）**:
```
标题: 您已订阅免费版 — 升级查看完整信号
正文:
免费版让您了解市场状态。
高级版让您知道该如何行动。

免费版 → 信号摘要（标的名称）
高级版 → 精确进仓价 + 止损位 + 止盈位

本周有3个新买入信号，付费会员已收到完整价格。

$49/月，含7天免费试用，随时取消。

CTA: 开始免费试用
```

---

## 6. 广告图片素材清单

需要制作以下图片（建议用 Canva 或 Figma）：

| 图片 | 尺寸 | 用途 |
|------|------|------|
| 策略vs SPY收益曲线（英文） | 1200×628 | FB/IG Feed |
| 策略vs SPY收益曲线（中文） | 1200×628 | FB/IG Feed |
| 年度业绩数据卡片 | 1080×1080 | IG Square |
| 熊市防御说明图 | 1080×1080 | IG Square |
| 手机端邮件预览截图 | 1080×1920 | Stories |
| Newsletter内容截图 | 1080×1080 | IG Square |

**图片设计建议**:
- 背景: 深色 (#0b0f19) 配渐变高亮
- 强调色: 青色 (#22d3ee) + 紫色 (#818cf8)
- 数字要大要突出（+536%）
- 避免过多文字（FB对文字比例有限制）

---

## 7. 启动检查清单

### 技术层面：
- [x] Meta Pixel (837012746071305) 已安装
- [x] Lead 事件（免费订阅）已配置
- [x] InitiateCheckout 事件已配置
- [x] Purchase 事件（payment-success页面）已配置
- [ ] 开启 Conversions API（提升20-30%追踪准确率）
- [ ] 上传邮件客户列表创建自定义受众
- [ ] 创建 Lookalike 受众

### 广告层面：
- [ ] 创建 Meta Business 账号并验证域名 stockqueen.tech
- [ ] 制作 3-5 张广告图片
- [ ] 创建3个活动（英文免费、中文免费、Premium升级）
- [ ] 设置每日预算上限（建议第1周总共 $50/天测试）
- [ ] 配置 UTM 参数（已在落地页 URL 中添加）
- [ ] 运行7天后查看: CPC/CPL/ROAS，关掉表现差的创意

### 第一周目标指标：
| 指标 | 目标 |
|------|------|
| CPL (免费订阅成本) | < $8 |
| CTR | > 1.5% |
| 落地页转化率 | > 15% |
| Premium CPL | < $40 |
