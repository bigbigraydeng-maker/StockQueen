"""
StockQueen V1 - Signal Engine Service
Trading signal generation based on market data
"""

import asyncio
import logging
import time
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta
from enum import Enum
import yfinance as yf

from app.config import RiskConfig
from app.config.pharma_watchlist import PHARMA_WATCHLIST
from app.models import SignalCreate, Signal, MarketSnapshot, DirectionBias, SignalRating
from app.services.db_service import MarketDataService, SignalService as SignalDBService, CooldownService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class MarketType(str, Enum):
    """市场类型枚举"""
    PHARMA = "PHARMA"


class TrendAnalyzer:
    """Analyze price trends using moving averages"""
    
    @staticmethod
    async def get_ma20_and_trend(ticker: str) -> Tuple[Optional[float], Optional[bool]]:
        """
        Fetch MA20 and determine if price is above it
        Returns: (ma20_value, price_above_ma20)
        """
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="30d")
            
            if hist.empty or len(hist) < 20:
                logger.warning(f"Insufficient data for MA20 calculation: {ticker}")
                return None, None
            
            ma20 = hist['Close'].tail(20).mean()
            current_price = hist['Close'].iloc[-1]
            price_above_ma20 = current_price > ma20
            
            logger.info(
                f"{ticker} MA20 Analysis: "
                f"MA20=${ma20:.2f}, "
                f"Price=${current_price:.2f}, "
                f"Above MA20={price_above_ma20}"
            )
            
            return round(ma20, 2), price_above_ma20
            
        except Exception as e:
            logger.error(f"Error fetching MA20 for {ticker}: {e}")
            return None, None


class YahooFinanceClient:
    """Client for fetching market data from Yahoo Finance"""
    
    @staticmethod
    async def get_premarket_data(ticker: str, max_retries: int = 3) -> Optional[Dict]:
        """
        Fetch premarket data for a ticker with retry logic
        Returns: Dict with premarket price and change percentage
        """
        for attempt in range(max_retries):
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                current_price = info.get('currentPrice') or info.get('regularMarketPrice')
                previous_close = info.get('previousClose') or info.get('regularMarketPreviousClose')

                if not current_price or not previous_close:
                    logger.warning(f"Missing price data for {ticker} (attempt {attempt + 1})")
                else:
                    change_pct = (current_price - previous_close) / previous_close
                    return {
                        'premarket_price': current_price,
                        'premarket_change_pct': change_pct,
                        'has_premarket': True
                    }

            except Exception as e:
                logger.error(f"Error fetching premarket data for {ticker} (attempt {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying premarket for {ticker} in {wait_time}s...")
                await asyncio.sleep(wait_time)

        logger.error(f"All {max_retries} attempts failed for premarket data of {ticker}")
        return None
    
    @staticmethod
    async def get_market_snapshot(ticker: str, max_retries: int = 3) -> Optional[MarketSnapshot]:
        """
        Fetch complete market snapshot for a ticker with retry logic
        """
        for attempt in range(max_retries):
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period="30d")
                info = stock.info

                if hist.empty:
                    logger.warning(f"No historical data for {ticker} (attempt {attempt + 1})")
                else:
                    # Current price data
                    current_price = info.get('currentPrice') or hist['Close'].iloc[-1]
                    previous_close = info.get('previousClose') or hist['Close'].iloc[-2]
                    day_change_pct = (current_price - previous_close) / previous_close

                    # Volume analysis
                    current_volume = info.get('volume') or hist['Volume'].iloc[-1]
                    avg_volume_30d = hist['Volume'].tail(30).mean()
                    volume_multiplier = current_volume / avg_volume_30d if avg_volume_30d > 0 else 0

                    # Market cap
                    market_cap = info.get('marketCap')

                    # MA20
                    ma20 = hist['Close'].tail(20).mean()
                    price_above_ma20 = current_price > ma20

                    return MarketSnapshot(
                        ticker=ticker,
                        current_price=round(current_price, 2),
                        previous_close=round(previous_close, 2),
                        day_change_pct=round(day_change_pct * 100, 2),
                        volume=int(current_volume),
                        avg_volume_30d=int(avg_volume_30d),
                        volume_multiplier=round(volume_multiplier, 2),
                        market_cap=market_cap,
                        ma20=round(ma20, 2),
                        price_above_ma20=price_above_ma20,
                        timestamp=datetime.utcnow()
                    )

            except Exception as e:
                logger.error(f"Error fetching market snapshot for {ticker} (attempt {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying market snapshot for {ticker} in {wait_time}s...")
                await asyncio.sleep(wait_time)

        logger.error(f"All {max_retries} attempts failed for market snapshot of {ticker}")
        return None


