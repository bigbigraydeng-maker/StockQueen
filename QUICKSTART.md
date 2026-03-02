# StockQueen V1 - Quick Start Guide

Get StockQueen up and running in 10 minutes!

---

## 🚀 Quick Start (Windows)

### 1. Setup Environment

```powershell
# Navigate to project directory
cd C:\Users\Zhong\Documents\trae_projects\StockQueen

# Run startup script
start.bat
```

This will:
- Create virtual environment
- Install dependencies
- Start the server

### 2. Configure API Keys

Edit `.env` file with your API keys:

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key

# DeepSeek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# Tiger
TIGER_ACCESS_TOKEN=your-token
TIGER_TIGER_ID=your-id
TIGER_ACCOUNT=your-account

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_PHONE_FROM=+1234567890
TWILIO_PHONE_TO=+6491234567
```

### 3. Setup Database

1. Go to https://supabase.com/dashboard
2. Create project
3. Go to SQL Editor
4. Copy `database/schema.sql` content
5. Paste and click "Run"

### 4. Access Application

- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

---

## 🧪 Test the System

### Test API Endpoints

```powershell
python scripts\test_api.py
```

### Test News Fetch

```powershell
python scripts\test_news_fetch.py
```

### Test AI Classification

```powershell
python scripts\test_ai_classification.py
```

---

## 📊 Daily Workflow

### 06:30 NZ Time
- System automatically fetches news
- AI classifies events
- Results saved to database

### 07:00 NZ Time
- Market data fetched
- Signals generated
- You receive notification via OpenClaw

### Your Action (07:00+)
1. Visit http://localhost:8000/docs
2. Check `/api/signals/observe`
3. Confirm signals via `/api/signals/confirm`

### Next Day 06:30
- D+1 confirmation check
- Trades executed if conditions met

---

## 🎯 Key Features

| Feature | Status |
|---------|--------|
| RSS News Fetch | ✅ Ready |
| AI Classification | ✅ Ready |
| Market Data | ✅ Framework |
| Signal Generation | ✅ Ready |
| Risk Management | ✅ Ready |
| Order Execution | ✅ Framework |
| Notifications | ✅ Ready |
| API Endpoints | ✅ Ready |
| Scheduled Tasks | ✅ Ready |

---

## 📁 Project Structure

```
StockQueen/
├── app/                    # Main application
│   ├── routers/            # API endpoints
│   ├── services/           # Business logic
│   ├── utils/              # Utilities
│   ├── main.py             # FastAPI app
│   ├── config.py           # Configuration
│   └── models.py          # Data models
├── database/
│   └── schema.sql         # Database schema
├── scripts/               # Test scripts
│   ├── test_api.py
│   ├── test_news_fetch.py
│   └── test_ai_classification.py
├── start.bat             # Windows startup
├── start.sh              # Linux/Mac startup
├── requirements.txt       # Dependencies
├── .env.example         # Config template
└── README.md            # Full documentation
```

---

## 🔧 Common Tasks

### View Current Signals

```powershell
curl http://localhost:8000/api/signals/observe
```

### Check Risk Status

```powershell
curl http://localhost:8000/api/risk/status
```

### Confirm a Signal

```powershell
curl -X POST http://localhost:8000/api/signals/confirm `
  -H "Content-Type: application/json" `
  -d '{"signal_id": "uuid", "confirmed": true}'
```

### View Logs

```powershell
Get-Content stockqueen.log -Tail 50
```

---

## ⚠️ Important Notes

1. **Test First**: Always test with paper trading
2. **API Keys**: Never commit `.env` to git
3. **Database**: Run `schema.sql` in Supabase SQL Editor
4. **Timezone**: System uses NZ time by default
5. **Monitoring**: Check logs regularly

---

## 🆘 Troubleshooting

### Server won't start
- Check Python version (3.11+)
- Verify dependencies installed
- Check port 8000 is available

### Database errors
- Verify Supabase URL and key
- Ensure schema is created
- Check Supabase project is active

### API errors
- Verify all API keys are correct
- Check API quotas
- Review error logs

---

## 📚 Next Steps

1. ✅ Complete setup
2. ✅ Run tests
3. ✅ Configure API keys
4. ✅ Setup database
5. 📝 Read [DEPLOYMENT.md](DEPLOYMENT.md) for production
6. 🚀 Deploy to Render

---

**Need help?** Check [README.md](README.md) or [DEPLOYMENT.md](DEPLOYMENT.md)

**Happy Trading! 🚀**
