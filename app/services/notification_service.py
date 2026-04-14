"""
StockQueen - Notification Service
Email (Gmail SMTP) primary notifications. Feishu disabled.
"""

import httpx
import logging
import json
import smtplib
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.config import settings
from app.models import Signal
from app.database import get_db

logger = logging.getLogger(__name__)


# ============================================================
# EMAIL CLIENT (Gmail SMTP — primary notification channel)
# ============================================================

class EmailClient:
    """Gmail SMTP email notification client."""

    def __init__(self):
        self.smtp_host = settings.email_smtp_host
        self.smtp_port = settings.email_smtp_port
        self.smtp_user = settings.email_smtp_user
        self.smtp_password = settings.email_smtp_password
        self.email_to = settings.email_to

    def _is_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_to)

    async def send_email(self, subject: str, body_html: str, body_text: str = "") -> bool:
        """Send email via Gmail SMTP (runs in thread to avoid blocking event loop)."""
        if not self._is_configured():
            logger.warning("[EMAIL] Not configured — EMAIL_SMTP_USER / EMAIL_SMTP_PASSWORD / EMAIL_TO missing")
            return False
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._send_sync, subject, body_html, body_text)
        except Exception as e:
            logger.error(f"[EMAIL] Failed to send '{subject}': {e}")
            return False

    def _send_sync(self, subject: str, body_html: str, body_text: str) -> bool:
        """Synchronous SMTP send (called via executor)."""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_user
            msg["To"] = self.email_to

            if body_text:
                msg.attach(MIMEText(body_text, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, self.email_to, msg.as_string())

            logger.info(f"[EMAIL] Sent: {subject}")
            return True
        except Exception as e:
            logger.error(f"[EMAIL] SMTP error: {e}")
            return False


def _html_wrap(title: str, body: str, color: str = "#00d4aa") -> str:
    """Wrap content in a clean HTML email template — light background + dark text for readability."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background:#f5f5f5; color:#2c3e50; margin:0; padding:0; }}
  .container {{ max-width:620px; margin:20px auto; background:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.1); }}
  .header {{ background:{color}; padding:20px 28px; }}
  .header h1 {{ margin:0; font-size:18px; color:#fff; font-weight:700; letter-spacing:0.5px; }}
  .header .subtitle {{ color:rgba(255,255,255,0.8); font-size:12px; margin-top:4px; }}
  .body {{ padding:24px 28px; color:#2c3e50; }}
  table {{ width:100%; border-collapse:collapse; margin:16px 0; background:#fafafa; border-radius:8px; overflow:hidden; }}
  th {{ text-align:left; background:#f0f0f0; color:#555; font-size:11px; text-transform:uppercase; padding:8px 12px; border-bottom:1px solid #e0e0e0; font-weight:600; }}
  td {{ padding:10px 12px; border-bottom:1px solid #e8e8e8; font-size:14px; color:#2c3e50; }}
  tr:last-child td {{ border-bottom:none; }}
  .ticker {{ font-size:24px; font-weight:700; color:{color}; letter-spacing:1px; }}
  .price {{ color:{color}; font-weight:700; font-size:16px; }}
  .sl {{ color:#c0392b; font-weight:700; }}
  .tp {{ color:#27ae60; font-weight:700; }}
  .quantity {{ color:#3498db; font-weight:700; font-size:15px; }}
  .section-title {{ font-size:13px; font-weight:700; color:#34495e; margin-top:20px; margin-bottom:8px; border-bottom:2px solid {color}; padding-bottom:6px; }}
  .badge {{ display:inline-block; padding:4px 12px; border-radius:20px; font-size:12px; font-weight:600; margin-bottom:12px; }}
  .badge-entry {{ background:#d5f4e6; color:#27ae60; border:1px solid #27ae60; }}
  .badge-exit {{ background:#fadbd8; color:#c0392b; border:1px solid #c0392b; }}
  .badge-rotation {{ background:#fef5e7; color:#d68910; border:1px solid #d68910; }}
  .fundamentals {{ background:#ecf0f1; padding:12px; border-radius:6px; margin:12px 0; border-left:4px solid {color}; }}
  .fundamentals p {{ margin:6px 0; font-size:13px; }}
  .footer {{ padding:14px 28px; border-top:1px solid #e0e0e0; font-size:11px; color:#7f8c8d; background:#fafafa; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>StockQueen &mdash; {title}</h1>
    <div class="subtitle">{datetime.now().strftime('%Y-%m-%d %H:%M NZT')}</div>
  </div>
  <div class="body">{body}</div>
  <div class="footer">StockQueen 破浪系统 · 模拟盘交易信号 · 自动生成，请勿回复</div>
</div>
</body>
</html>"""


class TwilioClient:
    """Twilio SMS and Voice client for emergency notifications"""
    
    def __init__(self):
        self.account_sid = settings.twilio_account_sid
        self.auth_token = settings.twilio_auth_token
        self.from_number = settings.twilio_phone_from
        self.to_number = settings.twilio_phone_to
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"
    
    async def send_sms(self, message: str) -> bool:
        """Send SMS via Twilio"""
        try:
            logger.info(f"Sending SMS: {message[:50]}...")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/Messages.json",
                    auth=(self.account_sid, self.auth_token),
                    data={
                        "From": self.from_number,
                        "To": self.to_number,
                        "Body": message
                    }
                )
                response.raise_for_status()
                
                logger.info("SMS sent successfully")
                return True
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Twilio HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            return False
    
    async def make_call(self, message: str) -> bool:
        """Make voice call via Twilio with TTS message"""
        try:
            logger.info(f"Making voice call with message: {message[:50]}...")
            
            # Create TwiML for text-to-speech
            twiml = f'''<Response>
                <Say language="en-US" voice="alice">
                    StockQueen Alert! {message}
                    This is an automated trading signal notification.
                </Say>
                <Pause length="2"/>
                <Say language="en-US" voice="alice">
                    Repeat. {message}
                </Say>
            </Response>'''
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/Calls.json",
                    auth=(self.account_sid, self.auth_token),
                    data={
                        "From": self.from_number,
                        "To": self.to_number,
                        "Twiml": twiml
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                
                logger.info("Voice call initiated successfully")
                return True
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Twilio voice call HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Error making voice call: {e}")
            return False
    
    async def send_high_signal_alert(self, ticker: str, rating: str, entry_price: float, day_change: float) -> bool:
        """Send both SMS and voice call for HIGH rating signals"""
        message = f"StockQueen HIGH Signal: {ticker} at ${entry_price:.2f}, up {day_change:.1f}% today. Check Feishu for details."
        
        # Send SMS first
        sms_sent = await self.send_sms(message)
        
        # Then make voice call
        call_made = await self.make_call(f"{ticker} trading signal. Entry price {entry_price:.2f} dollars. Up {day_change:.1f} percent today.")
        
        return sms_sent or call_made


class FeishuClient:
    """Feishu client for notifications (supports both webhook and API)"""
    
    def __init__(self):
        self.webhook_url = settings.feishu_webhook_url
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.receive_id = settings.feishu_receive_id
        self.access_token = None
        self.token_expires_at = None
    
    async def _get_access_token(self) -> str:
        """Get Feishu access token"""
        if self.access_token and self.token_expires_at and datetime.utcnow() < self.token_expires_at:
            return self.access_token
        
        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET must be configured")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self.app_id,
                        "app_secret": self.app_secret
                    },
                    timeout=10
                )
                response.raise_for_status()
                
                data = response.json()
                self.access_token = data.get("tenant_access_token")
                expires_in = data.get("expire", 7200)
                self.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)
                
                logger.info("Feishu access token obtained successfully")
                return self.access_token
                
        except Exception as e:
            logger.error(f"Failed to get Feishu access token: {e}")
            raise
    
    async def send_feishu_message(self, title: str, content: str):
        """Send notification via Feishu"""
        # Priority 1: Use API mode (if receive_id is configured)
        if self.receive_id:
            return await self._send_via_api(title, content)
        
        # Priority 2: Use webhook mode (if webhook_url is configured)
        if self.webhook_url:
            return await self._send_via_webhook(title, content)
        
        # No configuration available
        logger.warning("Neither FEISHU_RECEIVE_ID nor FEISHU_WEBHOOK_URL is configured")
        return False
    
    async def _send_via_api(self, title: str, content: str) -> bool:
        """Send message via Feishu API"""
        try:
            token = await self._get_access_token()
            
            # Use proper JSON serialization
            message_text = f"{title}\n\n{content}"
            content_json = json.dumps({"text": message_text}, ensure_ascii=False)
            
            payload = {
                "receive_id": self.receive_id,
                "msg_type": "text",
                "content": content_json
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                    headers={
                        "Authorization": f"Bearer {token}"
                    },
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
                
                logger.info(f"Feishu API notification sent: {title}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to send Feishu API notification: {e}")
            return False
    
    async def _send_via_webhook(self, title: str, content: str) -> bool:
        """Send message via Feishu webhook"""
        try:
            payload = {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "title": title,
                            "content": [[{"tag": "text", "text": content}]]
                        }
                    }
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(self.webhook_url, json=payload, timeout=10)
                response.raise_for_status()
            
            logger.info(f"Feishu webhook notification sent: {title}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Feishu webhook notification: {e}")
            return False


