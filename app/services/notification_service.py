"""
StockQueen V1 - Notification Service
OpenClaw integration and Twilio SMS notifications
"""

import httpx
import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.config import settings
from app.models import Signal

logger = logging.getLogger(__name__)


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
    """Main notification service"""
    
    def __init__(self):
        self.twilio = TwilioClient()
        self.feishu = FeishuClient()
        # self.openclaw = OpenClawClient()  # Temporarily disabled
    
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
        
        return await self.feishu.send_feishu_message(
            title="StockQueen - Daily Signal Summary",
            content=content
        )
    
    async def send_trade_confirmation(self, signal: Signal, order_id: str) -> bool:
        """Send trade execution confirmation"""
        content = f"✅ Trade Executed\n\n"
        content += f"Ticker: {signal.ticker}\n"
        content += f"Direction: {signal.direction.upper()}\n"
        content += f"Entry: ${signal.entry_price}\n"
        content += f"Order ID: {order_id}\n"
        content += f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        
        return await self.feishu.send_feishu_message(
            title=f"StockQueen - Trade Executed: {signal.ticker}",
            content=content
        )
    
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

        return await self.feishu.send_feishu_message(
            title="StockQueen - 地缘危机信号报告",
            content=content
        )


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
    """Send weekly rotation summary via Feishu."""
    service = NotificationService()

    regime = result.get("regime", "unknown")
    selected = result.get("selected", [])
    added = result.get("added", [])
    removed = result.get("removed", [])

    content = f"Regime: {'BULL' if regime == 'bull' else 'BEAR'}\n"
    content += f"Top {len(selected)}: {', '.join(selected)}\n"

    if added:
        content += f"NEW: {', '.join(added)}\n"
    if removed:
        content += f"OUT: {', '.join(removed)}\n"

    content += "\n"
    scores = result.get("scores_top10", [])
    for s in scores[:5]:
        ticker = s.get("ticker", "")
        score = s.get("score", 0)
        r1w = s.get("return_1w", 0)
        r1m = s.get("return_1m", 0)
        ma = "Y" if s.get("above_ma20") else "N"
        content += f"  {ticker:6s} score={score:+.2f} 1w={r1w:+.1%} 1m={r1m:+.1%} MA20={ma}\n"

    return await service.feishu.send_feishu_message(
        title="StockQueen - Weekly Rotation Report",
        content=content
    )


async def notify_rotation_entry(signal) -> bool:
    """Send daily entry signal notification with RAG context."""
    service = NotificationService()

    content = f"Ticker: {signal.ticker}\n"
    content += f"Entry Price: ${signal.entry_price:.2f}\n"
    content += f"Stop Loss: ${signal.stop_loss:.2f}\n"
    content += f"Take Profit: ${signal.take_profit:.2f}\n"
    content += f"Conditions: {', '.join(signal.trigger_conditions)}\n"
    content += "Action: BUY at next open\n"

    # Append RAG context if available
    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()
        ctx = await ks.get_context_for_signal(signal.ticker)
        if ctx:
            content += f"\n--- RAG Context ---\n{ctx[:500]}\n"
    except Exception:
        pass

    return await service.feishu.send_feishu_message(
        title=f"StockQueen - Entry Signal: {signal.ticker}",
        content=content
    )


async def notify_rotation_exit(signal) -> bool:
    """Send daily exit signal notification."""
    service = NotificationService()

    content = f"Ticker: {signal.ticker}\n"
    content += f"Current: ${signal.current_price:.2f}\n"
    if signal.entry_price:
        pnl = (signal.current_price / signal.entry_price - 1)
        content += f"Entry: ${signal.entry_price:.2f} (P&L: {pnl:+.1%})\n"
    content += f"Reason: {signal.exit_reason}\n"
    content += f"Conditions: {', '.join(signal.trigger_conditions)}\n"
    content += "Action: SELL at next open"

    return await service.feishu.send_feishu_message(
        title=f"StockQueen - Exit Signal: {signal.ticker}",
        content=content
    )
