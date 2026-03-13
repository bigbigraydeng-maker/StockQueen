# StockQueen Weekly Report - Integration Guide

## Overview

This document describes how to integrate the Weekly Quant Report system with Supabase for newsletter subscription management and email delivery.

---

## PART 1: Supabase Setup

### 1.1 Create Supabase Project

1. Go to [https://supabase.com](https://supabase.com)
2. Create a new project
3. Note down your `Project URL` and `Anon Key`

### 1.2 Database Schema

Create the following table in Supabase SQL Editor:

```sql
-- Newsletter subscribers table
CREATE TABLE newsletter_subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    language_preference VARCHAR(2) NOT NULL DEFAULT 'en',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    last_email_sent TIMESTAMP WITH TIME ZONE
);

-- Create index for faster queries
CREATE INDEX idx_newsletter_lang ON newsletter_subscribers(language_preference);
CREATE INDEX idx_newsletter_active ON newsletter_subscribers(is_active);

-- Enable Row Level Security
ALTER TABLE newsletter_subscribers ENABLE ROW LEVEL SECURITY;

-- Create policy for anonymous inserts (subscription)
CREATE POLICY "Allow anonymous subscription" 
ON newsletter_subscribers 
FOR INSERT 
TO anon 
WITH CHECK (true);

-- Create policy for anonymous select (check if email exists)
CREATE POLICY "Allow anonymous check" 
ON newsletter_subscribers 
FOR SELECT 
TO anon 
USING (true);
```

### 1.3 Environment Variables

Add to your deployment environment:

```bash
SUPABASE_URL=your_project_url
SUPABASE_ANON_KEY=your_anon_key
```

---

## PART 2: Frontend Integration

### 2.1 Add Supabase Client

Create `js/supabase.js`:

```javascript
import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm'

const supabaseUrl = 'YOUR_SUPABASE_URL'
const supabaseKey = 'YOUR_SUPABASE_ANON_KEY'

export const supabase = createClient(supabaseUrl, supabaseKey)

// Subscribe function
export async function subscribeNewsletter(email, language) {
    try {
        const { data, error } = await supabase
            .from('newsletter_subscribers')
            .insert([
                { email, language_preference: language }
            ])
        
        if (error) throw error
        return { success: true, data }
    } catch (error) {
        if (error.code === '23505') {
            return { success: false, error: 'Email already subscribed' }
        }
        return { success: false, error: error.message }
    }
}

// Get subscribers by language
export async function getSubscribersByLanguage(language) {
    const { data, error } = await supabase
        .from('newsletter_subscribers')
        .select('*')
        .eq('language_preference', language)
        .eq('is_active', true)
    
    if (error) throw error
    return data
}
```

### 2.2 Update Newsletter Form

Replace the localStorage-based subscription with Supabase:

```javascript
import { subscribeNewsletter } from './js/supabase.js'

document.getElementById('newsletter-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const email = document.getElementById('newsletter-email').value;
    const language = document.querySelector('input[name="newsletter-lang"]:checked').value;
    const messageEl = document.getElementById('newsletter-message');
    
    const result = await subscribeNewsletter(email, language);
    
    if (result.success) {
        messageEl.textContent = 'Thank you for subscribing!';
        messageEl.style.color = '#34d399';
        messageEl.style.background = 'rgba(52, 211, 153, 0.1)';
        this.reset();
    } else {
        messageEl.textContent = result.error;
        messageEl.style.color = '#f87171';
        messageEl.style.background = 'rgba(248, 113, 113, 0.1)';
    }
    messageEl.style.display = 'block';
    
    setTimeout(() => {
        messageEl.style.display = 'none';
    }, 5000);
});
```

---

## PART 3: Email Delivery API

### 3.1 Using Resend (Recommended)

Create `api/send-weekly-report.js` (for serverless deployment):

```javascript
import { Resend } from 'resend'
import { createClient } from '@supabase/supabase-js'

const resend = new Resend(process.env.RESEND_API_KEY)
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY)

export default async function handler(req, res) {
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' })
    }
    
    const { week, year } = req.body
    
    try {
        // Get English subscribers
        const { data: enSubscribers } = await supabase
            .from('newsletter_subscribers')
            .select('email')
            .eq('language_preference', 'en')
            .eq('is_active', true)
        
        // Get Chinese subscribers
        const { data: zhSubscribers } = await supabase
            .from('newsletter_subscribers')
            .select('email')
            .eq('language_preference', 'zh')
            .eq('is_active', true)
        
        // Send English emails
        if (enSubscribers?.length > 0) {
            await resend.emails.send({
                from: 'StockQueen <weekly@stockqueen.io>',
                bcc: enSubscribers.map(s => s.email),
                subject: `StockQueen Weekly Quant Report — Week ${week}`,
                html: await generateEmailHTML('en', week, year),
            })
        }
        
        // Send Chinese emails
        if (zhSubscribers?.length > 0) {
            await resend.emails.send({
                from: 'StockQueen <weekly@stockqueen.io>',
                bcc: zhSubscribers.map(s => s.email),
                subject: `StockQueen 每周量化市场报告 — 第${week}周`,
                html: await generateEmailHTML('zh', week, year),
            })
        }
        
        // Update last_email_sent
        await supabase
            .from('newsletter_subscribers')
            .update({ last_email_sent: new Date().toISOString() })
            .eq('is_active', true)
        
        res.status(200).json({ 
            success: true, 
            enSent: enSubscribers?.length || 0,
            zhSent: zhSubscribers?.length || 0 
        })
        
    } catch (error) {
        res.status(500).json({ error: error.message })
    }
}

async function generateEmailHTML(language, week, year) {
    // Load and convert markdown to HTML
    // Return formatted email HTML
}
```

### 3.2 Environment Variables for Resend

```bash
RESEND_API_KEY=re_xxxxxxxx
```

---

## PART 4: Automation Pipeline (Future)

### 4.1 Report Generation Flow

```
Market Data (Alpha Vantage)
    ↓
AI Analysis (OpenAI GPT-4)
    ↓
Markdown Report Generated
    ↓
Saved to /content/week-XX-YYYY.md
    ↓
HTML Page Auto-generated
    ↓
Newsletter Sent via API
```

### 4.2 GitHub Actions Workflow

Create `.github/workflows/publish-report.yml`:

```yaml
name: Publish Weekly Report

on:
  schedule:
    - cron: '0 9 * * 1'  # Every Monday at 9 AM
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Generate Report
        run: |
          # Run report generation script
          node scripts/generate-weekly-report.js
      
      - name: Deploy to Render
        run: |
          # Trigger Render deployment
          curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK }}
      
      - name: Send Newsletter
        run: |
          # Call API to send emails
          curl -X POST https://stockqueen.io/api/send-weekly-report \
            -H "Authorization: Bearer ${{ secrets.API_KEY }}" \
            -d '{"week": "${{ env.WEEK }}", "year": "${{ env.YEAR }}"}'
```

---

## PART 5: File Structure

```
site/
├── weekly-report/
│   ├── index.html              # English listing page
│   ├── index-zh.html           # Chinese listing page
│   ├── week-XX-YYYY.html       # Individual report pages
│   ├── week-XX-YYYY-zh.html    # Chinese report pages
│   ├── content/                # Markdown source files
│   │   ├── week-XX-YYYY.md
│   │   └── week-XX-YYYY-zh.md
│   ├── js/
│   │   └── supabase.js         # Supabase client
│   └── INTEGRATION.md          # This file
├── blog/
│   └── index.html              # With newsletter CTA
├── index.html                  # With weekly report link
└── index-zh.html
```

---

## PART 6: Next Steps

1. **Set up Supabase project** and create the table
2. **Get Resend API key** for email delivery
3. **Update frontend** to use Supabase client
4. **Deploy API endpoint** for sending emails
5. **Test subscription flow** end-to-end
6. **Create first weekly report** manually
7. **Set up automation** for future reports

---

## Support

For questions or issues, contact: support@stockqueen.io