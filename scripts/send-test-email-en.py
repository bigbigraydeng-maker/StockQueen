#!/usr/bin/env python3
"""
StockQueen Newsletter Test Email Script (English Version)
Using Resend API - Reads configuration from environment variables
"""

import os
import sys

def install_package(package):
    """Install missing package"""
    print(f"Installing {package}...")
    os.system(f"{sys.executable} -m pip install {package}")

try:
    from dotenv import load_dotenv
except ImportError:
    install_package("python-dotenv")
    from dotenv import load_dotenv

try:
    import resend
except ImportError:
    install_package("resend")
    import resend

# Load environment variables
load_dotenv()

# ==================== Configuration (from environment variables) ====================

# 1. Resend API Key
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

# 2. Sender email
FROM_EMAIL = os.getenv("FROM_EMAIL", "onboarding@resend.dev")

# 3. Recipient email (can be passed via command line)
TO_EMAIL = os.getenv("TO_EMAIL", "")

# 4. Email subject
SUBJECT = "StockQueen Weekly Quant Report - Test Email"

# ==================== Email Content ====================

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>StockQueen Weekly Report</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">

    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">Weekly Quantitative Strategy Report</p>
    </div>

    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <p style="color: #64748b; font-size: 12px; margin-bottom: 20px;">March 21, 2026 | Week 12</p>

        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">Strategy Performance Summary</h2>
        
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <tr>
                <td style="padding: 15px; background: #f0fdf4; border-radius: 8px 0 0 8px; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">Weekly Return</p>
                    <p style="color: #059669; font-size: 28px; font-weight: bold; margin: 4px 0 0 0;">+2.8%</p>
                </td>
                <td style="padding: 15px; background: #fef2f2; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">S&P 500</p>
                    <p style="color: #dc2626; font-size: 28px; font-weight: bold; margin: 4px 0 0 0;">-1.2%</p>
                </td>
                <td style="padding: 15px; background: #f0fdf4; border-radius: 0 8px 8px 0; width: 33%; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">Alpha</p>
                    <p style="color: #059669; font-size: 28px; font-weight: bold; margin: 4px 0 0 0;">+4.0%</p>
                </td>
            </tr>
        </table>

        <h2 style="color: #0f172a; font-size: 18px; margin-bottom: 12px;">Current Positions</h2>
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
            <thead>
                <tr style="background: #f1f5f9;">
                    <th style="padding: 12px; text-align: left; font-size: 12px; color: #475569;">Ticker</th>
                    <th style="padding: 12px; text-align: right; font-size: 12px; color: #475569;">Return</th>
                </tr>
            </thead>
            <tbody>
                <tr style="border-bottom: 1px solid #e2e8f0;">
                    <td style="padding: 12px;">
                        <strong>SH</strong> <span style="color: #64748b; font-size: 12px;">Short S&P 500</span>
                    </td>
                    <td style="padding: 12px; text-align: right; color: #059669; font-weight: bold;">+4.1%</td>
                </tr>
                <tr style="border-bottom: 1px solid #e2e8f0;">
                    <td style="padding: 12px;">
                        <strong>PSQ</strong> <span style="color: #64748b; font-size: 12px;">Short QQQ</span>
                    </td>
                    <td style="padding: 12px; text-align: right; color: #059669; font-weight: bold;">+3.6%</td>
                </tr>
                <tr>
                    <td style="padding: 12px;">
                        <strong>DOG</strong> <span style="color: #64748b; font-size: 12px;">Short Dow 30</span>
                    </td>
                    <td style="padding: 12px; text-align: right; color: #059669; font-weight: bold;">+2.9%</td>
                </tr>
            </tbody>
        </table>

        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 16px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
            <p style="color: #92400e; font-size: 14px; margin: 0;">
                <strong>Market Regime:</strong> Bearish Defense (BEAR)
            </p>
        </div>

        <h2 style="color: #0f172a; font-size: 18px; margin-bottom: 12px;">📰 This Week's Market Insights</h2>
        <div style="background: #f8fafc; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
            <div style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #e2e8f0;">
                <p style="color: #64748b; font-size: 11px; margin: 0 0 4px 0;">Federal Reserve Policy</p>
                <p style="color: #0f172a; font-size: 14px; margin: 0; line-height: 1.5;">
                    The Fed kept interest rates unchanged, hinting at 2 potential rate cuts this year. Market volatility increased as risk-off sentiment grows.
                </p>
            </div>
            <div style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #e2e8f0;">
                <p style="color: #64748b; font-size: 11px; margin: 0 0 4px 0;">Tech Sector Movement</p>
                <p style="color: #0f172a; font-size: 14px; margin: 0; line-height: 1.5;">
                    Major tech stocks saw significant pullback this week, with Nasdaq down 2.5%. Capital is rotating into defensive sectors.
                </p>
            </div>
            <div>
                <p style="color: #64748b; font-size: 11px; margin: 0 0 4px 0;">AI Analysis View</p>
                <p style="color: #0f172a; font-size: 14px; margin: 0; line-height: 1.5;">
                    Multi-factor model indicates bear market conditions. Short strategies continue to outperform the market. Maintaining defensive positioning is recommended.
                </p>
            </div>
        </div>

        <h2 style="color: #0f172a; font-size: 18px; margin-bottom: 12px;">📊 Strategy Review</h2>
        <div style="background: #f0fdf4; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
            <p style="color: #166534; font-size: 14px; margin: 0; line-height: 1.6;">
                The strategy continued to outperform the market this week, with inverse ETF portfolio delivering positive returns amid market decline. 
                Since the beginning of 2026, the strategy has returned <strong>+94.5%</strong> vs S&P 500 <strong>+8.2%</strong>.
            </p>
        </div>

        <h2 style="color: #0f172a; font-size: 18px; margin-bottom: 12px;">🔮 Next Week Outlook</h2>
        <div style="background: #eff6ff; border-radius: 8px; padding: 16px; margin-bottom: 24px;">
            <ul style="color: #1e40af; font-size: 14px; margin: 0; padding-left: 20px; line-height: 1.8;">
                <li>Watch for Fed officials' speeches and inflation data</li>
                <li>Tech earnings season approaching - volatility expected to increase</li>
                <li>Strategy maintains bearish defense positioning with selective adjustments</li>
            </ul>
        </div>

        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen-site.onrender.com/weekly-report/" 
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%); 
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px; 
                      font-weight: 600; font-size: 14px;">
                View Full Report
            </a>
        </div>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">

        <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
            StockQueen Quantitative Research Team | Rayde Capital<br>
            <a href="https://stockqueen-site.onrender.com" style="color: #0891b2; text-decoration: none;">stockqueen.io</a>
        </p>
    </div>