class OpenClawClient:
    """OpenClaw webhook client for notifications"""
    
    def __init__(self):
        self.webhook_url = settings.openclaw_webhook_url
    
    async def send_notification(self, message_type: str, data: dict) -> bool:
        """Send notification via OpenClaw"""
        if not self.webhook_url:
            logger.warning("OPENCLAW_WEBHOOK_URL not configured")
            return False
        
        payload = {
            "type": message_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
                
                logger.info(f"OpenClaw notification sent: {message_type}")
                return True
                
        except httpx.HTTPStatusError as e:
            logger.error(f"OpenClaw HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Error sending OpenClaw notification: {e}")
            return False


class NotificationService:
    """Main notification service — Email primary, Feishu disabled."""

    def __init__(self):
        self.twilio = TwilioClient()
        self.feishu = FeishuClient()   # kept for legacy code paths, but not used for trading signals
        self.email = EmailClient()
    
    async def send_signal_summary(self, signals: List[Signal]) -> bool:
        """Send daily signal summary via Feishu"""
        if not signals:
            content = "📊 StockQueen Daily Report\n\nNo signals generated today."
        else:
            content = "📊 StockQueen Daily Report\n\n"
            content += f"Signals to Review: {len(signals)}\n\n"
            
            for i, signal in enumerate(signals, 1):
                direction_emoji = "📈" if signal.direction == "long" else "📉"
                
                rating = getattr(signal, 'rating', 'medium')
                if rating == 'high':
                    rating_emoji = "🟢"
                    rating_text = "HIGH - 趋势配合，建议关注"
                elif rating == 'medium':
                    rating_emoji = "🟡"
                    rating_text = "MEDIUM - 逆势信号，谨慎对待"
                else:
                    rating_emoji = "🔴"
                    rating_text = "LOW - 风险较高"
                
                content += f"{i}. {rating_emoji} {direction_emoji} {signal.ticker}\n"
                content += f"   Rating: {rating_text}\n"
                content += f"   Direction: {signal.direction.upper()}\n"
                content += f"   Entry: ${signal.entry_price}\n"
                content += f"   Stop: ${signal.stop_loss}\n"
                content += f"   Target: ${signal.target_price}\n"
                
                if hasattr(signal, 'ma20') and signal.ma20:
                    trend = "✅" if signal.price_above_ma20 else "❌"
                    content += f"   MA20: ${signal.ma20:.2f} {trend}\n"
                
                day_change = getattr(signal, 'day_change_pct', None)
                vol_mult = getattr(signal, 'volume_multiplier', None)
                if day_change is not None:
                    content += f"   当日涨幅: {day_change:.1f}%\n"
                if vol_mult is not None:
                    content += f"   成交量倍数: {vol_mult:.1f}x\n"
                
                # Premarket data display
                has_premarket = getattr(signal, 'has_premarket', None)
                premarket_change = getattr(signal, 'premarket_change_pct', None)
                premarket_price = getattr(signal, 'premarket_price', None)
                
                if has_premarket and premarket_change is not None:
                    content += f"\n   📊 盘前数据:\n"
                    content += f"   盘前价格: ${premarket_price:.2f}\n"
                    content += f"   盘前涨幅: {premarket_change:.1f}%\n"
                    
                    if premarket_change > 50:
                        content += f"   🔴 警告：盘前已暴涨 {premarket_change:.1f}%，主要行情可能已结束，追高风险极高！\n"
                    elif premarket_change > 30:
                        content += f"   🟠 注意：盘前已涨 {premarket_change:.1f}%，谨慎追入\n"
                    elif premarket_change > 10:
                        content += f"   🟡 盘前温和上涨 {premarket_change:.1f}%，可观察开盘情况\n"
                    else:
                        content += f"   🟢 盘前涨幅 {premarket_change:.1f}%，仍有参与空间\n"
                elif has_premarket is False:
                    content += f"\n   📊 盘前数据: 暂无（市场已开盘或无盘前交易）\n"
                
                if day_change is not None and day_change >= 20:
                    content += f"\n   ⚠️ 注意：当日涨幅已达{day_change:.1f}%，追高风险大，建议等回调\n"
                
                # LABU/LABD联动提示
                if signal.direction == "long":
                    content += f"\n   💡 联动参考：可关注 LABU（3倍生物科技做多ETF）\n"
                elif signal.direction == "short":
                    content += f"\n   💡 联动参考：可关注 LABD（3倍生物科技做空ETF）\n"
                
                content += "\n"
        
        # Legacy path — send plain-text email fallback
        subject = f"[StockQueen] Daily Signal Summary ({len(signals)} signals)"
        html = _html_wrap("Daily Signal Summary", f"<pre style='color:#ccc;font-size:13px'>{content}</pre>")
        return await self.email.send_email(subject, html)
    
    async def send_trade_confirmation(self, signal: Signal, order_id: str) -> bool:
        """Send trade execution confirmation"""
        content = f"✅ Trade Executed\n\n"
        content += f"Ticker: {signal.ticker}\n"
        content += f"Direction: {signal.direction.upper()}\n"
        content += f"Entry: ${signal.entry_price}\n"
        content += f"Order ID: {order_id}\n"
        content += f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        
        subject = f"[StockQueen] 成交确认 — {signal.ticker} | Order #{order_id}"
        html = _html_wrap(f"Trade Executed: {signal.ticker}", f"<pre style='color:#ccc;font-size:13px'>{content}</pre>")
        return await self.email.send_email(subject, html)
    
    async def send_risk_alert(self, alert_type: str, details: str) -> bool:
        """Send risk alert via Twilio SMS"""
        message = f"🚨 StockQueen Risk Alert\n\n"
        message += f"Type: {alert_type}\n"
        message += f"Details: {details}\n"
        message += f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        message += "System may be paused. Please check."
        
        return await self.twilio.send_sms(message)
    
    async def send_stop_loss_triggered(self, ticker: str, pnl: float) -> bool:
        """Send stop loss triggered notification"""
        message = f"⚠️ StockQueen Stop Loss\n\n"
        message += f"Ticker: {ticker}\n"
        message += f"P&L: ${pnl:.2f}\n"
        message += f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        message += "Position closed at stop loss."
        
        return await self.twilio.send_sms(message)
    
    async def send_volatility_alert(self, ticker: str, change_pct: float) -> bool:
        """Send high volatility alert"""
        message = f"📢 StockQueen Volatility Alert\n\n"
        message += f"Ticker: {ticker}\n"
        message += f"Daily Change: {change_pct:+.1%}\n"
        message += f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        message += "Unusual price movement detected."
        
        return await self.twilio.send_sms(message)
    
    async def send_api_error_alert(self, service: str, error: str) -> bool:
        """Send API error alert"""
        message = f"❌ StockQueen API Error\n\n"
        message += f"Service: {service}\n"
        message += f"Error: {error[:100]}\n"
        message += f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        message += "Please check system status."
        
        return await self.twilio.send_sms(message)
    
    async def send_high_signal_alert(self, signal: Signal) -> bool:
        """
        Send HIGH rating signal alert via SMS and voice call
        Called when a HIGH rating signal is generated
        """
        rating = getattr(signal, 'rating', 'medium')
        
        if rating != 'high':
            logger.info(f"Signal {signal.ticker} rating is {rating}, not sending Twilio alert")
            return False
        
        day_change = getattr(signal, 'day_change_pct', 0) or 0
        
        logger.info(f"Sending HIGH signal alert for {signal.ticker}")
        
        return await self.twilio.send_high_signal_alert(
            ticker=signal.ticker,
            rating=rating,
            entry_price=signal.entry_price or 0,
            day_change=day_change
        )


    async def send_geopolitical_signal_summary(self, signals: List[Signal]) -> bool:
        """Send geopolitical crisis signal summary via Feishu (enhanced with ATR/Alpha/Crisis)"""
        if not signals:
            content = "🌍 StockQueen Geopolitical Crisis Report\n\nNo signals generated."
        else:
            from app.config.geopolitical_watchlist import GEOPOLITICAL_SECTOR_MAP
            from app.config import RiskConfig

            SECTOR_NAMES = {
                "OIL_GAS": "🛢️ 油气开采",
                "OIL_TANKER": "🚢 油轮航运",
                "GOLD": "🥇 黄金贵金属",
                "DEFENSE": "🎖️ 军工国防",
                "COAL_ALT_ENERGY": "⚡ 煤炭/替代能源",
                "REFINERY": "🏭 炼油",
                "AIRLINE_SHORT": "✈️ 航空(做空)",
                "CRUISE_SHORT": "🚢 邮轮(做空)",
            }

            content = "🌍 StockQueen - 霍尔木兹海峡危机扫描报告\n\n"
            content += f"信号数量: {len(signals)}\n"

            # === Global summary: SPY + Crisis Score ===
            # Extract from the first signal (all signals share the same global values)
            sample = signals[0]
            crisis_score = getattr(sample, 'crisis_score', None)
            alpha_sample = getattr(sample, 'alpha_vs_spy', None)
            day_change_sample = getattr(sample, 'day_change_pct', None)

            # Infer SPY change: spy_change = day_change - alpha
            spy_change_inferred = None
            if alpha_sample is not None and day_change_sample is not None:
                spy_change_inferred = round(day_change_sample - alpha_sample, 2)

            content += "\n📊 市场概况:\n"
            if spy_change_inferred is not None:
                content += f"  SPY日涨跌: {spy_change_inferred:+.2f}%\n"
            if crisis_score is not None:
                crisis_bar = "🔴" * crisis_score + "⚪" * (4 - crisis_score)
                content += f"  危机强度: {crisis_bar} {crisis_score}/4\n"
            else:
                content += f"  危机强度: N/A\n"
            content += f"  事件日期: {RiskConfig.GEO_EVENT_DATE}\n"

            content += "\n" + "=" * 40 + "\n\n"

            # Group signals by sector
            sector_signals: Dict[str, list] = {}
            for signal in signals:
                sector = GEOPOLITICAL_SECTOR_MAP.get(signal.ticker, "UNKNOWN")
                if sector not in sector_signals:
                    sector_signals[sector] = []
                sector_signals[sector].append(signal)

            for sector, sigs in sector_signals.items():
                sector_name = SECTOR_NAMES.get(sector, sector)
                content += f"--- {sector_name} ---\n"

                for signal in sigs:
                    direction_emoji = "📈" if signal.direction == "long" else "📉"

                    rating = getattr(signal, 'rating', 'medium')
                    if rating == 'high':
                        rating_emoji = "🟢"
                    elif rating == 'medium':
                        rating_emoji = "🟡"
                    else:
                        rating_emoji = "🔴"

                    confidence = getattr(signal, 'confidence_score', None)
                    conf_str = f" ({confidence:.0f}分)" if confidence is not None else ""

                    content += f"  {rating_emoji} {direction_emoji} {signal.ticker}{conf_str}\n"
                    content += f"    Entry: ${signal.entry_price}  Stop: ${signal.stop_loss}  Target: ${signal.target_price}\n"

                    day_change = getattr(signal, 'day_change_pct', None)
                    vol_mult = getattr(signal, 'volume_multiplier', None)
                    if day_change is not None:
                        content += f"    涨幅: {day_change:+.1f}%"
                    if vol_mult is not None:
                        content += f"  量比: {vol_mult:.1f}x"
                    content += "\n"

                    # Enhanced fields: ATR, Alpha, Crisis
                    atr14 = getattr(signal, 'atr14', None)
                    alpha_vs_spy = getattr(signal, 'alpha_vs_spy', None)
                    enhanced_parts = []
                    if atr14 is not None:
                        enhanced_parts.append(f"ATR(14): ${atr14:.2f}")
                    if alpha_vs_spy is not None:
                        enhanced_parts.append(f"Alpha vs SPY: {alpha_vs_spy:+.2f}%")
                    if enhanced_parts:
                        content += f"    {' | '.join(enhanced_parts)}\n"

                content += "\n"

            # Add crisis context
            content += "=" * 40 + "\n"
            content += "💡 危机背景: 霍尔木兹海峡封锁\n"
            content += "做多逻辑: 油气/航运/黄金/军工受益于供应中断和避险情绪\n"
            content += "做空逻辑: 航空/邮轮受累于燃油成本飙升\n"
            content += "📐 增强策略: ATR自适应阈值 + SPY相对强弱 + 跨资产确认 + 事件衰减\n"
            content += "⚠️ 风险提示: 地缘冲突不确定性极大，注意仓位控制\n"

        subject = f"[StockQueen] 地缘危机信号报告 ({len(signals)} signals)"
        html = _html_wrap("地缘危机信号报告", f"<pre style='color:#ccc;font-size:13px'>{content}</pre>")
        return await self.email.send_email(subject, html)


# Convenience functions
async def notify_signals_ready(signals: List[Signal]) -> bool:
    """Notify that signals are ready for review"""
    service = NotificationService()
    return await service.send_signal_summary(signals)


async def notify_geopolitical_signals(signals: List[Signal]) -> bool:
    """Notify geopolitical crisis signals"""
    service = NotificationService()
    return await service.send_geopolitical_signal_summary(signals)


async def notify_risk_alert(alert_type: str, details: str) -> bool:
    """Send risk alert"""
    service = NotificationService()
    return await service.send_risk_alert(alert_type, details)


# ==================== ROTATION NOTIFICATIONS ====================

async def notify_rotation_summary(result: dict) -> bool:
    """Send weekly rotation summary via Email."""
    service = NotificationService()

    regime = result.get("regime", "unknown")
    selected = result.get("selected", [])
    added = result.get("added", [])
    removed = result.get("removed", [])
    regime_label = {"bull": "Bull 🟢", "strong_bull": "Strong Bull 🟢🟢",
                    "choppy": "Choppy 🟡", "bear": "Bear 🔴"}.get(regime, regime.upper())

    # Build score rows
    scores = result.get("scores_top10", [])
    score_rows = ""
    for i, s in enumerate(scores[:8], 1):
        ticker = s.get("ticker", "")
        score = s.get("score", 0)
        r1w = s.get("return_1w", 0)
        r1m = s.get("return_1m", 0)
        is_selected = ticker in selected
        row_style = "background:#00d4aa11;" if is_selected else ""
        badge = '<span class="badge badge-entry">SELECTED</span>' if is_selected else ""
        score_rows += f"""<tr style="{row_style}">
          <td><b>{ticker}</b> {badge}</td>
          <td class="price">{score:+.2f}</td>
          <td>{r1w:+.1%}</td>
          <td>{r1m:+.1%}</td>
        </tr>"""

    added_html = "".join(f'<span style="color:#00d4aa;font-weight:700;margin-right:8px">+{t}</span>' for t in added)
    removed_html = "".join(f'<span style="color:#ff4d4d;font-weight:700;margin-right:8px">-{t}</span>' for t in removed)

    body = f"""
    <p><span class="badge badge-rotation">宝典 V5 · 周轮动</span></p>
    <table>
      <tr><th>Regime</th><td>{regime_label}</td></tr>
      <tr><th>持仓 TOP {len(selected)}</th><td><b>{', '.join(selected)}</b></td></tr>
      {"<tr><th>新增</th><td>" + added_html + "</td></tr>" if added else ""}
      {"<tr><th>移除</th><td>" + removed_html + "</td></tr>" if removed else ""}
    </table>
    <table>
      <tr><th>Ticker</th><th>Score</th><th>1W</th><th>1M</th></tr>
      {score_rows}
    </table>
    <p style="color:#888;font-size:12px">周轮动已完成，待进场标的已写入 pending_entry 队列。</p>
    """

    subject = f"[StockQueen] 宝典V5 周轮动报告 — {', '.join(selected)} | {regime_label}"
    html = _html_wrap("Weekly Rotation Report", body, color="#f5a623")
    return await service.email.send_email(subject, html)


async def notify_rotation_entry(signal, quantity: int = 0, strategy: str = "宝典V5") -> bool:
    """Send entry signal notification via Email with full trade details + selection criteria + fundamentals."""
    service = NotificationService()
    db = get_db()

    entry = signal.entry_price or signal.current_price
    sl = signal.stop_loss or 0.0
    tp = signal.take_profit or 0.0
    risk_amt = entry - sl if sl > 0 else 0
    reward_amt = tp - entry if tp > 0 else 0
    rr = f"{reward_amt / risk_amt:.1f}R" if risk_amt > 0 else "—"
    qty_display = f"{quantity:,} 股" if quantity > 0 else "市价单（系统分配）"
    position_value = f"${entry * quantity:,.0f}" if quantity > 0 else "—"

    # ── 从最新快照获取该股的选股理由 + 基本面数据 ──
    selection_reason = ""
    fundamentals_html = ""
    try:
        snap = (db.table("rotation_snapshots")
                .select("id, scores, regime")
                .order("snapshot_date", desc=True)
                .limit(1)
                .execute())
        if snap.data:
            snapshot = snap.data[0]
            regime = snapshot.get("regime", "unknown")
            scores = snapshot.get("scores") or []

            # 在 scores 里找该股的信息
            for s in scores:
                if s.get("ticker") == signal.ticker:
                    name = s.get("name", "")
                    sector = s.get("sector", "")
                    asset_type = s.get("asset_type", "")
                    return_1w = s.get("return_1w", 0)
                    return_1m = s.get("return_1m", 0)
                    volatility = s.get("volatility", 0)
                    above_ma20 = s.get("above_ma20", False)
                    score = s.get("score", 0)

                    # 根据 asset_type 确定资产类型标签
                    if asset_type == "etf_offensive":
                        asset_label = "进攻型ETF"
                    elif asset_type == "etf_defensive":
                        asset_label = "防守型ETF"
                    else:
                        asset_label = "个股"

                    selection_reason = f"{asset_label} · {sector} · 评分: {score:+.2f}"

                    # 构建基本面表 - 分别计算颜色和值
                    return_1w_color = "#00d4aa" if return_1w > 0 else "#ff4d4d"
                    return_1m_color = "#00d4aa" if return_1m > 0 else "#ff4d4d"
                    ma20_status = "[UP] 上方（牛市）" if above_ma20 else "[DOWN] 下方（谨慎）"

                    fundamentals_html = f"""
    <div class="fundamentals">
      <div class="section-title">选股理由与基本面</div>
      <p style="margin:8px 0;font-size:13px"><b>资产类型:</b> <span style="color:#3498db">{asset_label}</span></p>
      <p style="margin:8px 0;font-size:13px"><b>行业:</b> {sector if sector else '—'}</p>
      <p style="margin:8px 0;font-size:13px"><b>动量评分:</b> <span style="color:#00d4aa;font-weight:700">{score:+.2f}</span></p>
      <p style="margin:8px 0;font-size:13px"><b>1周回报:</b> <span style="color:{return_1w_color};font-weight:700">{return_1w:+.1%}</span></p>
      <p style="margin:8px 0;font-size:13px"><b>1月回报:</b> <span style="color:{return_1m_color};font-weight:700">{return_1m:+.1%}</span></p>
      <p style="margin:8px 0;font-size:13px"><b>波动率:</b> {volatility:.1%}</p>
      <p style="margin:8px 0;font-size:13px"><b>MA20 趋势:</b> {ma20_status}</p>
    </div>
                    """
                    break
    except Exception as e:
        logger.warning(f"Failed to fetch selection criteria for {signal.ticker}: {e}")

    # 构建进场条件说明
    conditions_display = "、".join(signal.trigger_conditions) if signal.trigger_conditions else "标准进场条件"

    body = f"""
    <p><span class="badge badge-entry">ENTRY SIGNAL · 进场信号</span></p>
    <p class="ticker">{signal.ticker}</p>
    {fundamentals_html}
    <table>
      <tr><th>策略</th><td>{strategy}</td></tr>
      <tr><th>进场价</th><td class="price">${entry:.2f}</td></tr>
      <tr><th>止损价</th><td class="sl">${sl:.2f} &nbsp;(-{risk_amt:.2f})</td></tr>
      <tr><th>止盈价</th><td class="tp">${tp:.2f} &nbsp;(+{reward_amt:.2f})</td></tr>
      <tr><th>盈亏比</th><td>{rr}</td></tr>
      <tr><th>购买数量</th><td><span class="quantity">{qty_display}</span></td></tr>
      <tr><th>仓位市值</th><td><span class="quantity">{position_value}</span></td></tr>
      <tr><th>进场条件</th><td style="font-size:12px;color:#888">{conditions_display}</td></tr>
      <tr><th>操作</th><td><b>次日开盘 MKT 买入</b></td></tr>
    </table>
    """

    subject = f"[StockQueen] 进场信号 — {signal.ticker} @ ${entry:.2f} | {strategy}"
    html = _html_wrap(f"Entry Signal: {signal.ticker}", body, color="#00d4aa")
    return await service.email.send_email(subject, html)


async def notify_rotation_entry_batch(signals: list, strategy: str = "宝典V5") -> bool:
    """Send batch entry notifications for multiple signals in a single email."""
    if not signals:
        return False

    service = NotificationService()
    db = get_db()

    # Build signal cards
    signal_cards = ""
    signal_count = len(signals)
    tickers = ", ".join([s.ticker for s in signals])

    for idx, signal in enumerate(signals, 1):
        entry = signal.entry_price or signal.current_price
        sl = signal.stop_loss or 0.0
        tp = signal.take_profit or 0.0
        risk_amt = entry - sl if sl > 0 else 0
        reward_amt = tp - entry if tp > 0 else 0
        rr = f"{reward_amt / risk_amt:.1f}R" if risk_amt > 0 else "—"

        # Fetch fundamentals
        fundamentals_html = ""
        try:
            snap = (db.table("rotation_snapshots")
                    .select("scores")
                    .order("snapshot_date", desc=True)
                    .limit(1)
                    .execute())
            if snap.data:
                scores = snap.data[0].get("scores") or []
                for s in scores:
                    if s.get("ticker") == signal.ticker:
                        sector = s.get("sector", "")
                        asset_type = s.get("asset_type", "")
                        return_1w = s.get("return_1w", 0)
                        return_1m = s.get("return_1m", 0)
                        volatility = s.get("volatility", 0)
                        above_ma20 = s.get("above_ma20", False)
                        score = s.get("score", 0)

                        if asset_type == "etf_offensive":
                            asset_label = "进攻型ETF"
                        elif asset_type == "etf_defensive":
                            asset_label = "防守型ETF"
                        else:
                            asset_label = "个股"

                        return_1w_color = "#00d4aa" if return_1w > 0 else "#ff4d4d"
                        return_1m_color = "#00d4aa" if return_1m > 0 else "#ff4d4d"
                        ma20_status = "[UP]" if above_ma20 else "[DOWN]"

                        fundamentals_html = f"""<div style="background:#ecf0f1;padding:10px;border-radius:6px;border-left:4px solid #00d4aa;margin:8px 0;font-size:12px">
  <b>{asset_label}</b> | {sector} | 评分: <span style="color:#00d4aa;font-weight:700">{score:+.2f}</span><br/>
  1W: <span style="color:{return_1w_color}">{return_1w:+.1%}</span> | 1M: <span style="color:{return_1m_color}">{return_1m:+.1%}</span> | 波动: {volatility:.1%} | MA20: {ma20_status}
</div>"""
                        break
        except Exception as e:
            logger.warning(f"Failed to fetch fundamentals for {signal.ticker}: {e}")

        conditions_display = "、".join(signal.trigger_conditions) if signal.trigger_conditions else "标准进场条件"

        signal_cards += f"""
    <div style="background:#fafafa;padding:16px;border-radius:8px;margin-bottom:12px;border-left:4px solid #00d4aa">
      <p style="margin:0 0 8px 0;font-size:16px;font-weight:700;color:#00d4aa">{idx}. {signal.ticker}</p>
      {fundamentals_html}
      <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:8px">
        <tr><td style="padding:6px 0"><b>进场:</b> <span style="color:#00d4aa;font-weight:700">${entry:.2f}</span></td><td style="padding:6px 0"><b>止损:</b> <span style="color:#ff4d4d">${sl:.2f}</span></td></tr>
        <tr><td style="padding:6px 0"><b>止盈:</b> <span style="color:#27ae60">${tp:.2f}</span></td><td style="padding:6px 0"><b>盈亏比:</b> {rr}</td></tr>
        <tr><td colspan="2" style="padding:6px 0;font-size:12px;color:#888">条件: {conditions_display}</td></tr>
      </table>
    </div>
        """

    body = f"""
    <p><span class="badge badge-entry">ENTRY SIGNALS · 批量进场</span></p>
    <p style="font-size:14px;margin:12px 0"><b>共 {signal_count} 个进场信号</b>：{tickers}</p>
    {signal_cards}
    <p style="color:#888;font-size:12px;margin-top:16px">所有标的将在次日开盘 MKT 买入，按仓位配置自动分配资金。</p>
    """

    subject = f"[StockQueen] 批量进场信号 — {signal_count} 个标的 | {strategy}"
    html = _html_wrap(f"Batch Entry: {tickers}", body, color="#00d4aa")
    return await service.email.send_email(subject, html)


async def notify_rotation_exit(signal, strategy: str = "宝典V5") -> bool:
    """Send exit signal notification via Email."""
    service = NotificationService()

    current = signal.current_price
    entry = signal.entry_price or 0.0
    pnl_pct = (current / entry - 1) if entry > 0 else 0
    pnl_color = "#00d4aa" if pnl_pct >= 0 else "#ff4d4d"
    pnl_sign = "+" if pnl_pct >= 0 else ""
    exit_reason_map = {
        "stop_loss": "止损触发",
        "take_profit": "止盈触发",
        "rotation_exit": "轮动换仓",
        "entry_timeout": "进场超时",
        "replaced_by_fallback": "递补替换",
        "manual": "手动平仓",
    }
    reason_display = exit_reason_map.get(signal.exit_reason or "", signal.exit_reason or "未知")

    body = f"""
    <p><span class="badge badge-exit">EXIT SIGNAL · 出场信号</span></p>
    <p class="ticker">{signal.ticker}</p>
    <table>
      <tr><th>策略</th><td>{strategy}</td></tr>
      <tr><th>当前价</th><td class="price">${current:.2f}</td></tr>
      {"<tr><th>进场价</th><td>${:.2f}</td></tr>".format(entry) if entry > 0 else ""}
      {"<tr><th>盈亏</th><td style='color:{};font-weight:700'>{}{:.1%}</td></tr>".format(pnl_color, pnl_sign, pnl_pct) if entry > 0 else ""}
      <tr><th>出场原因</th><td><b>{reason_display}</b></td></tr>
      <tr><th>触发条件</th><td style="font-size:12px;color:#aaa">{', '.join(signal.trigger_conditions)}</td></tr>
      <tr><th>操作</th><td><b>次日开盘 MKT 卖出</b></td></tr>
    </table>
    """

    subject = f"[StockQueen] 出场信号 — {signal.ticker} {pnl_sign}{pnl_pct:.1%} | {reason_display}"
    html = _html_wrap(f"Exit Signal: {signal.ticker}", body, color="#ff4d4d")
    return await service.email.send_email(subject, html)


async def notify_midweek_replacement(replacements: list[dict]) -> bool:
    """Send email notification when mid-week replacement positions are queued."""
    if not replacements:
        return False
    service = NotificationService()

    rows = ""
    for r in replacements:
        rows += f"""<tr>
          <td><b>{r['ticker']}</b></td>
          <td class="price">${r['current_price']:.2f}</td>
          <td style="color:#888">${r['signal_price']:.2f}</td>
          <td>{r['drift_in_atr']:.2f} ATR</td>
          <td class="sl">${r['new_sl']:.2f}</td>
          <td class="tp">${r['new_tp']:.2f}</td>
        </tr>"""

    body = f"""
    <p><span class="badge badge-rotation">宝典V5 · 周中补仓</span></p>
    <p>共 <b>{len(replacements)}</b> 个替代仓位已进入 pending_entry 队列：</p>
    <table>
      <tr><th>Ticker</th><th>当前价</th><th>信号价</th><th>漂移</th><th>止损</th><th>止盈</th></tr>
      {rows}
    </table>
    <p style="color:#888;font-size:12px">以上标的将在次日 Entry Check 通过后自动入场。</p>
    """

    subject = f"[StockQueen] 宝典V5 周中补仓 — {len(replacements)} 个仓位补入"
    html = _html_wrap("Mid-week Replacement", body, color="#f5a623")
    return await service.email.send_email(subject, html)


# ==================== REGIME CHANGE ALERTS ====================

REGIME_LABELS = {
    "strong_bull": "Strong Bull",
    "bull": "Bull",
    "choppy": "Choppy",
    "bear": "Bear",
}

REGIME_EMOJI = {
    "strong_bull": "🟢🟢",
    "bull": "🟢",
    "choppy": "🟡",
    "bear": "🔴",
}


async def notify_regime_change(
    prev_regime: str,
    new_regime: str,
    score: int,
    signals: list[dict],
    spy_price: float,
) -> bool:
    """Send urgent Feishu alert when market regime changes."""
    service = NotificationService()

    prev_label = f"{REGIME_EMOJI.get(prev_regime, '')} {REGIME_LABELS.get(prev_regime, prev_regime)}"
    new_label = f"{REGIME_EMOJI.get(new_regime, '')} {REGIME_LABELS.get(new_regime, new_regime)}"

    # Determine severity
    regime_order = ["bear", "choppy", "bull", "strong_bull"]
    prev_idx = regime_order.index(prev_regime) if prev_regime in regime_order else 1
    new_idx = regime_order.index(new_regime) if new_regime in regime_order else 1
    direction = "UPGRADE" if new_idx > prev_idx else "DOWNGRADE"

    content = f"Regime Change: {prev_label}  →  {new_label}\n"
    content += f"Direction: {direction}\n"
    content += f"Score: {score} (range: -5 to +5)\n"
    content += f"SPY: ${spy_price:.2f}\n"
    content += "\n--- Signal Breakdown ---\n"
    for sig in signals:
        name = sig.get("name", "")
        value = sig.get("value", "")
        unit = sig.get("unit", "")
        pts = sig.get("contribution", 0)
        content += f"  {name}: {value}{unit} ({pts:+d} pts)\n"

    content += "\n--- Impact ---\n"
    if new_regime == "bear":
        content += "  Pool: DEFENSIVE + INVERSE ETFs only (7 tickers)\n"
        content += "  Cash: ~50% minimum\n"
    elif new_regime == "choppy":
        content += "  Pool: DEFENSIVE + OFFENSIVE ETFs + LARGECAP only\n"
        content += "  Mean Reversion: 50% allocation\n"
    elif new_regime == "bull":
        content += "  Pool: Full universe (~500 tickers)\n"
        content += "  Mean Reversion: 10% allocation\n"
    elif new_regime == "strong_bull":
        content += "  Pool: Full universe (~500 tickers)\n"
        content += "  V4 Rotation: 70% allocation\n"

    alert_color = "#ff4d4d" if direction == "DOWNGRADE" else "#00d4aa"

    sig_rows = "".join(
        f"<tr><td>{s.get('name','')}</td><td>{s.get('value','')}{s.get('unit','')}</td>"
        f"<td style='color:{'#00d4aa' if s.get('contribution',0)>0 else '#ff4d4d'}'>"
        f"{s.get('contribution',0):+d} pts</td></tr>"
        for s in signals
    )

    impact_map = {
        "bear": "仓位 50% 现金 · 切换防御池 + 反向ETF",
        "choppy": "仓位降低 · 防御+蓝筹+MR策略",
        "bull": "全仓 · 完整动态选股池",
        "strong_bull": "全仓 · 可增加杠杆",
    }

    body = f"""
    <p><span class="badge" style="background:{alert_color}22;color:{alert_color};border:1px solid {alert_color}44">
      REGIME {direction}
    </span></p>
    <table>
      <tr><th>前 Regime</th><td>{REGIME_LABELS.get(prev_regime, prev_regime)}</td></tr>
      <tr><th>新 Regime</th><td><b>{REGIME_LABELS.get(new_regime, new_regime)}</b></td></tr>
      <tr><th>评分</th><td>{score} / 5</td></tr>
      <tr><th>SPY 价格</th><td>${spy_price:.2f}</td></tr>
      <tr><th>影响</th><td>{impact_map.get(new_regime, '参数重新配置')}</td></tr>
    </table>
    <table>
      <tr><th>信号因子</th><th>值</th><th>贡献</th></tr>
      {sig_rows}
    </table>
    <p style="color:#888;font-size:12px">下次周轮动将使用新 Regime 参数。</p>
    """

    subject = f"[StockQueen] ⚠️ Regime {direction}: {REGIME_LABELS.get(prev_regime,prev_regime)} → {REGIME_LABELS.get(new_regime,new_regime)}"
    html = _html_wrap(f"Regime Change: {direction}", body, color=alert_color)
    return await service.email.send_email(subject, html)