class SignalEngine:
    """Signal generation engine - Pharma市场"""
    
    def __init__(self):
        self.db_service = SignalDBService()
        self.trend_analyzer = TrendAnalyzer()
        self.yahoo_client = YahooFinanceClient()
        self.notification_service = NotificationService()
        self._last_signal_date: Dict[str, datetime] = {}
    
    async def _initialize_cooldown_cache(self):
        """
        从数据库加载最近30天内的信号记录到内存缓存
        在服务启动时调用
        """
        try:
            recent_signals = await CooldownService.get_recent_signals(days=30)
            self._last_signal_date = recent_signals
            logger.info(f"Initialized cooldown cache with {len(recent_signals)} tickers from database")
        except Exception as e:
            logger.error(f"Error initializing cooldown cache: {e}")
            self._last_signal_date = {}
    
    def _is_in_cooldown(self, ticker: str, cooldown_days: int = 30) -> bool:
        """
        检查ticker是否处于冷却期（内存检查，快速）
        如果距离上次触发信号不足cooldown_days天，返回True
        """
        if ticker not in self._last_signal_date:
            return False
        
        last_date = self._last_signal_date[ticker]
        days_since = (datetime.utcnow() - last_date).days
        return days_since < cooldown_days
    
    async def _record_signal(self, ticker: str):
        """
        记录ticker的信号触发日期
        同时更新内存缓存和数据库
        """
        # 更新内存缓存
        self._last_signal_date[ticker] = datetime.utcnow()
        
        # 持久化到数据库
        await CooldownService.record_signal(ticker)
    
    def _get_market_type(self, ticker: str) -> MarketType:
        """根据ticker判断市场类型"""
        return MarketType.PHARMA
    
    def _get_market_cap_limits(self, market_type: MarketType) -> Tuple[float, float]:
        """获取市值限制"""
        return RiskConfig.MIN_MARKET_CAP, RiskConfig.MAX_MARKET_CAP
    
    async def generate_signal(
        self,
        ticker: str,
        event_id: str,
        direction_bias: DirectionBias,
        market_type: Optional[MarketType] = None
    ) -> Optional[Signal]:
        """
        Generate trading signal for a ticker based on event and market conditions
        
        Args:
            ticker: 股票代码
            event_id: 事件ID
            direction_bias: 方向偏好
            market_type: 市场类型（可选，自动检测）
        """
        logger.info(f"Generating signal for {ticker} with bias {direction_bias}")
        
        # 检查冷却期（30天）
        if self._is_in_cooldown(ticker, cooldown_days=30):
            days_since = (datetime.utcnow() - self._last_signal_date[ticker]).days
            logger.info(f"Signal skipped for {ticker}: in cooldown ({days_since} days since last signal)")
            return None
        
        # 自动检测市场类型
        if market_type is None:
            market_type = self._get_market_type(ticker)
        
        # Fetch market data
        snapshot = await self.yahoo_client.get_market_snapshot(ticker)
        if not snapshot:
            logger.error(f"Failed to fetch market data for {ticker}")
            return None
        
        # Check market cap constraints
        min_cap, max_cap = self._get_market_cap_limits(market_type)
        if snapshot.market_cap:
            if snapshot.market_cap < min_cap:
                logger.warning(f"{ticker} market cap too small: ${snapshot.market_cap:,.0f} < ${min_cap:,.0f}")
                return None
            if snapshot.market_cap > max_cap:
                logger.warning(f"{ticker} market cap too large: ${snapshot.market_cap:,.0f} > ${max_cap:,.0f}")
                return None
        
        # Get MA20 and trend
        ma20, price_above_ma20 = await self.trend_analyzer.get_ma20_and_trend(ticker)
        
        # Determine signal direction based on price movement and bias
        signal_direction = self._determine_signal_direction(
            snapshot.day_change_pct,
            direction_bias,
            snapshot.volume_multiplier,
            market_type
        )
        
        if not signal_direction:
            logger.info(f"No signal generated for {ticker} - conditions not met")
            return None
        
        # Calculate confidence score
        confidence_score = self._calculate_confidence(
            snapshot.day_change_pct,
            snapshot.volume_multiplier,
            price_above_ma20,
            signal_direction
        )
        
        # Determine signal rating
        rating = self._determine_rating(price_above_ma20, signal_direction)
        
        # Calculate entry, stop loss, and target prices
        entry_price = snapshot.current_price
        if signal_direction == DirectionBias.LONG:
            stop_loss = entry_price * 0.90  # 10% stop loss
            target_price = entry_price * 1.20  # 20% target
        else:  # SHORT
            stop_loss = entry_price * 1.10  # 10% stop loss
            target_price = entry_price * 0.80  # 20% target
        
        # Create signal
        signal_data = SignalCreate(
            ticker=ticker,
            event_id=event_id,
            market_snapshot_id=snapshot.id if hasattr(snapshot, 'id') else "",
            direction=signal_direction.value,
            rating=rating.value,
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_loss, 2),
            target_price=round(target_price, 2),
            confidence_score=round(confidence_score, 2),
            ma20=ma20,
            price_above_ma20=price_above_ma20,
            day_change_pct=snapshot.day_change_pct,
            volume_multiplier=snapshot.volume_multiplier
        )
        
        # Save to database
        signal = await self.db_service.create_signal(signal_data)
        
        # 记录信号触发日期（用于冷却期过滤）
        await self._record_signal(ticker)
        
        # Send notification
        await self.notification_service.send_signal_alert(signal)
        
        logger.info(f"Signal generated for {ticker}: {signal_direction.value} ({rating.value})")
        return signal
    
    def _determine_signal_direction(
        self,
        day_change_pct: float,
        direction_bias: DirectionBias,
        volume_multiplier: float,
        market_type: MarketType = MarketType.PHARMA
    ) -> Optional[DirectionBias]:
        """
        Determine if signal should be generated based on price movement and bias
        """
        # 获取阈值
        long_threshold = RiskConfig.LONG_MIN_GAIN
        short_threshold = RiskConfig.SHORT_MIN_DROP
        vol_threshold = RiskConfig.VOLUME_MULTIPLIER
        
        # Check volume requirement
        if volume_multiplier < vol_threshold:
            return None
        
        # Long signal conditions
        if direction_bias == DirectionBias.LONG:
            if day_change_pct >= long_threshold * 100:
                return DirectionBias.LONG
        
        # Short signal conditions (only if enabled)
        enable_short = RiskConfig.ENABLE_SHORT_SIGNALS
        if direction_bias == DirectionBias.SHORT and enable_short:
            if day_change_pct <= short_threshold * 100:
                return DirectionBias.SHORT
        
        return None
    
    def _calculate_confidence(
        self,
        day_change_pct: float,
        volume_multiplier: float,
        price_above_ma20: Optional[bool],
        direction: DirectionBias
    ) -> float:
        """
        Calculate confidence score for the signal (0-100)
        """
        confidence = 50.0  # Base confidence
        
        # Volume factor (higher volume = higher confidence)
        if volume_multiplier >= 10:
            confidence += 20
        elif volume_multiplier >= 5:
            confidence += 15
        elif volume_multiplier >= 3:
            confidence += 10
        
        # Price movement factor
        if direction == DirectionBias.LONG:
            if day_change_pct >= 20:
                confidence += 15
            elif day_change_pct >= 15:
                confidence += 10
            elif day_change_pct >= 8:
                confidence += 5
        
        # Trend alignment factor
        if price_above_ma20 is not None:
            if direction == DirectionBias.LONG and price_above_ma20:
                confidence += 10  # Long signal with upward trend
            elif direction == DirectionBias.SHORT and not price_above_ma20:
                confidence += 10  # Short signal with downward trend
        
        return min(confidence, 100.0)
    
    def _determine_rating(
        self,
        price_above_ma20: Optional[bool],
        direction: DirectionBias
    ) -> SignalRating:
        """
        Determine signal rating based on trend alignment
        """
        if price_above_ma20 is None:
            return SignalRating.MEDIUM
        
        if direction == DirectionBias.LONG:
            if price_above_ma20:
                return SignalRating.HIGH  # Long signal with upward trend
            else:
                return SignalRating.MEDIUM  # Long signal against trend
        
        return SignalRating.MEDIUM  # Default for short signals