</body>
</html>
"""

# ==================== Send Function ====================

def send_email(to_email=None):
    """Send test email"""
    
    # Use provided email or from environment variable
    recipient = to_email or TO_EMAIL
    
    # Validate configuration
    if not RESEND_API_KEY:
        print("❌ Error: RESEND_API_KEY not set")
        print("   Please set it in .env file:")
        print("   RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxx")
        return False
    
    if not RESEND_API_KEY.startswith("re_"):
        print("❌ Error: RESEND_API_KEY format incorrect")
        print("   Should start with 're_'")
        return False
    
    if not recipient:
        print("❌ Error: Recipient email not set")
        print("   Option 1: Set TO_EMAIL=your@email.com in .env file")
        print("   Option 2: Pass via command line: python send-test-email-en.py your@email.com")
        return False
    
    try:
        resend.api_key = RESEND_API_KEY
        
        params = {
            "from": FROM_EMAIL,
            "to": [recipient],
            "subject": SUBJECT,
            "html": HTML_CONTENT,
        }
        
        print(f"📧 Sending email to {recipient}...")
        email = resend.Emails.send(params)
        
        print(f"✅ Email sent successfully!")
        print(f"   Email ID: {email['id']}")
        print(f"   Recipient: {recipient}")
        print(f"   Sender: {FROM_EMAIL}")
        return True
        
    except Exception as e:
        print(f"❌ Send failed: {e}")
        print("\nCommon issues:")
        print("   - Is the API Key correct?")
        print("   - Is the sender email verified?")
        print("   - Is the recipient email address correct?")
        print("   - Have you exceeded daily limit (100 emails/day for free tier)?")
        return False

def show_config():
    """Display current configuration"""
    print("=" * 50)
    print("📋 Current Configuration")
    print("=" * 50)
    print(f"API Key: {'✅ Set' if RESEND_API_KEY else '❌ Not set'}")
    print(f"Sender: {FROM_EMAIL}")
    print(f"Recipient: {TO_EMAIL or '❌ Not set'}")
    print("=" * 50)

if __name__ == "__main__":
    # Show configuration
    show_config()
    print()
    
    # Check command line arguments
    if len(sys.argv) > 1:
        # Use email from command line
        recipient = sys.argv[1]
        send_email(recipient)
    else:
        # Use email from environment variable
        send_email()
