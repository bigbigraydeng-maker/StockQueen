# StockQueen V5 — 500-Ticker Momentum Rotation, Stress-Tested Across Every Market Regime

Multi-factor momentum rotation strategy for US equities & ETFs with regime-adaptive position management. Validated through 40-month Walk-Forward testing and stress-tested across bear, bull, and late-cycle markets.

**Live Dashboard**: https://stockqueen-api.onrender.com/dashboard
**Public Site**: https://stockqueen-site.onrender.com

> **V5 is live!** Expanded from 220 to 500 tickers. Walk-Forward Sharpe 2.68. Positive alpha in every market regime tested (2022-2026).

## V5 Performance

**Validation**: 40-Month Walk-Forward (3mo train + 1mo OOS, 25 parameter combos)
**Universe**: 500 US Stocks & ETFs across all major sectors
**Bias Corrections**: 0.1% slippage, 500K volume filter, next-day open execution

| Metric | Fixed Best | Walk-Forward Adaptive | SPY | QQQ |
|--------|-----------|----------------------|-----|-----|
| Cumulative Return | **+536.8%** | +379.7% | +69.8% | +111.2% |
| Annualized Return | **80.5%** | 64.9% | — | — |
| Sharpe Ratio | **2.68** | 1.76 | — | — |
| Max Drawdown | **-19.1%** | -25.3% | — | — |
| Win Rate | **57.7%** | 56.4% | — | — |

### Stress Test — Every Market Regime

| Regime | Strategy | SPY | QQQ | Alpha vs SPY | Sharpe | Max DD |
|--------|----------|-----|-----|-------------|--------|--------|
| 🐻 Bear 2022 (Fed tightening) | **+12.5%** | -17.5% | -29.6% | **+30.0%** | 1.05 | -9.4% |
| 🔄 Recovery 2023 (AI rally) | **+79.9%** | +24.4% | +54.4% | **+55.6%** | 2.61 | -18.5% |
| 🐂 Bull 2024 (rate cut hopes) | **+77.5%** | +24.5% | +28.1% | **+53.1%** | 2.65 | -13.9% |
| ⚡ Late Cycle 2025-26 (tariffs) | **+107.7%** | +15.8% | +19.1% | **+91.9%** | 3.44 | -12.6% |

### Version Evolution

| Version | Tickers | Sharpe | Annual | MaxDD | Key Change |
|---------|---------|--------|--------|-------|------------|
| V1 | 136 | 1.04 | 40.4% | -35.7% | Baseline momentum |
| V2 | 136 | 1.99 | 77.6% | -29.5% | +Trailing stop |
| V3 | 220 | 2.41 | 68.3% | -25.8% | +Expanded pool, 6 WF windows |
| V4 | 220 | 2.33 | 63.7% | -20.8% | +Bias corrections (decay 0.23) |
| **V5** | **500** | **2.68** | **80.5%** | **-19.1%** | **+500 tickers, 40-month WF** |

## Architecture

```
[Weekly Scheduler (NZT Saturday 10:00)]
        |
[Universe: 500 US Stocks & ETFs]
  14 Offensive ETFs | 6 Defensive ETFs | 4 Inverse ETFs
  158 Large-Cap | 318 Mid-Cap Growth | All Major Sectors
        |
[Multi-Factor Scoring Engine]
  - Momentum: 1W/1M/3M returns (regime-weighted)
  - Volatility penalty + Graduated trend bonus
  - Fundamentals: earnings growth, cash flow (no overview = no look-ahead)
  - Technical: ATR, RSI, MACD, Bollinger, OBV, ADX
  - Relative strength vs SPY
  - Sector concentration cap (max 2 per sector)
        |
[Market Regime Detection (4-signal)]
  SPY vs MA50/MA20 | Volatility stress | 1M momentum
  → strong_bull | bull | choppy | bear
  → Dynamic momentum weight adjustment per regime
        |
[Risk Management]
  - ATR-based stop-loss: entry - 1.5×ATR14
  - Trailing stop: highest - 1.5×ATR14 (activates at +0.5×ATR profit)
  - Take profit: entry + 3.0×ATR14
  - Score-weighted position sizing
        |
[Tiger Open API — Order Execution]
        |
[Dashboard + Notifications]
  HTMX real-time dashboard | Feishu alerts
```

## Tech Stack

- **Backend**: Python 3.11 + FastAPI + APScheduler (21 scheduled jobs)
- **Database**: Supabase (PostgreSQL)
- **Market Data**: Alpha Vantage Premium ($49/mo, 75 req/min)
- **Broker**: Tiger Open API (real-time quotes + order execution)
- **AI**: DeepSeek (news classification + event scoring), OpenAI (embeddings for RAG)
- **Frontend**: HTMX + Tailwind CSS (dashboard), Static HTML (public site)
- **Deployment**: Render (API server + scheduler worker + static site)

## Quick Start

