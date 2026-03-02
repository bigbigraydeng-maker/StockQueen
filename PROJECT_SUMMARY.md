# StockQueen V1 - Project Summary

Complete project overview and implementation status.

---

## 📋 Project Overview

**StockQueen V1** is an AI-driven event-driven trading system for biotech stocks.

### Core Objectives

- ✅ Monitor RSS feeds for biotech/pharma news
- ✅ Use DeepSeek AI to classify events
- ✅ Generate trading signals based on price/volume criteria
- ✅ Execute trades with hardcoded risk management
- ✅ Send notifications via OpenClaw and Twilio

### Target Market

- **Focus**: Biotech/Pharma stocks
- **Data Sources**: PR Newswire, FDA RSS
- **Trading Style**: Event-driven, swing trading
- **Risk Profile**: Aggressive (max 15% drawdown)

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    StockQueen V1                        │
├─────────────────────────────────────────────────────────────┤
│                                                       │
│  ┌──────────────┐      ┌──────────────┐             │
│  │ RSS Feeds    │ ────▶│ Keyword      │             │
│  │ (PR/FDA)     │      │ Filter       │             │
│  └──────────────┘      └──────┬───────┘             │
│                                │                       │
│                                ▼                       │
│                       ┌──────────────┐               │
│                       │ DeepSeek AI  │               │
│                       │ Classifier   │               │
│                       └──────┬───────┘               │
│                              │                        │
│                              ▼                        │
│                       ┌──────────────┐               │
│                       │ Tiger API    │               │
│                       │ Market Data  │               │
│                       └──────┬───────┘               │
│                              │                        │
│                              ▼                        │
│                       ┌──────────────┐               │
│                       │ Signal       │               │
│                       │ Engine       │               │
│                       └──────┬───────┘               │
│                              │                        │
│                              ▼                        │
│                       ┌──────────────┐               │
│                       │ Risk Engine  │               │
│                       │ (Hardcoded)  │               │
│                       └──────┬───────┘               │
│                              │                        │
│                              ▼                        │
│                       ┌──────────────┐               │
│                       │ Order Engine │               │
│                       │ (Tiger API)  │               │
│                       └──────┬───────┘               │
│                              │                        │
│                              ▼                        │
│                       ┌──────────────┐               │
│                       │ Notification │               │
│                       │ (OpenClaw+   │               │
│                       │  Twilio)     │               │
│                       └──────────────┘               │
│                              │                        │
│                              ▼                        │
│                       ┌──────────────┐               │
│                       │ Supabase DB  │               │
│                       └──────────────┘               │
│                                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Signal Criteria

### Long Signal (Buy)
- **Price Gain**: ≥ 25% in one day
- **Volume**: ≥ 3x 30-day average
- **Market Cap**: $500M - $4B
- **Stop Loss**: 5% below entry
- **Target**: 10% above entry

### Short Signal (Sell)
- **Price Drop**: ≤ -30% in one day
- **Volume**: ≥ 3x 30-day average
- **Market Cap**: $500M - $4B
- **Stop Loss**: 5% above entry
- **Target**: 10% below entry

---

## ⚠️ Risk Management (Hardcoded)

| Rule | Value | Purpose |
|-------|--------|---------|
| Max Positions | 2 | Limit exposure |
| Risk Per Trade | 10% | Position sizing |
| Max Drawdown | 15% | System pause trigger |
| Consecutive Losses | 2 | System pause trigger |

---

## 🕐 Daily Schedule (NZ Time)

| Time | Task | Description |
|------|------|-------------|
| 06:30 | News Pipeline | Fetch RSS, classify with AI |
| 07:00 | Market Pipeline | Fetch data, generate signals |
| 07:00+ | Human Review | Confirm/reject signals |
| Next Day 06:30 | Confirmation | D+1 check, execute trades |

---

## 📁 Implementation Status

### ✅ Completed Modules

