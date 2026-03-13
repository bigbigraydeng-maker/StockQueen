# StockQueen V2.3

AI-driven multi-factor rotation system for US equities and ETFs.

## Overview

StockQueen is a quantitative rotation strategy system that automatically selects and rebalances a portfolio of US stocks and ETFs based on market conditions. It combines multiple data sources and analytical factors to generate weekly portfolio recommendations with daily entry/exit timing.

### Key Capabilities

- **Market Regime Detection** - Automatically identifies bull/bear/choppy market phases and adjusts strategy accordingly
- **Multi-Factor Scoring** - Proprietary scoring engine evaluates 80+ tickers across multiple dimensions
- **Adaptive Portfolio** - Rotates between offensive (growth stocks, tech ETFs), defensive (bonds, gold), and inverse (short ETFs) based on regime
- **Daily Signal Generation** - Entry/exit timing with ATR-based stop-loss and take-profit levels
- **Walk-Forward Backtest** - Rolling optimization engine to validate strategy robustness
- **Dual Benchmark** - Performance tracked against both SPY (S&P 500) and QQQ (Nasdaq 100)
- **Knowledge Base Integration** - AI-powered news sentiment and fundamental analysis
- **Real-time Dashboard** - Web UI with portfolio monitoring, weekly reports, and glossary

## Architecture

```
[Market Data Layer - Alpha Vantage]
        |
[Knowledge Base - Supabase]  ←  [AI Sentiment Collector]
        |                        [Fundamental Collector]
        ↓
[Multi-Factor Scoring Engine]
        |
    Proprietary
    Algorithm
        |
        ↓
[Rotation Selection]  →  [Weekly Rebalance]
        ↓
[Daily Entry/Exit Timing]
        ↓
[Notification Engine - Feishu]
        ↓
[Dashboard - FastAPI + HTMX]
```

## Coverage

| Category | Count | Examples |
|----------|-------|---------|
| Growth Stocks | 60+ | Tech, SaaS, Semiconductors, AI, China ADR |
| Offensive ETFs | 10+ | Sector and thematic ETFs |
| Defensive ETFs | 5+ | Bonds, Gold, Cash equivalents |
| Inverse ETFs | 4 | Market hedge instruments |

## Tech Stack

- **Backend**: Python 3.12 + FastAPI
- **Frontend**: Jinja2 + HTMX + Tailwind CSS + Chart.js
- **Database**: Supabase (PostgreSQL)
- **Market Data**: Alpha Vantage (Premium)
- **AI**: DeepSeek API (news classification & sentiment)
- **Notifications**: Feishu (weekly reports)
- **Deployment**: Render (Web Service + Background Worker)

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd StockQueen
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |
| `ALPHA_VANTAGE_KEY` | Alpha Vantage API key (Premium recommended) |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `FEISHU_WEBHOOK_URL` | Feishu bot webhook URL (optional) |

### 3. Run Locally

```bash
uvicorn app.main:app --reload --port 8000
```

Visit `http://localhost:8000` for the dashboard.

## Project Structure

```
StockQueen/
├── app/
│   ├── main.py                    # FastAPI application entry
│   ├── config/
│   │   ├── settings.py            # Environment configuration
│   │   └── rotation_watchlist.py  # Stock universe & parameters
│   ├── models.py                  # Pydantic data models
│   ├── routers/
│   │   ├── api.py                 # REST API endpoints
│   │   └── web.py                 # Web UI routes + HTMX
│   ├── services/
│   │   ├── rotation_service.py    # Core rotation engine
│   │   ├── multi_factor_scorer.py # Scoring algorithm
│   │   ├── alphavantage_client.py # Market data client
│   │   ├── knowledge_service.py   # Knowledge base queries
│   │   ├── knowledge_collectors.py # Data collectors
│   │   └── notification_service.py # Feishu notifications
│   └── templates/                 # Jinja2 HTML templates
├── docs/                          # Documentation
├── .cache/                        # Local data cache (gitignored)
├── render.yaml                    # Render deployment config
└── requirements.txt
```

## Web Dashboard

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Portfolio overview, positions, weekly report |
| Backtest | `/backtest` | Strategy backtest + Walk-Forward optimization |
| Knowledge | `/knowledge` | Knowledge base browser |
| API Docs | `/docs` | FastAPI auto-generated documentation |

## Deployment

### Render

1. Push code to GitHub
2. Connect repository to Render
3. Add environment variables in Render dashboard
4. Deploy (see `render.yaml` for service configuration)

The system uses two Render services:
- **Web Service** - Dashboard + API
- **Background Worker** - Scheduled data collection and signal generation

## Disclaimer

This is an experimental quantitative trading system for research and educational purposes. It is not financial advice. Always:

- Test with paper trading before committing real capital
- Never risk more than you can afford to lose
- Monitor the system regularly
- Maintain manual override capabilities
- Past backtest performance does not guarantee future results

## License

Private - All Rights Reserved

---

**Built with Python + AI for systematic investing**
