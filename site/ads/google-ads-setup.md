# StockQueen Google Ads Setup Guide

## 基础配置（首次设置）

### 1. 账号结构
```
MCC账号（可选）
└── StockQueen Google Ads 账号
    ├── 活动1: Search - Free Newsletter (English)
    ├── 活动2: Search - Free Newsletter (Chinese)
    ├── 活动3: Search - Premium Signals (English)
    ├── 活动4: Display Remarketing (English + Chinese)
    └── 活动5: YouTube (未来扩展)
```

---

## 2. 转化追踪配置（必须先做）

### Step 1: 创建转化动作
在 Google Ads 后台 → 工具 → 转化 → 新建转化：

| 转化名称 | 类型 | 价值 | 来源 |
|---------|------|------|------|
| `newsletter_subscribe_free` | 潜在客户 | $0 | GA4 导入 |
| `checkout_initiated` | 潜在客户 | $10 | GA4 导入 |
| `purchase_monthly` | 购买 | $49 | GA4 导入 |
| `purchase_quarterly` | 购买 | $129 | GA4 导入 |
| `purchase_yearly` | 购买 | $399 | GA4 导入 |

### Step 2: 关联 GA4
Google Ads → 工具 → 已关联账号 → Google Analytics → 关联 (G-NDZYLB3YGE)
然后导入 GA4 转化事件到 Google Ads。

### Step 3: 获取 Google Ads 转化 ID
创建转化后，在 `payment-success.html` 中取消注释并填入：
```javascript
gtag('event', 'conversion', {
    send_to: 'AW-XXXXXXXXX/YYYYYYY',  // 替换为你的转化 tag
    value: value,
    currency: 'USD'
});
```

---

## 3. 活动 1: Search — Free Newsletter (English)

**目标**: 让英语用户订阅免费 newsletter
**出价策略**: 先用手动 CPC，积累 50 个转化后换 Target CPA
**日预算**: $15-20/天
**地区**: Australia, New Zealand, Singapore, Hong Kong, Japan, South Korea, USA, Canada, UK

### 广告组 1: "AI Trading Signals"
**关键词（精准匹配）**:
- [ai trading signals]
- [quantitative trading signals]
- [algorithmic trading newsletter]
- [ai stock signals free]
- [quant trading newsletter]

**关键词（词组匹配）**:
- "AI trading newsletter"
- "quantitative trading alerts"
- "momentum trading signals"
- "systematic trading newsletter"

**广告文案 A（侧重业绩）**:
```
标题1: Free AI Trading Newsletter
标题2: 536% Return Since 2022 | StockQueen
标题3: Weekly Quant Signals — Subscribe Free
描述1: AI-powered quantitative strategy outperforms S&P 500 by 467%. Get weekly
       market analysis, regime detection & trading signals. No credit card needed.
描述2: Walk-forward validated strategy. 57.7% win rate. 2.68 Sharpe ratio.
       Join investors across Asia-Pacific. Unsubscribe anytime.
```

**广告文案 B（侧重免费/无风险）**:
```
标题1: Weekly AI Stock Signals — Free
标题2: Quant Strategy | +536% Total Return
标题3: 100% Free • No Card Required
描述1: Every Saturday: market regime analysis, momentum signals & portfolio
       performance vs SPY. Powered by AI quantitative model. 100% free.
描述2: Institutional-grade quant strategy made accessible. Walk-forward tested
       across 163 weeks. Subscribe now, unsubscribe anytime.
```

**落地页**: `https://stockqueen.tech/subscribe.html?utm_source=google&utm_medium=cpc&utm_campaign=search_en_free`

---

### 广告组 2: "Momentum Strategy"
**关键词**:
- [momentum trading strategy]
- [momentum factor investing]
- [sector rotation strategy newsletter]
- [stock momentum signals]
- [best trading newsletter 2025]

**广告文案**:
```
标题1: Momentum Strategy Newsletter
标题2: AI Regime Detection | Bull/Bear/Choppy
标题3: Free Weekly — StockQueen
描述1: Our AI auto-detects market regime (Bull/Bear/Choppy) and rotates
       portfolio accordingly. +536% total return since Jan 2022.
描述2: Transparent track record, walk-forward validated. Free weekly newsletter
       covering signals, positions & market analysis. Sign up free today.
```

---

### 广告组 3: "Stock Newsletter"
**关键词**:
- [best stock newsletter]
- [stock market newsletter free]
- [weekly stock picks newsletter]
- [AI stock picks newsletter]