| Module | Status | Notes |
|---------|--------|-------|
| Project Structure | ✅ Complete | All directories created |
| Configuration | ✅ Complete | Pydantic settings |
| Database Schema | ✅ Complete | 9 tables with RLS |
| News Service | ✅ Complete | RSS + keyword filter |
| AI Service | ✅ Complete | DeepSeek integration |
| Market Service | ✅ Complete | Tiger API framework |
| Signal Engine | ✅ Complete | Generation + confirmation |
| Risk Engine | ✅ Complete | Hardcoded rules |
| Order Engine | ✅ Complete | Tiger API framework |
| Notification Service | ✅ Complete | Twilio + OpenClaw |
| API Endpoints | ✅ Complete | REST API |
| Scheduler | ✅ Complete | APScheduler |
| Test Scripts | ✅ Complete | 3 test scripts |
| Deployment Config | ✅ Complete | Render + Docker |
| Documentation | ✅ Complete | README + guides |

### ⚠️ Requires Configuration

| Component | Action Required |
|-----------|----------------|
| Supabase | Create project, run schema.sql |
| DeepSeek | Get API key |
| Tiger API | Get credentials, configure endpoints |
| Twilio | Get account, phone numbers |
| OpenClaw | Configure webhook URL |
| Tiger API Endpoints | Update with actual endpoints |

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-------------|----------|
| Backend | Python 3.11 + FastAPI | Web framework |
| Database | Supabase (PostgreSQL) | Data storage |
| AI | DeepSeek API | News classification |
| Broker | Tiger Open API | Trading execution |
| Notifications | OpenClaw + Twilio | Alerts |
| Scheduling | APScheduler | Task automation |
| Deployment | Render / Docker | Hosting |
| Monitoring | Custom metrics | Health checks |

---

## 📊 Database Schema

### Tables (9)

1. **events** - Raw RSS news
2. **ai_events** - AI classifications
3. **market_snapshots** - Market data
4. **signals** - Trading signals
5. **orders** - Trade orders
6. **trades** - Completed trades
7. **risk_state** - Current risk status
8. **system_logs** - Application logs
9. **api_call_logs** - External API logs

---

## 🚀 Deployment Options

### Option 1: Render (Recommended)
- **Cost**: $7-25/month
- **Pros**: Easy setup, auto-scaling
- **Cons**: Free tier may sleep

### Option 2: Docker
- **Cost**: VPS ($5-10/month)
- **Pros**: Full control, always running
- **Cons**: Manual setup

### Option 3: Local
- **Cost**: Free
- **Pros**: No cost, full control
- **Cons**: Requires always-on machine

---

## 📝 Next Steps for Production

1. **Configure APIs**
   - [ ] Get all API keys
   - [ ] Update `.env` file
   - [ ] Test each API connection

2. **Setup Database**
   - [ ] Create Supabase project
   - [ ] Run `schema.sql`
   - [ ] Verify tables created

3. **Test End-to-End**
   - [ ] Run news fetch test
   - [ ] Run AI classification test
   - [ ] Run signal generation test
   - [ ] Test notification system

4. **Paper Trading**
   - [ ] Setup paper trading account
   - [ ] Run for 1-2 months
   - [ ] Track performance

5. **Deploy**
   - [ ] Choose deployment option
   - [ ] Deploy application
   - [ ] Configure monitoring

6. **Go Live**
   - [ ] Start with small capital
   - [ ] Monitor closely
   - [ ] Adjust parameters as needed

---

## 🎯 Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| System Uptime | 99%+ | TBD |
| Signal Accuracy | 55%+ | TBD |
| Win Rate | 55%+ | TBD |
| Risk Limit Breaches | 0 | TBD |
| API Errors | <1% | TBD |

---

## 📞 Support Resources

- **Documentation**: `README.md`, `DEPLOYMENT.md`, `QUICKSTART.md`
- **API Docs**: `/docs` endpoint
- **Test Scripts**: `scripts/` directory
- **Logs**: `stockqueen.log` + database logs

---

## ⚠️ Disclaimer

**This is an experimental trading system.**

- Always test with paper trading first
- Never risk more than you can afford to lose
- Monitor system regularly
- Have manual override capabilities
- Past performance does not guarantee future results

---

## 📄 License

MIT License - See LICENSE file

---

**Built with ❤️ for systematic trading**

**Version**: 1.0.0
**Status**: ✅ Ready for Testing
**Last Updated**: 2025-02-25
