# StockQueen V1 - Deployment Guide

Complete deployment guide for StockQueen V1.

---

## 📋 Prerequisites

Before deploying, ensure you have:

- [ ] Supabase account (https://supabase.com)
- [ ] DeepSeek API key (https://platform.deepseek.com)
- [ ] Tiger Securities account with API access
- [ ] Twilio account (https://www.twilio.com)
- [ ] OpenClaw account (for notifications)
- [ ] GitHub account (for Render deployment)
- [ ] Render account (https://render.com)

---

## 🚀 Local Development Setup

### 1. Clone Repository

```bash
git clone <your-repo-url>
cd stockqueen
```

### 2. Create Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required environment variables:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `DEEPSEEK_API_KEY`
- `TIGER_ACCESS_TOKEN`
- `TIGER_TIGER_ID`
- `TIGER_ACCOUNT`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_FROM`
- `TWILIO_PHONE_TO`

### 5. Initialize Database

1. Go to https://supabase.com/dashboard
2. Create a new project
3. Go to SQL Editor
4. Copy contents of `database/schema.sql`
5. Paste and click "Run"

6. Copy Supabase URL and Service Role Key:
   - Settings → API → Project URL
   - Settings → API → service_role (secret)

7. Add to `.env`:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_KEY=your-service-role-key
   ```

### 6. Run Application

**Windows:**
```bash
start.bat
```

**Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

Or manually:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 7. Test Application

Visit http://localhost:8000/docs for API documentation.

Run tests:
```bash
# Test API endpoints
python scripts/test_api.py

# Test news fetch
python scripts/test_news_fetch.py

# Test AI classification
python scripts/test_ai_classification.py
```

---

## 🌐 Render Deployment

### 1. Prepare Repository

```bash
# Initialize git (if not already)
git init
git add .
git commit -m "Initial commit: StockQueen V1"

# Push to GitHub
git branch -M main
git remote add origin https://github.com/your-username/stockqueen.git
git push -u origin main
```

### 2. Create Render Service

1. Go to https://dashboard.render.com
2. Click "New +"
3. Select "Web Service"
4. Connect your GitHub repository
5. Configure:

   **Name:** `stockqueen-api`

   **Region:** Oregon (or closest to you)

   **Branch:** `main`

   **Runtime:** `Python 3`

   **Build Command:**
   ```
   pip install -r requirements.txt
   ```

   **Start Command:**
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

6. Click "Create Web Service"

### 3. Add Environment Variables

In Render dashboard → Environment:

1. Click "Add Environment Variable"
2. Add all variables from `.env.example`
3. **Important:** Set `APP_ENV=production`
4. Click "Save Changes"

### 4. Deploy

- Render will automatically deploy on push
- Monitor deployment logs in Render dashboard
- Once deployed, you'll get a URL like: `https://stockqueen-api.onrender.com`

### 5. Verify Deployment

1. Visit `https://stockqueen-api.onrender.com/health`
2. Should return: `{"status": "healthy", ...}`
3. Visit `https://stockqueen-api.onrender.com/docs` for API docs

---

## ⏰ Scheduled Tasks

StockQueen uses APScheduler for scheduled tasks. Tasks run automatically:

| Time (NZ) | Task |
|------------|------|
| 06:30 | News fetch + AI classification |
| 07:00 | Market data fetch + Signal generation |
| 06:30 (next day) | D+1 confirmation check |

**Note:** Render's free tier may sleep the web service when inactive. For reliable scheduling:

### Option 1: Use Render Cron Jobs (Paid)
- Create a "Cron Job" service in Render
- Configure to call your API endpoints at scheduled times

### Option 2: Use External Scheduler
- Use OpenClaw (as designed)
- Or use cron-job.org, EasyCron, etc.

### Option 3: Upgrade to Render Standard
- Standard plan ($25/month) keeps web service running 24/7

---

## 🔒 Security Checklist

- [ ] Never commit `.env` to git
- [ ] Use strong API keys
- [ ] Rotate API keys regularly
- [ ] Enable 2FA on all accounts
- [ ] Use HTTPS in production
- [ ] Set up firewall rules in Supabase
- [ ] Monitor logs for suspicious activity
- [ ] Set up alerts for API failures

---

## 📊 Monitoring

### Application Logs

View logs in Render dashboard → Logs

### Database Monitoring

Supabase dashboard → Database → Logs

### API Health Check

```bash
curl https://stockqueen-api.onrender.com/health
```

### Risk Status

```bash
curl https://stockqueen-api.onrender.com/api/risk/status
```

---

## 🐛 Troubleshooting

### Issue: Database Connection Failed

**Solution:**
1. Verify `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are correct
2. Check Supabase project is active
3. Verify database tables exist (run schema.sql)

### Issue: DeepSeek API Error

**Solution:**
1. Verify `DEEPSEEK_API_KEY` is valid
2. Check API quota at https://platform.deepseek.com
3. Verify `deepseek-chat` model is available

### Issue: Tiger API Error

**Solution:**
1. Verify `TIGER_ACCESS_TOKEN` and `TIGER_TIGER_ID`
2. Check Tiger API documentation for correct endpoints
3. Verify account has trading permissions

### Issue: Twilio SMS Not Sending

**Solution:**
1. Verify `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`
2. Check Twilio phone numbers are verified
3. Verify account has SMS credits

### Issue: Render Deployment Fails

**Solution:**
1. Check build logs in Render dashboard
2. Verify `requirements.txt` is correct
3. Check for syntax errors in Python files
4. Verify all environment variables are set

### Issue: Scheduled Tasks Not Running

**Solution:**
1. Check application logs for scheduler errors
2. Verify timezone is correct (`TIMEZONE=Pacific/Auckland`)
3. Check if web service is sleeping (Render free tier)
4. Consider upgrading to Standard plan

---

## 📝 Post-Deployment Checklist

- [ ] Database schema created
- [ ] All environment variables configured
- [ ] Health check endpoint working
- [ ] API documentation accessible
- [ ] Test news fetch works
- [ ] Test AI classification works
- [ ] Test signal generation works
- [ ] Test risk checks work
- [ ] Twilio SMS alerts working
- [ ] Scheduled tasks running
- [ ] Logs being captured
- [ ] Monitoring set up

---

## 🎯 Next Steps

1. **Paper Trading**: Test with paper trading account first
2. **Backtesting**: Run historical data to validate signals
3. **Optimization**: Adjust thresholds based on performance
4. **Monitoring**: Set up alerts for system health
5. **Documentation**: Document any customizations

---

## 📞 Support

- **Documentation**: See `README.md`
- **API Docs**: Visit `/docs` endpoint
- **Logs**: Check Render and Supabase dashboards
- **Issues**: Report bugs via GitHub issues

---

**Happy Trading! 🚀**
