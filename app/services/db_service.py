"""
StockQueen V1 - Database Service
CRUD operations for all database tables
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from app.database import get_db
from app.models import (
    NewsEvent, NewsEventCreate,
    AIEvent, AIEventCreate,
    MarketSnapshot, MarketSnapshotCreate,
    Signal, SignalCreate,
    Order, OrderCreate,
    Trade,
    RiskState
)

logger = logging.getLogger(__name__)


class EventService:
    """Service for news events operations"""
    
    @staticmethod
    async def create_event(event: NewsEventCreate) -> Optional[NewsEvent]:
        """Create a new news event"""
        try:
            db = get_db()
            data = {
                "ticker": event.ticker,
                "title": event.title,
                "summary": event.summary,
                "url": event.url,
                "source": event.source,
                "published_at": event.published_at.isoformat(),
                "status": "pending"
            }
            
            result = db.table("events").insert(data).execute()
            
            if result.data:
                logger.info(f"Created event: {event.title[:50]}...")
                return NewsEvent(**result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Error creating event: {e}")
            return None
    
    @staticmethod
    async def get_event_by_url(url: str) -> Optional[NewsEvent]:
        """Get event by URL (for deduplication)"""
        try:
            db = get_db()
            result = db.table("events").select("*").eq("url", url).execute()
            
            if result.data:
                return NewsEvent(**result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Error getting event by URL: {e}")
            return None
    
    @staticmethod
    async def get_pending_events() -> List[NewsEvent]:
        """Get all pending events for processing"""
        try:
            db = get_db()
            result = db.table("events").select("*").eq("status", "pending").execute()
            
            return [NewsEvent(**row) for row in result.data] if result.data else []
            
        except Exception as e:
            logger.error(f"Error getting pending events: {e}")
            return []
    
    @staticmethod
    async def update_event_status(event_id: str, status: str) -> bool:
        """Update event status"""
        try:
            db = get_db()
            db.table("events").update({"status": status}).eq("id", event_id).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error updating event status: {e}")
            return False


class AIEventService:
    """Service for AI classified events operations"""
    
    @staticmethod
    async def create_ai_event(event: AIEventCreate) -> Optional[AIEvent]:
        """Create a new AI classified event"""
        try:
            db = get_db()
            data = {
                "event_id": event.event_id,
                "ticker": event.ticker,
                "is_valid_event": event.is_valid_event,
                "event_type": event.event_type,
                "direction_bias": event.direction_bias,
                "raw_response": event.raw_response
            }
            
            result = db.table("ai_events").insert(data).execute()
            
            if result.data:
                logger.info(f"Created AI event for: {event.event_id}")
                return AIEvent(**result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Error creating AI event: {e}")
            return None
    
    @staticmethod
    async def get_valid_events() -> List[AIEvent]:
        """Get all valid events for market data processing"""
        try:
            db = get_db()
            result = db.table("ai_events").select("*").eq("is_valid_event", True).execute()
            
            return [AIEvent(**row) for row in result.data] if result.data else []
            
        except Exception as e:
            logger.error(f"Error getting valid AI events: {e}")
            return []


class MarketDataService:
    """Service for market snapshot operations"""
    
    @staticmethod
    async def create_snapshot(snapshot: MarketSnapshotCreate) -> Optional[MarketSnapshot]:
        """Create a new market snapshot"""
        try:
            db = get_db()
            data = {
                "ticker": snapshot.ticker,
                "event_id": snapshot.event_id,
                "prev_close": snapshot.prev_close,
                "day_open": snapshot.day_open,
                "day_high": snapshot.day_high,
                "day_low": snapshot.day_low,
                "current_price": snapshot.current_price,
                "day_change_pct": snapshot.day_change_pct,
                "volume": snapshot.volume,
                "avg_volume_30d": snapshot.avg_volume_30d,
                "market_cap": snapshot.market_cap
            }
            
            result = db.table("market_snapshots").insert(data).execute()
            
            if result.data:
                logger.info(f"Created market snapshot for: {snapshot.ticker}")
                return MarketSnapshot(**result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Error creating market snapshot: {e}")
            return None
    
    @staticmethod
    async def get_snapshots_for_signal_generation() -> List[MarketSnapshot]:
        """Get snapshots that need signal generation"""
        try:
            db = get_db()
            # Get snapshots that don't have signals yet
            result = db.table("market_snapshots").select("*").execute()
            
            return [MarketSnapshot(**row) for row in result.data] if result.data else []
            
        except Exception as e:
            logger.error(f"Error getting snapshots: {e}")
            return []


class SignalService:
    """Service for trading signal operations"""
    
    @staticmethod
    async def create_signal(signal: SignalCreate) -> Optional[Signal]:
        """Create a new trading signal"""
        try:
            db = get_db()
            data = {
                "ticker": signal.ticker,
                "event_id": signal.event_id,
                "market_snapshot_id": signal.market_snapshot_id,
                "status": "observe",
                "direction": signal.direction,
                "rating": signal.rating,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "target_price": signal.target_price,
                "confidence_score": signal.confidence_score,
                "ma20": signal.ma20,
                "price_above_ma20": signal.price_above_ma20,
                "day_change_pct": signal.day_change_pct,
                "volume_multiplier": signal.volume_multiplier,
                "premarket_price": signal.premarket_price,
                "premarket_change_pct": signal.premarket_change_pct,
                "has_premarket": signal.has_premarket,
                "human_confirmed": False
            }
            
            result = db.table("signals").insert(data).execute()
            
            if result.data:
                logger.info(f"Created signal for: {signal.ticker} ({signal.direction})")
                return Signal(**result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Error creating signal: {e}")
            return None
    
    @staticmethod
    async def get_observe_signals() -> List[Signal]:
        """Get all observe signals for human confirmation"""
        try:
            db = get_db()
            result = db.table("signals").select("*").eq("status", "observe").execute()
            
            return [Signal(**row) for row in result.data] if result.data else []
            
        except Exception as e:
            logger.error(f"Error getting observe signals: {e}")
            return []
    
    @staticmethod
    async def get_confirmed_signals() -> List[Signal]:
        """Get all confirmed signals for D+1 confirmation"""
        try:
            db = get_db()
            result = db.table("signals").select("*").eq("status", "confirmed").execute()
            
            return [Signal(**row) for row in result.data] if result.data else []
            
        except Exception as e:
            logger.error(f"Error getting confirmed signals: {e}")
            return []
    
    @staticmethod
    async def confirm_signal(signal_id: str, confirmed: bool, notes: str = None) -> bool:
        """Human confirmation of signal"""
        try:
            db = get_db()
            data = {
                "human_confirmed": confirmed,
                "status": "confirmed" if confirmed else "cancelled",
                "confirmed_at": datetime.utcnow().isoformat(),
                "notes": notes
            }
            
            db.table("signals").update(data).eq("id", signal_id).execute()
            logger.info(f"Signal {signal_id} confirmed: {confirmed}")
            return True
            
        except Exception as e:
            logger.error(f"Error confirming signal: {e}")
            return False
    
    @staticmethod
    async def update_signal_status(signal_id: str, status: str) -> bool:
        """Update signal status"""
        try:
            db = get_db()
            db.table("signals").update({"status": status}).eq("id", signal_id).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error updating signal status: {e}")
            return False


class OrderService:
    """Service for order operations"""
    
    @staticmethod
    async def create_order(order: OrderCreate) -> Optional[Order]:
        """Create a new order"""
        try:
            db = get_db()
            data = {
                "signal_id": order.signal_id,
                "ticker": order.ticker,
                "direction": order.direction,
                "side": order.side,
                "quantity": order.quantity,
                "price": order.price,
                "stop_price": order.stop_price,
                "status": "pending"
            }
            
            result = db.table("orders").insert(data).execute()
            
            if result.data:
                logger.info(f"Created order for: {order.ticker}")
                return Order(**result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Error creating order: {e}")
            return None
    
    @staticmethod
    async def update_order_tiger_id(order_id: str, tiger_order_id: str) -> bool:
        """Update order with Tiger API order ID"""
        try:
            db = get_db()
            db.table("orders").update({
                "tiger_order_id": tiger_order_id,
                "status": "submitted"
            }).eq("id", order_id).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error updating order Tiger ID: {e}")
            return False


class RiskService:
    """Service for risk state operations"""
    
    @staticmethod
    async def get_risk_state() -> Optional[RiskState]:
        """Get current risk state"""
        try:
            db = get_db()
            result = db.table("risk_state").select("*").limit(1).execute()
            
            if result.data:
                return RiskState(**result.data[0])
            return None
            
        except Exception as e:
            logger.error(f"Error getting risk state: {e}")
            return None
    
    @staticmethod
    async def update_risk_state(updates: Dict[str, Any]) -> bool:
        """Update risk state"""
        try:
            db = get_db()
            db.table("risk_state").update(updates).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error updating risk state: {e}")
            return False


class CooldownService:
    """Service for signal cooldown tracking - 持久化到数据库"""
    
    @staticmethod
    async def record_signal(ticker: str) -> bool:
        """记录信号触发日期到数据库"""
        try:
            db = get_db()
            data = {
                "ticker": ticker,
                "triggered_at": datetime.utcnow().isoformat()
            }
            
            result = db.table("signal_cooldowns").insert(data).execute()
            
            if result.data:
                logger.info(f"Recorded cooldown for: {ticker}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error recording cooldown: {e}")
            return False
    
    @staticmethod
    async def get_recent_signals(days: int = 30) -> Dict[str, datetime]:
        """
        获取最近days天内触发过信号的ticker列表
        返回: {ticker: last_triggered_datetime}
        """
        try:
            db = get_db()
            cutoff_date = (datetime.utcnow() - __import__('datetime').timedelta(days=days)).isoformat()
            
            # 获取最近days天内的所有信号记录
            result = db.table("signal_cooldowns").select("*").gte("triggered_at", cutoff_date).execute()
            
            if not result.data:
                return {}
            
            # 按ticker分组，取每个ticker的最新触发时间
            ticker_dates = {}
            for row in result.data:
                ticker = row["ticker"]
                triggered_at = datetime.fromisoformat(row["triggered_at"].replace('Z', '+00:00'))
                
                if ticker not in ticker_dates or triggered_at > ticker_dates[ticker]:
                    ticker_dates[ticker] = triggered_at
            
            logger.info(f"Loaded {len(ticker_dates)} tickers in cooldown from database")
            return ticker_dates
            
        except Exception as e:
            logger.error(f"Error getting recent signals: {e}")
            return {}
    
    @staticmethod
    async def is_in_cooldown(ticker: str, cooldown_days: int = 30) -> bool:
        """检查ticker是否处于冷却期"""
        try:
            recent_signals = await CooldownService.get_recent_signals(cooldown_days)
            
            if ticker not in recent_signals:
                return False
            
            last_date = recent_signals[ticker]
            days_since = (datetime.utcnow() - last_date).days
            
            return days_since < cooldown_days
            
        except Exception as e:
            logger.error(f"Error checking cooldown: {e}")
            return False


class LogService:
    """Service for logging operations"""
    
    @staticmethod
    async def log_api_call(
        service: str,
        endpoint: str,
        method: str,
        status_code: int = None,
        error_message: str = None,
        duration_ms: int = None,
        request_body: Dict = None,
        response_body: Dict = None
    ) -> bool:
        """Log API call"""
        try:
            db = get_db()
            data = {
                "service": service,
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "error_message": error_message,
                "duration_ms": duration_ms,
                "request_body": request_body,
                "response_body": response_body
            }
            
            db.table("api_call_logs").insert(data).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error logging API call: {e}")
            return False
