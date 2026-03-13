# StockQueen V3 - AI Adaptive Rotation Strategy

Multi-factor momentum rotation strategy for US equities & ETFs with regime-adaptive position management.

**Live Dashboard**: https://stockqueen-api.onrender.com/dashboard
**Public Site**: https://stockqueen-site.onrender.com

## Current Performance (Apr 2023 - Mar 2026)

| Metric | Value | Note |
|--------|-------|------|
| Total Return | 94.5% | vs SPY 69.6%, QQQ 93.3% |
| Annualized Return | 24.8% | |
| Sharpe Ratio | 0.73 | Target: >1.0 |
| Max Drawdown | -33.2% | Target: <20% |
| Win Rate | 49% | |
| Alpha vs SPY | +24.9% | |
| Alpha vs QQQ | +1.2% | Needs improvement |

> **Known Issues**: Drawdown too high (33%), Sharpe below 1.0, alpha vs QQQ not compelling. Strategy tuning planned.

## Architecture

```
[Daily Scheduler (NZT 10:00)]
        |
[Watchlist: 80+ US Stocks & ETFs]
        |
[Multi-Factor Scoring Engine]
   - Momentum (price, volume, RSI, MACD)
   - Fundamentals (earnings, revenue growth)
   - Technical indicators (ATR, Bollinger, OBV)
        |
[Market Regime Detection]
   - BULL  -> Offensive positions (growth stocks)
   - BEAR  -> Inverse ETFs (SH, PSQ, DOG)
   - CHOPPY -> Defensive (GLD, SHY, VGIT)
        |
[Position Sizing & Risk Management]
   - ATR-based stop-loss / take-profit
   - Sector concentration limits
   - Portfolio drawdown controls
        |
[Tiger Open API - Order Execution]
        |
[Dashboard + Public Site]
```

## Tech Stack

- **Backend**: Python + FastAPI + APScheduler (21 scheduled jobs)
- **Database**: Supabase (PostgreSQL)
- **Broker**: Tiger Open API (real-time quotes + order execution)
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
│   ├── scheduler.py            # APScheduler (21 daily jobs)
│   ├── models.py               # Pydantic models
│   ├── config/
│   │   └── rotation_watchlist.py  # 80+ ticker universe
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
| 10:00 | Daily rotation scan | Tue-Sat |
| 10:30 | Pattern statistics + Sector rotation | Tue-Sat |
| 03:00-09:30 | Real-time price tracking | Every 30min (trading hours) |
| 06:00 | News fetch + AI classification | Daily |
| 12:00 | Health check + DB cleanup | Daily |

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