**广告文案**:
```
标题1: #1 AI Stock Newsletter — Free
标题2: Beat the Market by 467% Alpha
标题3: Real Signals. Full Transparency.
描述1: Not stock tips — a quantitative system. AI detects market regimes,
       rotates between growth & defensive ETFs. Free weekly newsletter.
描述2: 57.7% win rate across 87 signals. Average hold: 8.4 days.
       Join Asia-Pacific investors using institutional-grade quant research.
```

---

## 4. 活动 2: Search — Free Newsletter (Chinese)

**日预算**: $10-15/天
**地区**: Hong Kong, Taiwan, Singapore, Malaysia
**语言**: Chinese (Traditional), Chinese (Simplified)

### 广告组 1: 量化投资
**关键词**:
- [量化投资 newsletter]
- [AI 股票信号]
- [量化交易 周报]
- [美股 量化策略]
- [AI 炒股 信号]

**广告文案 A**:
```
标题1: 免费AI量化交易周报 | StockQueen
标题2: 累计收益536% 超越SPY467%
标题3: 每周六送达 无需信用卡
描述1: AI量化模型自动识别牛市/熊市/震荡市，每周提供交易信号和市场分析。
       2022年以来累计收益536.8%，夏普比率2.68，每周免费送达。
描述2: Walk-Forward验证163周，胜率57.7%。
       加入港台新马澳新等地区投资者，永久免费订阅。
```

**落地页**: `https://stockqueen.tech/subscribe-zh.html?utm_source=google&utm_medium=cpc&utm_campaign=search_zh_free`

---

## 5. 活动 3: Search — Premium Signals (English)

**日预算**: $10-15/天（先小，验证付费转化率）
**出价策略**: Target CPA (待积累数据后)

### 广告组: Premium Trading Signals
**关键词**:
- [premium stock signals]
- [paid trading signals service]
- [professional trading signals subscription]
- [buy sell trading signals]
- [quantitative trading subscription]

**广告文案**:
```
标题1: Full Trading Signals — $49/mo
标题2: Entry Price • Stop-Loss • Take-Profit
标题3: 7-Day Free Trial | StockQueen Premium
描述1: Get complete buy/sell signals with exact entry prices, stop-loss and
       take-profit levels. Quantitative strategy with 536% return since 2022.
描述2: Walk-forward validated. Not opinions — systematic signals.
       7-day free trial, cancel anytime. Start today.
```

**落地页**: `https://stockqueen.tech/subscribe.html?utm_source=google&utm_medium=cpc&utm_campaign=search_en_premium#premium`

---

## 6. 活动 4: Display Remarketing

**受众**: 访问过 stockqueen.tech 但未订阅的用户（需 Google Ads 受众列表 + 网站代码）
**日预算**: $5-10/天

**横幅广告尺寸准备**:
- 300×250 (Medium Rectangle) ✓
- 728×90 (Leaderboard) ✓
- 160×600 (Wide Skyscraper) ✓
- 320×50 (Mobile Banner) ✓
- 1200×628 (Responsive) ✓

**广告文案（Responsive Display Ad）**:
```
标题: Free AI Trading Newsletter
长标题: 536% Return Strategy — Free Weekly Signals
描述: You visited StockQueen. Don't miss this week's signals — subscribe free.
```

---

## 7. 关键词否定列表（全局）

```
-forex
-crypto
-bitcoin
-cryptocurrency
-options trading
-day trading course
-penny stocks
-how to trade
-trading app
-free demo
-paper trading
-trading simulator
```

---

## 8. UTM 参数规范

所有落地页 URL 统一格式：
```
https://stockqueen.tech/subscribe.html
  ?utm_source=google
  &utm_medium=cpc
  &utm_campaign=search_en_free   (活动名)
  &utm_content=ad_a              (广告创意区分)
  &utm_term={keyword}            (自动插入关键词)
```

---

## 9. 启动检查清单

- [ ] Google Ads 账号创建并绑定信用卡
- [ ] 关联 GA4 (G-NDZYLB3YGE)
- [ ] 设置转化追踪（导入 GA4 事件）
- [ ] 创建受众再营销列表（需网站流量 >100/月 才能使用）
- [ ] 上传 5 个以上广告创意图片（1200x628, 1200x1200）
- [ ] 测试落地页加载速度（目标 <3秒）
- [ ] 验证 newsletter 订阅流程正常
- [ ] 设置预算上限告警
- [ ] 运行 7 天后查看数据，调整出价