```bash
git clone https://github.com/bigbigraydeng-maker/StockQueen.git
cd StockQueen
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # Edit with your API keys
uvicorn app.main:app --reload
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | ✅ | Supabase service role key |
| `ALPHA_VANTAGE_KEY` | ✅ | Alpha Vantage Premium API key |
| `TIGER_ID` | ⚡ | Tiger Open API developer ID |
| `TIGER_ACCOUNT` | ⚡ | Tiger trading account |
| `TIGER_PRIVATE_KEY` | ⚡ | Tiger RSA private key (PEM) |
| `DEEPSEEK_API_KEY` | ⚡ | DeepSeek AI API key |
| `OPENAI_API_KEY` | ⚡ | OpenAI API key (embeddings) |
| `FEISHU_WEBHOOK_URL` | ⚡ | Feishu notification webhook |
| `FEISHU_APP_ID` | ⚡ | Feishu app credentials |
| `FEISHU_APP_SECRET` | ⚡ | Feishu app secret |
| `FEISHU_RECEIVE_ID` | ⚡ | Feishu message recipient |

✅ = Required for basic operation | ⚡ = Required for full functionality

## Project Structure

```
stockqueen/
├── app/
│   ├── main.py                    # FastAPI entry + startup
│   ├── scheduler.py               # APScheduler (21 cron jobs)
│   ├── models.py                  # Pydantic data models
│   ├── config/
│   │   ├── settings.py            # Environment config (Pydantic)
│   │   ├── rotation_watchlist.py  # 500-ticker universe + strategy params
│   │   └── key2goldenmine.json    # Locked parameters (WF validated)
│   ├── routers/
│   │   ├── web.py                 # Dashboard + trades + strategy pages
│   │   ├── rotation.py            # Rotation API endpoints
│   │   ├── signals.py             # Signal endpoints
│   │   ├── risk.py                # Risk management API
│   │   ├── knowledge.py           # Knowledge base API
│   │   └── websocket.py           # Real-time WebSocket
│   ├── services/
│   │   ├── rotation_service.py    # Core rotation + backtest engine
│   │   ├── multi_factor_scorer.py # 9-factor scoring system
│   │   ├── alphavantage_client.py # AV data client (dual cache)
│   │   ├── knowledge_service.py   # RAG knowledge base
│   │   ├── market_service.py      # Market data pipeline
│   │   ├── order_service.py       # Tiger trade execution
│   │   ├── risk_service.py        # Risk monitoring
│   │   └── notification_service.py# Feishu/SMS alerts
│   └── templates/                 # Jinja2 + HTMX templates
│       ├── base.html              # Layout with nav
│       ├── dashboard.html         # Main dashboard + exec panel
│       ├── trades.html            # Trade history page
│       ├── strategy.html          # Strategy lock visualization
│       └── partials/              # HTMX partial templates
├── site/                          # Public marketing site
│   ├── index.html / index-zh.html # EN/ZH landing pages
│   ├── data/*.json                # Backtest data (dynamic)
│   ├── blog/                      # SEO blog articles (EN/ZH)
│   └── weekly-report/             # Newsletter content
├── scripts/
│   └── walk_forward_test.py       # Walk-Forward validation script
├── render.yaml                    # Render deployment blueprint
└── requirements.txt
```

## Dashboard Features

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/dashboard` | Live positions, regime, scores, execution panel |
| Trade History | `/trades` | Closed positions with P&L, exit reasons, summary stats |
| Strategy Lock | `/strategy` | key2goldenmine parameters, WF windows, iteration history |

## Scheduled Jobs (NZT = UTC+13)

| Time | Job | Frequency | Description |
|------|-----|-----------|-------------|
| 09:15 | Market data pipeline | Tue-Sat | OHLCV + signal generation |
| 09:30 | Confirmation engine | Tue-Sat | D+1 signal confirmation |
| 09:40 | Entry check | Tue-Sat | New position entry timing |
| 09:45 | Exit check | Tue-Sat | Stop-loss + trailing stop |
| 09:50 | Signal outcome | Tue-Sat | Track 1d/5d/20d returns |
| 10:00 | News outcome | Tue-Sat | News-price correlation |
| 10:15 | AI sentiment | Tue-Sat | DeepSeek sentiment scoring |
| 10:30 | ETF flows | Tue-Sat | ETF fund flow tracking |
| Sat 10:00 | Weekly rotation | Saturday | Core momentum rotation (500 tickers) |
| Sat 10:30 | Pattern stats | Saturday | Technical pattern analysis |
| Sat 11:30 | 13F holdings | Saturday | Institutional tracking |
| 1st 12:00 | Auto param tune | Monthly | Parameter optimization |

## Disclaimer

This is a quantitative research and trading system. Walk-Forward validated backtests reduce but do not eliminate overfitting risk. Past performance does not guarantee future results. The 500-ticker universe is a curated pool subject to survivorship bias. Trading involves substantial risk of loss. Not financial advice.

## License

MIT License

---

*Built by Rayde Capital*
