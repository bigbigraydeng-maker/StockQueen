# StockQueen V4 — Walk-Forward Validated Momentum Rotation

Multi-factor momentum rotation strategy for US equities & ETFs with regime-adaptive position management, validated through 6-window Walk-Forward testing.

**Live Dashboard**: https://stockqueen-api.onrender.com/dashboard
**Public Site**: https://stockqueen-site.onrender.com

## V4 Performance — Walk-Forward OOS Spliced

**Validation**: 6-Window Walk-Forward (8mo train + 8mo OOS, 2021-07 ~ 2026-03)
**Universe**: 220 US Stocks & ETFs across 24 sectors
**Bias Corrections**: 0.1% slippage, 500K volume filter, next-day open execution, IPO date filter

| Metric | Value | Note |
|--------|-------|------|
| Cumulative Return | **+494.4%** | Spliced OOS across 6 windows |
| Annualized Return | **63.7%** | vs SPY ~12%, QQQ ~15% |
| Sharpe Ratio | **2.33** | Out-of-sample |
| Max Drawdown | **-20.8%** | |
| Win Rate | **60.2%** | |
| Overfitting Decay | **0.23** | Train→Test Sharpe decay (MODERATE) |

### Walk-Forward Windows

| Window | Train | OOS Test | Market Context | OOS Sharpe |
|--------|-------|----------|----------------|------------|
| W1 | 2021-07~2022-06 | 2022-07~2023-02 | Fed rate hikes, bear market | 1.92 |
| W2 | 2022-03~2022-12 | 2023-03~2023-10 | AI bull (ChatGPT era) | 2.28 |
| W3 | 2022-11~2023-08 | 2023-11~2024-06 | Mag-7 divergence | 2.52 |
| W4 | 2023-07~2024-04 | 2024-07~2025-02 | Rate cut expectations | 2.68 |
| W5 | 2024-03~2024-12 | 2025-03~2025-10 | Elevated volatility | 2.15 |
| W6 | 2024-11~2025-08 | 2025-09~2026-03 | Current regime | 2.45 |

### Locked Parameters (key2goldenmine)

| Parameter | Value | Evidence |
|-----------|-------|----------|
| TOP_N | 6 | Selected by 4/6 windows |
| HOLDING_BONUS | 0.0 | Selected by 5/6 windows |
| ATR_STOP_MULT | 1.5 | Fixed stop-loss distance |
| TRAILING_STOP_MULT | 1.5 | Trailing stop distance |
| TRAILING_ACTIVATE | 0.5 | Profit threshold to activate trailing |

Full parameter lock file: `app/config/key2goldenmine.json`

## Architecture

```
[Weekly Scheduler (NZT Saturday 10:00)]
        |
[Universe: 220 US Stocks & ETFs]
  14 Offensive ETFs | 3 Defensive ETFs | 4 Inverse ETFs
  48 Large-Cap | 99 Mid-Cap Growth | 24 Sectors
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
│   │   ├── rotation_watchlist.py  # 220-ticker universe + strategy params
│   │   └── key2goldenmine.json    # V4 locked parameters (WF validated)
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
│   ├── blog/                      # SEO blog articles
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

### Manual Execution Panel
- **执行轮动**: Trigger weekly rotation scan on-demand
- **市场数据**: Fetch latest market data pipeline
- **退出检查**: Run stop-loss / trailing stop checks

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
| Sat 10:00 | Weekly rotation | Saturday | Core momentum rotation |
| Sat 10:30 | Pattern stats | Saturday | Technical pattern analysis |
| Sat 11:30 | 13F holdings | Saturday | Institutional tracking |
| 1st 12:00 | Auto param tune | Monthly | Parameter optimization |

## Iteration History

| Version | Tickers | WF Windows | Sharpe | Annual | MaxDD | Overfit | Key Change |
|---------|---------|------------|--------|--------|-------|---------|------------|
| V1 | 136 | 3 | 1.04 | 40.4% | -35.7% | 0.45 | Baseline |
| V2 | 136 | 3 | 1.99 | 77.6% | -29.5% | 0.57 | +Trailing stop |
| V3 | 220 | 6 | 2.41 | 68.3% | -25.8% | 0.42 | +Expanded pool |
| V4 | 220 | 6 | 2.33 | 63.7% | -20.8% | **0.23** | +Bias corrections |

V4 sacrificed raw performance for significantly improved robustness (overfitting decay 0.42 → 0.23).

## Deployment

Render Blueprint (`render.yaml`) deploys 3 services:

1. **stockqueen-api** (Web) — FastAPI backend + HTMX dashboard
2. **stockqueen-scheduler** (Worker) — APScheduler cron jobs
3. **stockqueen-site** (Static) — Public marketing site

## Disclaimer

This is a quantitative research and trading system. Walk-Forward validated backtests reduce but do not eliminate overfitting risk. Past performance does not guarantee future results. Trading involves substantial risk of loss. Not financial advice.

## License

MIT License

---

*Built by Rayde Capital*
