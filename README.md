# 👑 StockQueen V1

AI-driven event-driven trading system for biotech stocks.

## 🎯 Overview

StockQueen is an automated trading system that:
- Monitors RSS feeds for biotech/pharma news (PR Newswire, FDA)
- Uses DeepSeek AI to classify events (Phase 2/3 results, FDA approvals, CRLs)
- Fetches market data via Tiger Open API
- Generates trading signals based on price/volume criteria
- Executes trades with hardcoded risk management rules
- Sends notifications via OpenClaw and Twilio SMS

## 🏗️ Architecture

```
[RSS News Layer]
        ↓
[Keyword Filter Layer]
        ↓
[DeepSeek Classification Layer]
        ↓
[Market Data Layer - Tiger API]
        ↓
[WebSocket Real-time Stream] ←──────────┐
        ↓                                  │
[Signal Engine]                           │
        ↓                                 │
[Confirmation Engine - D+1]               │
        ↓                                 │
[Risk Engine]                             │
        ↓                                 │
[Order Engine - Tiger API]                │
        ↓                                 │
[Notification Engine - OpenClaw + Twilio] │
        ↓                                 │
[Supabase Database] ←─────────────────────┘
```

### ✨ Key Features

- **🔌 WebSocket Long Connection**: Real-time market data streaming with automatic reconnection
- **🤖 AI Classification**: DeepSeek-powered news analysis and event classification
- **📊 Signal Engine**: Automated trading signal generation based on price/volume criteria
- **⚠️ Risk Management**: Hardcoded risk limits for capital protection
- **📱 Multi-channel Notifications**: Feishu + Twilio SMS alerts

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd stockqueen
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Setup Database

1. Create Supabase project at https://supabase.com
2. Run SQL from `database/schema.sql`
3. Copy Supabase URL and service key to `.env`

### 4. Run Locally

```bash
uvicorn app.main:app --reload
```

Visit http://localhost:8000/docs for API documentation.

## 🔌 WebSocket Quick Start

StockQueen supports real-time market data via WebSocket long connection:

```bash
# Start with WebSocket support
python start_websocket.bat

# Or test WebSocket connection
python test_websocket.py
```

### WebSocket API Examples

```bash
# Subscribe to real-time quotes
curl -X POST http://localhost:8000/api/websocket/subscribe \
  -d '{"ticker": "AAPL"}'

# Get connection status
curl http://localhost:8000/api/websocket/status

# View cached prices
curl http://localhost:8000/api/websocket/prices
```

See [WEBSOCKET_GUIDE.md](WEBSOCKET_GUIDE.md) for detailed configuration.

## 📋 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUPABASE_URL` | Supabase project URL | Yes |
| `SUPABASE_SERVICE_KEY` | Supabase service role key | Yes |
| `DEEPSEEK_API_KEY` | DeepSeek API key | Yes |
| `TIGER_ACCESS_TOKEN` | Tiger Open API access token | Yes |
| `TIGER_TIGER_ID` | Tiger ID | Yes |
| `TIGER_ACCOUNT` | Tiger trading account number | Yes |
| `TWILIO_ACCOUNT_SID` | Twilio account SID | Yes |
| `TWILIO_AUTH_TOKEN` | Twilio auth token | Yes |
| `TWILIO_PHONE_FROM` | Twilio phone number | Yes |
| `TWILIO_PHONE_TO` | Your phone number for alerts | Yes |
| `FEISHU_WEBHOOK_URL` | Feishu bot webhook URL | Optional |
| `FEISHU_APP_SECRET` | Feishu bot app secret | Optional |
| `TIGER_WS_URL` | Tiger WebSocket URL (auto-set) | Auto |

## 📊 Signal Criteria

### Long Signal
- Day gain ≥ 25%
- Volume ≥ 3x 30-day average
- Market cap: $500M - $4B

### Short Signal
- Day drop ≤ -30%
- Volume ≥ 3x 30-day average
- Market cap: $500M - $4B

## ⚠️ Risk Management (Hardcoded)

- Max positions: 2
- Risk per trade: 10% of account equity
- Max drawdown: 15% (triggers pause)
- Consecutive loss limit: 2 (triggers pause)

## 🕐 Daily Schedule (NZ Time)

| Time | Task |
|------|------|
| 06:30 | News fetch + AI classification |
| 07:00 | Market data fetch + Signal generation |
| 07:00 | Send signal summary for human confirmation |
| Next day 06:30 | D+1 confirmation check |

## 🛠️ Tech Stack

- **Backend**: Python + FastAPI
- **Database**: Supabase (PostgreSQL)
- **AI**: DeepSeek API
- **Broker**: Tiger Open API
- **Notifications**: OpenClaw + Twilio
- **Deployment**: Render

## 📁 Project Structure

```
stockqueen/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry
│   ├── config.py            # Configuration
│   ├── database.py          # Supabase client
│   ├── models.py            # Pydantic models
│   ├── scheduler.py         # APScheduler
│   ├── routers/             # API routes
│   │   ├── signals.py
│   │   └── risk.py
│   ├── services/            # Business logic
│   │   ├── news_service.py
│   │   ├── ai_service.py
│   │   ├── market_service.py
│   │   ├── signal_service.py
│   │   ├── risk_service.py
│   │   ├── order_service.py
│   │   └── notification_service.py
│   └── utils/               # Utilities
├── database/
│   └── schema.sql           # Database schema
├── requirements.txt
├── .env.example
├── .gitignore
├── render.yaml              # Render deployment config
└── README.md
```

## 🚢 Deployment

### Render (Recommended)

1. Push code to GitHub
2. Connect repository to Render
3. Add environment variables in Render dashboard
4. Deploy!

See `render.yaml` for configuration.

## 📝 API Endpoints

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/signals/observe` | GET | Get observe signals |
| `/api/signals/confirmed` | GET | Get confirmed signals |
| `/api/signals/confirm` | POST | Confirm/reject signal |
| `/api/signals/summary` | GET | Get signal summary |
| `/api/risk/status` | GET | Get risk status |
| `/api/risk/check` | GET | Check if trading allowed |

### WebSocket Management (Real-time Data)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/websocket/status` | GET | WebSocket connection status |
| `/api/websocket/subscribe` | POST | Subscribe to ticker quotes |
| `/api/websocket/unsubscribe` | POST | Unsubscribe from ticker |
| `/api/websocket/watchlist` | GET | Get subscribed tickers |
| `/api/websocket/watchlist/batch-subscribe` | POST | Batch subscribe |
| `/api/websocket/watchlist/clear` | DELETE | Clear all subscriptions |
| `/api/websocket/prices` | GET | Get all cached prices |
| `/api/websocket/prices/{ticker}` | GET | Get specific ticker price |

## ⚠️ Disclaimer

This is an experimental trading system. Use at your own risk. Always:
- Test with paper trading first
- Never risk more than you can afford to lose
- Monitor the system regularly
- Have manual override capabilities

## 📄 License

MIT License - See LICENSE file

## 🤝 Contributing

This is a personal project. Contributions welcome via issues and PRs.

---

**Built with ❤️ for systematic trading**