# Global signal engine instance
signal_engine = SignalEngine()


async def run_signal_generation() -> List[Signal]:
    """
    Run signal generation for all watchlist tickers
    Returns: List of generated signals
    """
    logger.info("=" * 50)
    logger.info("Starting Signal Generation")
    logger.info("=" * 50)
    
    try:
        # Initialize cooldown cache if not already initialized
        await signal_engine._initialize_cooldown_cache()
        
        generated_signals = []
        
        # Process all Pharma watchlist tickers
        from app.config.pharma_watchlist import PHARMA_WATCHLIST
        
        for ticker, _ in PHARMA_WATCHLIST.items():
            try:
                # Generate signal with LONG bias (default)
                from app.models import DirectionBias
                signal = await signal_engine.generate_signal(
                    ticker=ticker,
                    event_id=f"market_scan_{datetime.utcnow().isoformat()}",
                    direction_bias=DirectionBias.LONG
                )
                
                if signal:
                    generated_signals.append(signal)
                    logger.info(f"Generated signal for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error generating signal for {ticker}: {e}")
                continue
        
        logger.info(f"Signal generation completed: {len(generated_signals)} signals generated")
        return generated_signals
        
    except Exception as e:
        logger.error(f"Error in run_signal_generation: {e}")
        return []


async def run_confirmation_engine() -> dict:
    """
    Run D+1 confirmation engine
    Returns: Confirmation results
    """
    logger.info("=" * 50)
    logger.info("Starting Confirmation Engine")
    logger.info("=" * 50)
    
    try:
        # TODO: Implement D+1 confirmation logic
        # This should check signals from previous day and calculate actual returns
        
        confirmation_results = {
            "status": "completed",
            "message": "Confirmation engine run successfully",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info("Confirmation engine completed successfully")
        return confirmation_results
        
    except Exception as e:
        logger.error(f"Error in confirmation engine: {e}")
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
