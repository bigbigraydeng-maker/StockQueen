# StockQueen V3.1 - AI Adaptive Rotation Strategy

Multi-factor momentum rotation strategy for US equities & ETFs with regime-adaptive position management, trailing stops, and auto-parameter tuning.

**Live Dashboard**: https://stockqueen-api.onrender.com/dashboard
**Public Site**: https://stockqueen.tech

## Current Performance (Apr 2023 - Mar 2026, 132 weeks)

| Metric | Value | Note |
|--------|-------|------|
| Total Return | **129.2%** | vs SPY 57.6%, QQQ 68.3% |
| Annualized Return | **36.7%** | |
| Sharpe Ratio | **1.35** | |
| Max Drawdown | **-22.5%** | Bear market cash position reduced drawdown |
| Win Rate | 53% | |
| Alpha vs SPY | **+59.5%** | |
| Alpha vs QQQ | **+60.9%** | |
| Trailing Stop Triggers | 72 | Major profit-lock contributor |
| ATR Stop Triggers | 34 | Risk management |

## Architecture

```
[Weekly Scheduler (NZT Sat 10:00)]
        |
[Watchlist: 110+ US Stocks & ETFs]
   - Large-cap (NVDA, TSLA, AAPL, MSFT, etc.)
   - Growth / Mid-cap stocks
   - Sector ETFs + Defensive ETFs
        |
[Multi-Factor Scoring Engine]
   - Momentum, Technical, Trend, Relative Strength
   - Fundamentals, Earnings, Cashflow, Sentiment
   - Large-cap stocks use separate weight profile
        |
[Market Regime Detection]
   - BULL/STRONG_BULL -> Offensive (growth + large-cap)
   - BEAR  -> Cash position + Inverse ETFs (SH, PSQ)
   - CHOPPY -> Defensive (GLD, SHY, BIL)
        |
[Risk Management]
   - ATR-based stop-loss (1.5x ATR)
   - Trailing stop (lock profits after 1.5x ATR gain)
   - Circuit breaker (15% drawdown -> force bear mode)
   - Bear market cash position (cap 2 positions)
        |
[Auto Parameter Tuning (Monthly)]
   - Grid search over last 6 months
   - Optimizes top_n + holding_bonus
   - Stored in Supabase, used by weekly rotation
        |
[Dashboard + Public Site (stockqueen.tech)]
```

## Tech Stack

- **Backend**: Python + FastAPI + APScheduler (18 scheduled jobs)
- **Database**: Supabase (PostgreSQL) + three-tier cache (Memory/Disk/Supabase)
- **Data**: Alpha Vantage (market data + fundamentals)
- **AI**: DeepSeek (news classification), multi-factor scoring engine
- **Frontend**: HTMX + Tailwind CSS (dashboard), Static site (public)
- **Deployment**: Render (API + static site)

## Quick Start

```bash
git clone <repository-url>
cd stockqueen
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # Edit with your API keys
uvicorn app.main:app --reload
```

## Key Environment Variables

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |
| `TIGER_ACCESS_TOKEN` | Tiger Open API token |
| `TIGER_TIGER_ID` | Tiger ID |
| `TIGER_ACCOUNT` | Tiger trading account |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `ALPHA_VANTAGE_KEY` | Alpha Vantage API key |

## Project Structure

```
stockqueen/
├── app/
│   ├── main.py                 # FastAPI entry + startup
│   ├── scheduler.py            # APScheduler (18 scheduled jobs)
│   ├── models.py               # Pydantic models
│   ├── config/
│   │   └── rotation_watchlist.py  # 110+ ticker universe
│   ├── routers/
│   │   ├── web.py              # Dashboard + HTMX + public API
│   │   └── signals.py          # Signal endpoints
│   ├── services/
│   │   ├── rotation_service.py # Core rotation logic
│   │   ├── knowledge_service.py# Multi-factor scoring
│   │   ├── market_service.py   # Tiger API integration
│   │   ├── order_service.py    # Trade execution
│   │   └── notification_service.py
│   └── templates/              # Jinja2 dashboard templates
├── site/                       # Public static site
│   ├── index.html              # Main page
│   ├── js/app.js               # Data loaders
│   ├── data/*.json             # Backtest & signal data
│   └── blog/                   # SEO blog articles
├── render.yaml                 # Render deployment
└── requirements.txt
```

## Scheduled Jobs (NZT)

| Time | Job | Frequency |
|------|-----|-----------|
| 09:15 | Market data fetch (post-close) | Tue-Sat |
| 09:30-09:50 | Entry/Exit checks + Signal tracking | Tue-Sat |
| 10:00 | Weekly momentum rotation | Saturday |
| 10:15-11:30 | AI sentiment, ETF flows, earnings | Tue-Sat |
| 03:30 | News fetch + AI classification | Tue-Sat |
| 04:00/07:30 | Geopolitical crisis scan | Tue-Sat |
| 12:00 1st | Monthly auto parameter tuning | Monthly |
| 15:00 | Knowledge base cleanup | Daily |

## Deployment

Deployed on Render with two services:
1. **API Server** (`stockqueen-api.onrender.com`) - FastAPI backend + dashboard
2. **Static Site** (`stockqueen-site.onrender.com`) - Public marketing site

## Disclaimer

This is a quantitative research system. Historical backtests do not guarantee future performance. Trading involves substantial risk of loss. Not financial advice.

## License

MIT License

---

*Built by Rayde Capital*
