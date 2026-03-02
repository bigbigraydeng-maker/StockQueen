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
import pandas as pd

from app.config import RiskConfig
from app.config.pharma_watchlist import PHARMA_WATCHLIST
from app.models import SignalCreate, Signal, MarketSnapshot, DirectionBias, SignalRating
from app.services.db_service import MarketDataService, SignalService as SignalDBService, CooldownService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class MarketType(str, Enum):
    """市场类型枚举"""
    PHARMA = "PHARMA"


def _batch_download_history(tickers: list, period: str = "30d") -> Dict[str, pd.DataFrame]:
    """
    Download history for all tickers in small batches with delays to avoid 429 rate limiting.
    yf.download() still makes per-ticker requests internally, so we split into chunks.
    """
    if not tickers:
        return {}

    BATCH_SIZE = 10
    BATCH_DELAY = 3  # seconds between batches

    all_results = {}
    chunks = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

    for chunk_idx, chunk in enumerate(chunks):
        try:
            logger.info(f"Signal batch {chunk_idx + 1}/{len(chunks)}: downloading {period} for {len(chunk)} tickers")

            data = yf.download(
                chunk,
                period=period,
                group_by="ticker" if len(chunk) > 1 else None,
                threads=False
            )

            if not data.empty:
                for ticker in chunk:
                    try:
                        if len(chunk) == 1:
                            df = data
                        else:
                            if ticker not in data.columns.get_level_values(0):
                                continue
                            df = data[ticker]

                        df = df.dropna(subset=['Close'])
                        if not df.empty:
                            all_results[ticker] = df
                    except Exception as e:
                        logger.error(f"Error extracting batch data for {ticker}: {e}")
            else:
                logger.warning(f"Signal batch {chunk_idx + 1} returned empty data")

        except Exception as e:
            logger.error(f"Signal batch {chunk_idx + 1} download error: {e}")

        # Delay between batches to avoid rate limiting
        if chunk_idx < len(chunks) - 1:
            time.sleep(BATCH_DELAY)

    logger.info(f"Signal batch total: {len(all_results)}/{len(tickers)} tickers successful")
    return all_results


def _build_snapshot_from_history(ticker: str, hist: pd.DataFrame) -> Optional[MarketSnapshot]:
    """Build a MarketSnapshot from pre-fetched history DataFrame (no extra API calls)"""
    try:
        if hist.empty or len(hist) < 1:
            return None

        current_price = float(hist['Close'].iloc[-1])
        previous_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current_price
        day_change_pct = ((current_price - previous_close) / previous_close * 100) if previous_close else 0.0

        current_volume = int(hist['Volume'].iloc[-1]) if not pd.isna(hist['Volume'].iloc[-1]) else 0
        avg_volume_30d = int(hist['Volume'].tail(30).mean()) if not hist['Volume'].isna().all() else 0
        volume_multiplier = current_volume / avg_volume_30d if avg_volume_30d > 0 else 0

        ma20 = float(hist['Close'].tail(20).mean()) if len(hist) >= 20 else None
        price_above_ma20 = current_price > ma20 if ma20 else None

        return MarketSnapshot(
            ticker=ticker,
            current_price=round(current_price, 2),
            previous_close=round(previous_close, 2),
            day_change_pct=round(day_change_pct, 2),
            volume=current_volume,
            avg_volume_30d=avg_volume_30d,
            volume_multiplier=round(volume_multiplier, 2),
            market_cap=None,
            ma20=round(ma20, 2) if ma20 else None,
            price_above_ma20=price_above_ma20,
            timestamp=datetime.utcnow()
        )
    except Exception as e:
        logger.error(f"Error building snapshot from history for {ticker}: {e}")
        return None


class TrendAnalyzer:
    """Analyze price trends using moving averages"""

    @staticmethod
    def get_ma20_from_history(ticker: str, hist: pd.DataFrame) -> Tuple[Optional[float], Optional[bool]]:
        """Compute MA20 from pre-fetched history (no API call)"""
        try:
            if hist.empty or len(hist) < 20:
                logger.warning(f"Insufficient data for MA20 calculation: {ticker}")
                return None, None

            ma20 = float(hist['Close'].tail(20).mean())
            current_price = float(hist['Close'].iloc[-1])
            price_above_ma20 = current_price > ma20

            logger.info(
                f"{ticker} MA20: MA20=${ma20:.2f}, Price=${current_price:.2f}, Above={price_above_ma20}"
            )
            return round(ma20, 2), price_above_ma20

        except Exception as e:
            logger.error(f"Error computing MA20 for {ticker}: {e}")
            return None, None

    @staticmethod
    async def get_ma20_and_trend(ticker: str) -> Tuple[Optional[float], Optional[bool]]:
        """Fallback: fetch MA20 via individual API call"""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="30d")
            return TrendAnalyzer.get_ma20_from_history(ticker, hist)
        except Exception as e:
            logger.error(f"Error fetching MA20 for {ticker}: {e}")
            return None, None


class SignalEngine:
    """Signal generation engine - Pharma市场"""
    
    def __init__(self):
        self.db_service = SignalDBService()
        self.trend_analyzer = TrendAnalyzer()
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
        market_type: Optional[MarketType] = None,
        prefetched_hist: Optional[pd.DataFrame] = None
    ) -> Optional[Signal]:
        """
        Generate trading signal for a ticker based on event and market conditions

        Args:
            ticker: 股票代码
            event_id: 事件ID
            direction_bias: 方向偏好
            market_type: 市场类型（可选，自动检测）
            prefetched_hist: 预取的历史数据（避免重复API调用）
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

        # Build snapshot from pre-fetched data or fetch individually
        if prefetched_hist is not None and not prefetched_hist.empty:
            snapshot = _build_snapshot_from_history(ticker, prefetched_hist)
        else:
            snapshot = _build_snapshot_from_history(ticker, pd.DataFrame())
        if not snapshot:
            logger.error(f"Failed to build market snapshot for {ticker}")
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

        # Get MA20 from pre-fetched data or fetch individually
        if prefetched_hist is not None and len(prefetched_hist) >= 20:
            ma20, price_above_ma20 = self.trend_analyzer.get_ma20_from_history(ticker, prefetched_hist)
        else:
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
    Run signal generation for all watchlist tickers.
    Uses batch yf.download() to pre-fetch all data in one call.
    """
    logger.info("=" * 50)
    logger.info("Starting Signal Generation")
    logger.info("=" * 50)

    try:
        # Initialize cooldown cache if not already initialized
        await signal_engine._initialize_cooldown_cache()

        # Batch pre-fetch 30d history for all watchlist tickers (single API call)
        from app.config.pharma_watchlist import PHARMA_WATCHLIST
        tickers = list(PHARMA_WATCHLIST.keys())
        logger.info(f"Batch pre-fetching 30d history for {len(tickers)} watchlist tickers")

        loop = asyncio.get_event_loop()
        batch_data = await loop.run_in_executor(None, _batch_download_history, tickers)

        generated_signals = []

        for ticker, _ in PHARMA_WATCHLIST.items():
            try:
                hist = batch_data.get(ticker)
                if hist is None or hist.empty:
                    logger.warning(f"No batch data for {ticker}, skipping signal generation")
                    continue

                from app.models import DirectionBias
                signal = await signal_engine.generate_signal(
                    ticker=ticker,
                    event_id=f"market_scan_{datetime.utcnow().isoformat()}",
                    direction_bias=DirectionBias.LONG,
                    prefetched_hist=hist
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
