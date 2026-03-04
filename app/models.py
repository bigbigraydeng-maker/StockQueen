"""
StockQueen V1 - Data Models
Pydantic models for data validation and serialization
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from enum import Enum
import uuid


# Enums
class EventStatus(str, Enum):
    PENDING = "pending"
    FILTERED = "filtered"
    PROCESSED = "processed"
    ERROR = "error"


class SignalStatus(str, Enum):
    OBSERVE = "observe"
    CONFIRMED = "confirmed"
    TRADE = "trade"
    EXECUTED = "executed"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    PHASE3_POSITIVE = "Phase3_Positive"
    PHASE3_NEGATIVE = "Phase3_Negative"
    FDA_APPROVAL = "FDA_Approval"
    CRL = "CRL"
    PHASE2_POSITIVE = "Phase2_Positive"
    PHASE2_NEGATIVE = "Phase2_Negative"
    OTHER = "Other"


class SignalRating(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DirectionBias(str, Enum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    ERROR = "error"


class RiskStatus(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    PAUSED = "paused"


# Base Model with common fields
class BaseDBModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


# ==================== EVENT MODELS ====================

class NewsEvent(BaseDBModel):
    """Raw news event from RSS feeds"""
    ticker: Optional[str] = None
    title: str
    summary: Optional[str] = None
    url: str
    source: str  # "pr_newswire" or "fda"
    published_at: datetime
    status: EventStatus = EventStatus.PENDING
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "XYZ Pharma Announces Positive Phase 3 Results",
                "url": "https://www.prnewswire.com/...",
                "source": "pr_newswire",
                "published_at": "2025-02-25T10:00:00Z"
            }
        }


class NewsEventCreate(BaseModel):
    """Model for creating news events"""
    title: str
    summary: Optional[str] = None
    url: str
    source: str
    published_at: datetime
    ticker: Optional[str] = None


# ==================== AI EVENT MODELS ====================

class AIClassificationResult(BaseModel):
    """DeepSeek AI classification output"""
    is_valid_event: bool
    event_type: EventType
    direction_bias: DirectionBias


class AIEvent(BaseDBModel):
    """AI classified event"""
    event_id: str  # Reference to news_event.id
    ticker: Optional[str] = None
    is_valid_event: bool
    event_type: EventType
    direction_bias: DirectionBias
    raw_response: Optional[str] = None  # Store original AI response
    
    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "uuid-here",
                "is_valid_event": True,
                "event_type": "Phase3_Positive",
                "direction_bias": "long"
            }
        }


class AIEventCreate(BaseModel):
    """Model for creating AI events"""
    event_id: str
    ticker: Optional[str] = None
    is_valid_event: bool
    event_type: str
    direction_bias: str
    raw_response: Optional[str] = None


# ==================== MARKET DATA MODELS ====================

class MarketSnapshot(BaseDBModel):
    """Market data snapshot from Tiger API"""
    ticker: str
    event_id: str = ""  # Reference to ai_event.id (optional for scan snapshots)
    prev_close: float = 0.0
    day_open: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    current_price: float = 0.0
    day_change_pct: float = 0.0
    volume: int = 0
    avg_volume_30d: int = 0
    market_cap: float = 0.0
    # Computed fields for signal engine (not stored in DB)
    volume_multiplier: float = 0.0
    ma20: Optional[float] = None
    price_above_ma20: Optional[bool] = None
    # Enhanced signal fields (P0/P1 enhancements)
    atr14: Optional[float] = None            # ATR(14) absolute value
    alpha_vs_spy: Optional[float] = None     # Excess return = ticker_change - SPY_change
    crisis_score: Optional[int] = None       # Cross-asset crisis intensity (0-4)
    
    class Config:
        json_schema_extra = {
            "example": {
                "ticker": "XYZ",
                "event_id": "uuid-here",
                "prev_close": 10.0,
                "day_open": 12.5,
                "current_price": 13.0,
                "day_change_pct": 0.30,
                "volume": 5000000,
                "avg_volume_30d": 1000000,
                "market_cap": 1000000000
            }
        }


class MarketSnapshotCreate(BaseModel):
    """Model for creating market snapshots"""
    ticker: str
    event_id: str
    prev_close: float
    day_open: float
    day_high: float
    day_low: float
    current_price: float
    day_change_pct: float
    volume: int
    avg_volume_30d: int
    market_cap: float


# ==================== SIGNAL MODELS ====================

class Signal(BaseDBModel):
    """Trading signal"""
    ticker: str
    event_id: str  # Reference to ai_event.id
    market_snapshot_id: str  # Reference to market_snapshot.id
    status: SignalStatus = SignalStatus.OBSERVE
    direction: DirectionBias
    rating: SignalRating = SignalRating.MEDIUM  # HIGH/MEDIUM/LOW based on trend
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    confidence_score: Optional[float] = None
    ma20: Optional[float] = None  # 20-day moving average
    price_above_ma20: Optional[bool] = None  # Trend indicator
    day_change_pct: Optional[float] = None  # Day gain percentage for chase warning
    volume_multiplier: Optional[float] = None  # Volume vs 30d avg
    # Enhanced signal fields (P0/P1 enhancements)
    atr14: Optional[float] = None
    alpha_vs_spy: Optional[float] = None
    crisis_score: Optional[int] = None
    # Premarket data
    premarket_price: Optional[float] = None
    premarket_change_pct: Optional[float] = None
    has_premarket: Optional[bool] = None
    human_confirmed: bool = False
    confirmed_at: Optional[datetime] = None
    notes: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "ticker": "XYZ",
                "event_id": "uuid-here",
                "market_snapshot_id": "uuid-here",
                "status": "observe",
                "direction": "long"
            }
        }


class SignalCreate(BaseModel):
    """Model for creating signals"""
    ticker: str
    event_id: str
    market_snapshot_id: str
    direction: str
    rating: str = "medium"
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    confidence_score: Optional[float] = None
    ma20: Optional[float] = None
    price_above_ma20: Optional[bool] = None
    day_change_pct: Optional[float] = None
    volume_multiplier: Optional[float] = None
    # Premarket data
    premarket_price: Optional[float] = None
    premarket_change_pct: Optional[float] = None
    has_premarket: Optional[bool] = None
    # Enhanced signal fields (P0/P1 enhancements)
    atr14: Optional[float] = None
    alpha_vs_spy: Optional[float] = None
    crisis_score: Optional[int] = None
    # 市场类型标识 - 支持多市场信号区分
    market_type: str = "PHARMA"  # 可选值: PHARMA, GEOPOLITICAL


class SignalConfirm(BaseModel):
    """Model for human confirmation"""
    signal_id: str
    confirmed: bool
    notes: Optional[str] = None


# ==================== ORDER MODELS ====================

class Order(BaseDBModel):
    """Trading order"""
    signal_id: str
    ticker: str
    direction: DirectionBias
    order_type: str = "limit"  # limit, market, stop
    side: str  # buy, sell
    quantity: int
    price: Optional[float] = None
    stop_price: Optional[float] = None
    tiger_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: Optional[float] = None
    filled_at: Optional[datetime] = None
    error_message: Optional[str] = None


class OrderCreate(BaseModel):
    """Model for creating orders"""
    signal_id: str
    ticker: str
    direction: str
    side: str
    quantity: int
    price: Optional[float] = None
    stop_price: Optional[float] = None


# ==================== TRADE MODELS ====================

class Trade(BaseDBModel):
    """Completed trade record"""
    signal_id: str
    order_id: str
    ticker: str
    direction: DirectionBias
    entry_price: float
    exit_price: Optional[float] = None
    quantity: int
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    entry_at: datetime
    exit_at: Optional[datetime] = None
    status: str = "open"  # open, closed


# ==================== RISK STATE MODELS ====================

class RiskState(BaseDBModel):
    """Current risk state"""
    current_positions: int = 0
    open_position_value: float = 0.0
    account_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    consecutive_losses: int = 0
    status: RiskStatus = RiskStatus.NORMAL
    last_trade_pnl: Optional[float] = None
    paused_at: Optional[datetime] = None
    resume_at: Optional[datetime] = None
    alert_sent: bool = False


# ==================== API RESPONSE MODELS ====================

class APIResponse(BaseModel):
    """Standard API response"""
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None


class SignalSummary(BaseModel):
    """Signal summary for daily notification"""
    date: str
    total_observe: int
    total_confirmed: int
    total_trade: int
    signals: list[Signal]
