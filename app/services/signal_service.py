"""
StockQueen V2.3 - Signal Engine Service
Trading signal generation based on market data.
Uses Alpha Vantage for market data (replaces yfinance).
"""

import asyncio
import logging
import math
import time
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta
from enum import Enum
import pandas as pd
import warnings

from app.config import RiskConfig
from app.config.pharma_watchlist import PHARMA_WATCHLIST
from app.models import SignalCreate, Signal, MarketSnapshot, DirectionBias, SignalRating
from app.services.db_service import MarketDataService, SignalService as SignalDBService, CooldownService
from app.services.notification_service import NotificationService
from app.services.alphavantage_client import get_av_client

logger = logging.getLogger(__name__)


class MarketType(str, Enum):
    """市场类型枚举"""
    PHARMA = "PHARMA"
    GEOPOLITICAL = "GEOPOLITICAL"


async def _batch_download_history(tickers: list, period: str = "30d") -> Dict[str, pd.DataFrame]:
    """
    Download history for all tickers via Alpha Vantage.
    Replaces yfinance batch download.
    """
    if not tickers:
        return {}

    # Parse period string to days
    days = 30
    if period.endswith("d"):
        days = int(period[:-1])
    elif period.endswith("mo"):
        days = int(period[:-2]) * 30

    av = get_av_client()
    all_results = await av.batch_get_daily_history(tickers, days=days)

    logger.info(f"Alpha Vantage batch total: {len(all_results)}/{len(tickers)} tickers successful")
    return all_results


def _akshare_batch_download(tickers: list) -> Dict[str, pd.DataFrame]:
    """
    Fallback data source using akshare (东方财富) when Yahoo Finance is blocked.
    Downloads 30d history for each ticker individually via ak.stock_us_daily().
    Returns Dict[ticker, DataFrame] with columns: Open, High, Low, Close, Volume.
    """
    if not tickers:
        return {}

    warnings.filterwarnings("ignore")
    all_results = {}
    BATCH_DELAY = 0.3  # 300ms between requests

    # Filter out non-US tickers (akshare stock_us_daily only supports US stocks)
    us_tickers = [t for t in tickers if not t.endswith('.HK')]
    skipped = len(tickers) - len(us_tickers)
    if skipped:
        logger.info(f"akshare: skipping {skipped} non-US tickers (.HK)")

    for i, ticker in enumerate(us_tickers):
        try:
            import akshare as ak
            df = ak.stock_us_daily(symbol=ticker, adjust='')

            if df is None or df.empty:
                logger.warning(f"akshare: no data for {ticker}")
                continue

            # Normalize column names to match yfinance format
            df = df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume',
            })

            # Keep only last 30 rows
            df = df.tail(30).copy()

            if not df.empty:
                all_results[ticker] = df

            if (i + 1) % 20 == 0:
                logger.info(f"akshare progress: {i + 1}/{len(us_tickers)} tickers fetched")

        except Exception as e:
            logger.error(f"akshare error for {ticker}: {e}")

        time.sleep(BATCH_DELAY)

    logger.info(f"akshare total: {len(all_results)}/{len(tickers)} tickers successful")
    return all_results


def _build_snapshot_from_history(ticker: str, hist: pd.DataFrame) -> Optional[MarketSnapshot]:
    """Build a MarketSnapshot from pre-fetched history DataFrame (no extra API calls)"""
    try:
        if hist.empty or len(hist) < 1:
            return None

        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else latest
        current_price = float(latest['Close'])
        previous_close = float(prev['Close'])
        day_change_pct = ((current_price - previous_close) / previous_close * 100) if previous_close else 0.0

        current_volume = int(latest['Volume']) if not pd.isna(latest['Volume']) else 0
        avg_volume_30d = int(hist['Volume'].tail(30).mean()) if not hist['Volume'].isna().all() else 0
        volume_multiplier = current_volume / avg_volume_30d if avg_volume_30d > 0 else 0

        day_open = float(latest['Open']) if 'Open' in hist.columns else current_price
        day_high = float(latest['High']) if 'High' in hist.columns else current_price
        day_low = float(latest['Low']) if 'Low' in hist.columns else current_price

        ma20_val = round(float(hist['Close'].tail(20).mean()), 2) if len(hist) >= 20 else None

        # Compute ATR(14) for adaptive thresholds (P0-1)
        atr14_val = _compute_atr14(hist, RiskConfig.GEO_ATR_PERIOD)

        return MarketSnapshot(
            ticker=ticker,
            event_id="scan_snapshot",
            prev_close=round(previous_close, 2),
            day_open=round(day_open, 2),
            day_high=round(day_high, 2),
            day_low=round(day_low, 2),
            current_price=round(current_price, 2),
            day_change_pct=round(day_change_pct, 2),
            volume=current_volume,
            avg_volume_30d=avg_volume_30d,
            market_cap=0.0,
            volume_multiplier=round(volume_multiplier, 2),
            ma20=ma20_val,
            price_above_ma20=current_price > ma20_val if ma20_val else None,
            atr14=atr14_val,
        )
    except Exception as e:
        logger.error(f"Error building snapshot from history for {ticker}: {e}")
        return None


# ==================== P0/P1 Enhancement Helpers ====================

def _compute_atr14(hist: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Compute ATR(period) from OHLCV DataFrame.
    ATR = rolling mean of True Range over `period` days.
    True Range = max(H-L, |H-prevClose|, |L-prevClose|)
    """
    try:
        if hist.empty or len(hist) < period + 1:
            return None

        high = hist['High']
        low = hist['Low']
        close = hist['Close']
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean().iloc[-1]

        if pd.isna(atr):
            return None
        return round(float(atr), 4)
    except Exception as e:
        logger.error(f"Error computing ATR: {e}")
        return None


def _compute_spy_change(spy_hist: pd.DataFrame) -> Optional[float]:
    """Compute SPY's latest day_change_pct from its history DataFrame."""
    try:
        if spy_hist is None or spy_hist.empty or len(spy_hist) < 2:
            return None
        current = float(spy_hist['Close'].iloc[-1])
        previous = float(spy_hist['Close'].iloc[-2])
        return round(((current - previous) / previous * 100), 2)
    except Exception as e:
        logger.error(f"Error computing SPY change: {e}")
        return None


def _compute_crisis_score(batch_data: Dict[str, pd.DataFrame]) -> int:
    """
    Compute crisis intensity score (0-4) based on cross-asset moves.
    Each asset moving in the "crisis direction" beyond threshold contributes +1.
    """
    score = 0
    threshold = RiskConfig.GEO_CRISIS_THRESHOLD

    for asset_ticker, expected_direction in RiskConfig.GEO_CRISIS_ASSETS:
        hist = batch_data.get(asset_ticker)
        if hist is None or hist.empty or len(hist) < 2:
            continue

        try:
            current = float(hist['Close'].iloc[-1])
            previous = float(hist['Close'].iloc[-2])
            change_pct = ((current - previous) / previous * 100)

            if expected_direction == "up" and change_pct >= threshold:
                score += 1
                logger.info(f"  Crisis asset {asset_ticker}: {change_pct:+.2f}% (expected UP) -> +1")
            elif expected_direction == "down" and change_pct <= -threshold:
                score += 1
                logger.info(f"  Crisis asset {asset_ticker}: {change_pct:+.2f}% (expected DOWN) -> +1")
            else:
                logger.info(f"  Crisis asset {asset_ticker}: {change_pct:+.2f}% (expected {expected_direction}) -> 0")
        except Exception:
            continue

    return score


def _compute_event_decay_multiplier() -> float:
    """
    Compute ATR multiplier adjustment based on event time decay.
    Returns >= 1.0: higher = harder to trigger signals (event fading).
    Day 0: 1.0 | Day 7: ~2.0 | Day 14: ~4.0 | capped at GEO_DECAY_MAX_MULTIPLIER
    """
    if not RiskConfig.GEO_USE_EVENT_DECAY:
        return 1.0

    try:
        event_date = datetime.strptime(RiskConfig.GEO_EVENT_DATE, "%Y-%m-%d")
        days_since = (datetime.utcnow() - event_date).days

        if days_since < 0:
            return 1.0  # Event hasn't happened yet

        decay_factor = math.exp(-RiskConfig.GEO_DECAY_RATE * days_since)
        # Floor to prevent extreme values: 1/floor = max multiplier
        min_decay = 1.0 / RiskConfig.GEO_DECAY_MAX_MULTIPLIER
        decay_factor = max(decay_factor, min_decay)

        return round(1.0 / decay_factor, 2)
    except Exception as e:
        logger.error(f"Error computing event decay: {e}")
        return 1.0


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
        """Fallback: fetch MA20 via Alpha Vantage individual API call"""
        try:
            av = get_av_client()
            hist = await av.get_daily_history(ticker, days=30)
            if hist is None or hist.empty:
                return None, None
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
        from app.config.geopolitical_watchlist import GEOPOLITICAL_ALL_WATCHLIST
        if ticker in GEOPOLITICAL_ALL_WATCHLIST:
            return MarketType.GEOPOLITICAL
        return MarketType.PHARMA

    def _get_market_cap_limits(self, market_type: MarketType) -> Tuple[float, float]:
        """获取市值限制"""
        if market_type == MarketType.GEOPOLITICAL:
            return RiskConfig.GEO_MIN_MARKET_CAP, RiskConfig.GEO_MAX_MARKET_CAP
        return RiskConfig.MIN_MARKET_CAP, RiskConfig.MAX_MARKET_CAP
    
    async def generate_signal(
        self,
        ticker: str,
        event_id: str,
        direction_bias: DirectionBias,
        market_type: Optional[MarketType] = None,
        prefetched_hist: Optional[pd.DataFrame] = None,
        spy_change: Optional[float] = None,
        crisis_score: Optional[int] = None,
    ) -> Optional[Signal]:
        """
        Generate trading signal for a ticker based on event and market conditions

        Args:
            ticker: 股票代码
            event_id: 事件ID
            direction_bias: 方向偏好
            market_type: 市场类型（可选，自动检测）
            prefetched_hist: 预取的历史数据（避免重复API调用）
            spy_change: SPY当日涨跌幅（用于计算alpha）
            crisis_score: 跨资产危机强度评分 (0-4)
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

        # Check market cap constraints (skip when limits are 0)
        min_cap, max_cap = self._get_market_cap_limits(market_type)
        if snapshot.market_cap:
            if min_cap > 0 and snapshot.market_cap < min_cap:
                logger.warning(f"{ticker} market cap too small: ${snapshot.market_cap:,.0f} < ${min_cap:,.0f}")
                return None
            if max_cap > 0 and snapshot.market_cap > max_cap:
                logger.warning(f"{ticker} market cap too large: ${snapshot.market_cap:,.0f} > ${max_cap:,.0f}")
                return None

        # Compute alpha vs SPY (P0-2)
        alpha_vs_spy = None
        if spy_change is not None:
            alpha_vs_spy = round(snapshot.day_change_pct - spy_change, 2)

        # Get MA20 from pre-fetched data or fetch individually
        if prefetched_hist is not None and len(prefetched_hist) >= 20:
            ma20, price_above_ma20 = self.trend_analyzer.get_ma20_from_history(ticker, prefetched_hist)
        else:
            ma20, price_above_ma20 = await self.trend_analyzer.get_ma20_and_trend(ticker)

        # Determine signal direction (enhanced with ATR + Alpha + Decay)
        signal_direction = self._determine_signal_direction(
            snapshot.day_change_pct,
            direction_bias,
            snapshot.volume_multiplier,
            market_type,
            atr14=snapshot.atr14,
            current_price=snapshot.current_price,
            alpha_vs_spy=alpha_vs_spy,
        )

        if not signal_direction:
            logger.info(f"No signal generated for {ticker} - conditions not met")
            return None

        # Calculate confidence score (enhanced with crisis multiplier)
        confidence_score = self._calculate_confidence(
            snapshot.day_change_pct,
            snapshot.volume_multiplier,
            price_above_ma20,
            signal_direction,
            crisis_score=crisis_score,
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
            volume_multiplier=snapshot.volume_multiplier,
            atr14=round(snapshot.atr14, 4) if snapshot.atr14 else None,
            alpha_vs_spy=alpha_vs_spy,
            crisis_score=crisis_score,
            market_type=market_type.value if market_type else "PHARMA",
        )

        # Save to database (may fail if schema mismatch, but don't lose the signal)
        signal = await self.db_service.create_signal(signal_data)

        # If DB save failed, create an in-memory Signal object so callers still get data
        if signal is None:
            logger.warning(f"DB save failed for {ticker}, creating in-memory signal")
            signal = Signal(
                ticker=ticker,
                event_id=event_id,
                market_snapshot_id=snapshot.id if hasattr(snapshot, 'id') else "",
                direction=signal_direction,
                rating=SignalRating(rating.value),
                entry_price=round(entry_price, 2),
                stop_loss=round(stop_loss, 2),
                target_price=round(target_price, 2),
                confidence_score=round(confidence_score, 2),
                ma20=ma20,
                price_above_ma20=price_above_ma20,
                day_change_pct=snapshot.day_change_pct,
                volume_multiplier=snapshot.volume_multiplier,
                atr14=round(snapshot.atr14, 4) if snapshot.atr14 else None,
                alpha_vs_spy=alpha_vs_spy,
                crisis_score=crisis_score,
            )

        # 记录信号触发日期（用于冷却期过滤）
        await self._record_signal(ticker)

        # Send notification (non-fatal if fails)
        try:
            await self.notification_service.send_high_signal_alert(signal)
        except Exception as e:
            logger.warning(f"Notification failed for {ticker}: {e}")

        logger.info(f"Signal generated for {ticker}: {signal_direction.value} ({rating.value})")
        return signal
    
    def _determine_signal_direction(
        self,
        day_change_pct: float,
        direction_bias: DirectionBias,
        volume_multiplier: float,
        market_type: MarketType = MarketType.PHARMA,
        atr14: Optional[float] = None,
        current_price: Optional[float] = None,
        alpha_vs_spy: Optional[float] = None,
    ) -> Optional[DirectionBias]:
        """
        Determine if signal should be generated based on price movement and bias.
        For GEOPOLITICAL: uses ATR-adaptive thresholds + SPY alpha + event decay.
        For PHARMA: uses fixed thresholds with direction-bias constraint.
        """
        # 根据市场类型选择基础配置
        if market_type == MarketType.GEOPOLITICAL:
            vol_threshold = RiskConfig.GEO_VOLUME_MULTIPLIER
            enable_short = RiskConfig.GEO_ENABLE_SHORT_SIGNALS
        else:
            vol_threshold = RiskConfig.VOLUME_MULTIPLIER
            enable_short = RiskConfig.ENABLE_SHORT_SIGNALS

        # Check volume requirement (universal gate)
        if volume_multiplier < vol_threshold:
            return None

        # === GEOPOLITICAL: ATR-adaptive + Alpha + Decay ===
        if market_type == MarketType.GEOPOLITICAL:
            # Step 1: Determine effective change (alpha vs raw)
            if RiskConfig.GEO_USE_ALPHA_VS_SPY and alpha_vs_spy is not None:
                effective_change = alpha_vs_spy
                change_label = f"alpha={alpha_vs_spy:+.2f}%"
            else:
                effective_change = day_change_pct
                change_label = f"raw={day_change_pct:+.2f}%"

            # Step 2: Determine dynamic thresholds
            if (RiskConfig.GEO_USE_ATR_THRESHOLDS
                    and atr14 is not None and atr14 > 0
                    and current_price and current_price > 0):
                # Convert ATR to percentage of price
                atr_pct = (atr14 / current_price) * 100

                # Base multipliers
                base_n_long = RiskConfig.GEO_ATR_LONG_MULTIPLIER
                base_n_short = RiskConfig.GEO_ATR_SHORT_MULTIPLIER

                # Apply event decay (multiplier >= 1.0, increases over time)
                decay_mult = _compute_event_decay_multiplier()
                effective_n_long = base_n_long * decay_mult
                effective_n_short = base_n_short * decay_mult

                long_threshold_pct = effective_n_long * atr_pct
                short_threshold_pct = -(effective_n_short * atr_pct)

                logger.info(
                    f"  ATR thresholds: ATR=${atr14:.2f} ({atr_pct:.2f}%), "
                    f"long>={long_threshold_pct:.2f}%, short<={short_threshold_pct:.2f}% "
                    f"(N={base_n_long:.1f}, decay={decay_mult:.2f}x)"
                )
            else:
                # Fallback to fixed thresholds
                long_threshold_pct = RiskConfig.GEO_LONG_MIN_GAIN * 100   # 3.0%
                short_threshold_pct = RiskConfig.GEO_SHORT_MIN_DROP * 100  # -4.0%
                logger.debug(f"  Using fixed thresholds: long>={long_threshold_pct:.1f}%, short<={short_threshold_pct:.1f}%")

            # Step 3: Direction-agnostic signal check
            if effective_change >= long_threshold_pct:
                logger.info(f"  -> GEO LONG: {change_label} >= {long_threshold_pct:.2f}%")
                return DirectionBias.LONG
            if enable_short and effective_change <= short_threshold_pct:
                logger.info(f"  -> GEO SHORT: {change_label} <= {short_threshold_pct:.2f}%")
                return DirectionBias.SHORT
            return None

        # === PHARMA: Fixed thresholds with direction-bias constraint (unchanged) ===
        long_threshold = RiskConfig.LONG_MIN_GAIN
        short_threshold = RiskConfig.SHORT_MIN_DROP

        if direction_bias == DirectionBias.LONG:
            if day_change_pct >= long_threshold * 100:
                return DirectionBias.LONG

        if direction_bias == DirectionBias.SHORT and enable_short:
            if day_change_pct <= short_threshold * 100:
                return DirectionBias.SHORT

        return None
    
    def _calculate_confidence(
        self,
        day_change_pct: float,
        volume_multiplier: float,
        price_above_ma20: Optional[bool],
        direction: DirectionBias,
        crisis_score: Optional[int] = None,
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
        elif direction == DirectionBias.SHORT:
            # P0 fix: SHORT signals also get price movement confidence
            if abs(day_change_pct) >= 15:
                confidence += 15
            elif abs(day_change_pct) >= 8:
                confidence += 10
            elif abs(day_change_pct) >= 4:
                confidence += 5

        # Trend alignment factor
        if price_above_ma20 is not None:
            if direction == DirectionBias.LONG and price_above_ma20:
                confidence += 10  # Long signal with upward trend
            elif direction == DirectionBias.SHORT and not price_above_ma20:
                confidence += 10  # Short signal with downward trend

        # P1-1: Cross-asset crisis confirmation multiplier
        if crisis_score is not None and crisis_score > 0:
            crisis_factor = 1 + crisis_score * RiskConfig.GEO_CRISIS_CONFIDENCE_FACTOR
            confidence *= crisis_factor
            logger.info(f"  Crisis score {crisis_score}/4: confidence × {crisis_factor:.2f}")

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
    Uses Alpha Vantage batch download to pre-fetch all data.
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

        batch_data = await _batch_download_history(tickers)

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


async def run_geopolitical_scan() -> List[Signal]:
    """
    Run geopolitical crisis scan for Hormuz crisis beneficiaries/losers.
    Enhanced with: ATR-adaptive thresholds, SPY alpha, cross-asset confirmation, event decay.
    """
    logger.info("=" * 50)
    logger.info("Starting Geopolitical Crisis Scan (Hormuz) - Enhanced")
    logger.info("=" * 50)

    try:
        await signal_engine._initialize_cooldown_cache()

        from app.config.geopolitical_watchlist import (
            GEOPOLITICAL_LONG_WATCHLIST,
            GEOPOLITICAL_SHORT_WATCHLIST,
            GEOPOLITICAL_SECTOR_MAP,
        )

        long_tickers = list(GEOPOLITICAL_LONG_WATCHLIST.keys())
        short_tickers = list(GEOPOLITICAL_SHORT_WATCHLIST.keys())
        all_tickers = long_tickers + short_tickers

        # Add supplemental tickers: SPY + cross-asset confirmation tickers
        spy_ticker = RiskConfig.GEO_SPY_TICKER
        crisis_tickers = [t for t, _ in RiskConfig.GEO_CRISIS_ASSETS]
        supplemental = [spy_ticker] + crisis_tickers
        all_download_tickers = list(set(all_tickers + supplemental))

        logger.info(
            f"Geopolitical scan: {len(long_tickers)} long + {len(short_tickers)} short "
            f"+ {len(supplemental)} supplemental ({', '.join(supplemental)})"
        )

        # Log event decay status
        decay_mult = _compute_event_decay_multiplier()
        logger.info(f"Event decay multiplier: {decay_mult:.2f}x (event date: {RiskConfig.GEO_EVENT_DATE})")

        # Batch download history via Alpha Vantage
        batch_data = await _batch_download_history(all_download_tickers)

        # Fallback to akshare if Alpha Vantage returned no data
        if len(batch_data) < len(all_download_tickers) * 0.1:
            logger.warning(
                f"Alpha Vantage returned only {len(batch_data)}/{len(all_download_tickers)} tickers, "
                f"falling back to akshare..."
            )
            loop = asyncio.get_event_loop()
            batch_data = await loop.run_in_executor(
                None, _akshare_batch_download, all_download_tickers
            )

        # === Pre-compute global values ===

        # P0-2: SPY relative strength
        spy_hist = batch_data.get(spy_ticker)
        spy_change = _compute_spy_change(spy_hist)
        if spy_change is not None:
            logger.info(f"SPY day_change: {spy_change:+.2f}%")
        else:
            logger.warning("Could not compute SPY change - alpha will be unavailable")

        # P1-1: Cross-asset crisis score
        crisis_score = _compute_crisis_score(batch_data)
        logger.info(f"Crisis intensity score: {crisis_score}/4")

        generated_signals = []

        # --- Long candidates ---
        for ticker in long_tickers:
            try:
                hist = batch_data.get(ticker)
                if hist is None or hist.empty:
                    continue

                sector = GEOPOLITICAL_SECTOR_MAP.get(ticker, "UNKNOWN")
                signal = await signal_engine.generate_signal(
                    ticker=ticker,
                    event_id=f"geo_hormuz_long_{sector}_{datetime.utcnow().isoformat()}",
                    direction_bias=DirectionBias.LONG,
                    market_type=MarketType.GEOPOLITICAL,
                    prefetched_hist=hist,
                    spy_change=spy_change,
                    crisis_score=crisis_score,
                )
                if signal:
                    generated_signals.append(signal)
                    logger.info(f"GEO signal: {ticker} ({sector}) -> {signal.direction}")
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")

        # --- Short candidates ---
        for ticker in short_tickers:
            try:
                hist = batch_data.get(ticker)
                if hist is None or hist.empty:
                    continue

                sector = GEOPOLITICAL_SECTOR_MAP.get(ticker, "UNKNOWN")
                signal = await signal_engine.generate_signal(
                    ticker=ticker,
                    event_id=f"geo_hormuz_short_{sector}_{datetime.utcnow().isoformat()}",
                    direction_bias=DirectionBias.SHORT,
                    market_type=MarketType.GEOPOLITICAL,
                    prefetched_hist=hist,
                    spy_change=spy_change,
                    crisis_score=crisis_score,
                )
                if signal:
                    generated_signals.append(signal)
                    logger.info(f"GEO signal: {ticker} ({sector}) -> {signal.direction}")
            except Exception as e:
                logger.error(f"Error scanning {ticker}: {e}")

        logger.info(
            f"Geopolitical scan completed: {len(generated_signals)} signals generated"
        )
        return generated_signals

    except Exception as e:
        logger.error(f"Error in run_geopolitical_scan: {e}")
        return []


# ==================== Backtest ====================

def _akshare_download_to_date(tickers: list, target_date_str: str) -> Dict[str, pd.DataFrame]:
    """
    Download full history via akshare and slice to end at target_date.
    Returns Dict[ticker, DataFrame] with 30 trading days ending on or before target_date.
    Columns: Open, High, Low, Close, Volume (capitalized to match yfinance format).
    """
    if not tickers:
        return {}

    warnings.filterwarnings("ignore")
    all_results = {}
    BATCH_DELAY = 0.3
    target_date = pd.Timestamp(target_date_str)

    us_tickers = [t for t in tickers if not t.endswith('.HK')]
    skipped = len(tickers) - len(us_tickers)
    if skipped:
        logger.info(f"akshare backtest: skipping {skipped} non-US tickers (.HK)")

    for i, ticker in enumerate(us_tickers):
        try:
            import akshare as ak
            df = ak.stock_us_daily(symbol=ticker, adjust='')

            if df is None or df.empty:
                continue

            # Normalize column names
            df = df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'volume': 'Volume',
            })

            # Slice to target_date
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df[df['date'] <= target_date]

            # Keep last 30 trading days
            df = df.tail(30).copy()

            if not df.empty and len(df) >= 2:
                all_results[ticker] = df

            if (i + 1) % 20 == 0:
                logger.info(f"akshare backtest progress: {i + 1}/{len(us_tickers)} tickers fetched")

        except Exception as e:
            logger.error(f"akshare backtest error for {ticker}: {e}")

        time.sleep(BATCH_DELAY)

    logger.info(f"akshare backtest total: {len(all_results)}/{len(tickers)} tickers successful")
    return all_results


async def run_geopolitical_backtest(
    target_date: str = "2026-02-28",
    ticker_limit: Optional[int] = None,
) -> dict:
    """
    Backtest the geopolitical signal engine against a historical date.
    Uses akshare (free) for full historical data.
    Returns signals + detailed diagnostics for every ticker.
    No cooldown, no DB writes, no notifications.
    """
    logger.info("=" * 50)
    logger.info(f"Geopolitical BACKTEST for date: {target_date}")
    logger.info("=" * 50)

    try:
        from app.config.geopolitical_watchlist import (
            GEOPOLITICAL_LONG_WATCHLIST,
            GEOPOLITICAL_SHORT_WATCHLIST,
            GEOPOLITICAL_SECTOR_MAP,
        )

        long_tickers = list(GEOPOLITICAL_LONG_WATCHLIST.keys())
        short_tickers = list(GEOPOLITICAL_SHORT_WATCHLIST.keys())

        # Apply ticker limit if specified
        if ticker_limit:
            long_tickers = long_tickers[:ticker_limit]
            short_limit = max(0, ticker_limit - len(long_tickers))
            short_tickers = short_tickers[:short_limit] if short_limit > 0 else short_tickers[:3]

        all_tickers = long_tickers + short_tickers

        # Add supplemental tickers: SPY + crisis assets
        spy_ticker = RiskConfig.GEO_SPY_TICKER
        crisis_tickers = [t for t, _ in RiskConfig.GEO_CRISIS_ASSETS]
        supplemental = [spy_ticker] + crisis_tickers
        all_download_tickers = list(set(all_tickers + supplemental))

        logger.info(
            f"Backtest: {len(long_tickers)} long + {len(short_tickers)} short "
            f"+ {len(supplemental)} supplemental, target_date={target_date}"
        )

        # Compute event decay for target date
        try:
            event_date = datetime.strptime(RiskConfig.GEO_EVENT_DATE, "%Y-%m-%d")
            backtest_date = datetime.strptime(target_date, "%Y-%m-%d")
            days_since_event = (backtest_date - event_date).days
        except Exception:
            days_since_event = 0

        if days_since_event < 0:
            decay_multiplier = 1.0  # Event hasn't happened yet
        elif RiskConfig.GEO_USE_EVENT_DECAY:
            decay_factor = math.exp(-RiskConfig.GEO_DECAY_RATE * days_since_event)
            min_decay = 1.0 / RiskConfig.GEO_DECAY_MAX_MULTIPLIER
            decay_factor = max(decay_factor, min_decay)
            decay_multiplier = round(1.0 / decay_factor, 2)
        else:
            decay_multiplier = 1.0

        logger.info(f"Backtest decay: {days_since_event} days since event, multiplier={decay_multiplier}")

        # Download historical data via akshare
        loop = asyncio.get_event_loop()
        batch_data = await loop.run_in_executor(
            None, _akshare_download_to_date, all_download_tickers, target_date
        )

        if not batch_data:
            return {
                "target_date": target_date,
                "error": "No data returned from akshare. Check date or network.",
                "signals_generated": 0,
                "signals": [],
                "diagnostics": [],
            }

        # === Pre-compute global values ===
        spy_hist = batch_data.get(spy_ticker)
        spy_change = _compute_spy_change(spy_hist)
        crisis_score = _compute_crisis_score(batch_data)

        global_info = {
            "spy_change": spy_change,
            "crisis_score": crisis_score,
            "decay_multiplier": decay_multiplier,
            "event_days_ago": days_since_event,
            "event_date": RiskConfig.GEO_EVENT_DATE,
            "tickers_downloaded": len(batch_data),
        }

        logger.info(f"Backtest globals: SPY={spy_change}, crisis={crisis_score}/4, decay={decay_multiplier}x")

        # === Scan each ticker with full diagnostics ===
        signals = []
        diagnostics = []

        all_scan_tickers = [(t, "long") for t in long_tickers] + [(t, "short") for t in short_tickers]

        for ticker, bias_str in all_scan_tickers:
            hist = batch_data.get(ticker)
            diag = {
                "ticker": ticker,
                "sector": GEOPOLITICAL_SECTOR_MAP.get(ticker, "UNKNOWN"),
                "direction_bias": bias_str,
                "result": "SKIP_NO_DATA",
                "reason": "No data available",
            }

            if hist is None or hist.empty or len(hist) < 2:
                diagnostics.append(diag)
                continue

            # Build snapshot
            snapshot = _build_snapshot_from_history(ticker, hist)
            if not snapshot:
                diag["result"] = "SKIP_SNAPSHOT_FAIL"
                diag["reason"] = "Failed to build market snapshot"
                diagnostics.append(diag)
                continue

            day_change_pct = snapshot.day_change_pct
            volume_mult = snapshot.volume_multiplier
            atr14 = snapshot.atr14
            current_price = snapshot.current_price

            # Compute alpha
            alpha_vs_spy = round(day_change_pct - spy_change, 2) if spy_change is not None else None

            # Populate basic diagnostics
            diag["current_price"] = current_price
            diag["day_change_pct"] = day_change_pct
            diag["volume_multiplier"] = round(volume_mult, 2)
            diag["atr14"] = round(atr14, 4) if atr14 else None
            diag["alpha_vs_spy"] = alpha_vs_spy

            # Volume gate
            vol_threshold = RiskConfig.GEO_VOLUME_MULTIPLIER
            if volume_mult < vol_threshold:
                diag["result"] = "SKIP_VOLUME"
                diag["reason"] = f"volume {volume_mult:.2f}x < {vol_threshold}x"
                diagnostics.append(diag)
                continue

            # Determine effective change
            if RiskConfig.GEO_USE_ALPHA_VS_SPY and alpha_vs_spy is not None:
                effective_change = alpha_vs_spy
                diag["change_type"] = "alpha"
            else:
                effective_change = day_change_pct
                diag["change_type"] = "raw"
            diag["effective_change"] = effective_change

            # Determine thresholds
            if (RiskConfig.GEO_USE_ATR_THRESHOLDS
                    and atr14 is not None and atr14 > 0
                    and current_price and current_price > 0):
                atr_pct = (atr14 / current_price) * 100
                n_long = RiskConfig.GEO_ATR_LONG_MULTIPLIER * decay_multiplier
                n_short = RiskConfig.GEO_ATR_SHORT_MULTIPLIER * decay_multiplier
                long_threshold = round(n_long * atr_pct, 2)
                short_threshold = round(-(n_short * atr_pct), 2)
                diag["atr_pct"] = round(atr_pct, 2)
                diag["threshold_type"] = "ATR_adaptive"
            else:
                long_threshold = round(RiskConfig.GEO_LONG_MIN_GAIN * 100, 2)
                short_threshold = round(RiskConfig.GEO_SHORT_MIN_DROP * 100, 2)
                diag["atr_pct"] = None
                diag["threshold_type"] = "fixed"

            diag["long_threshold"] = long_threshold
            diag["short_threshold"] = short_threshold

            # Direction check (direction-agnostic for geopolitical)
            signal_direction = None
            if effective_change >= long_threshold:
                signal_direction = "long"
            elif RiskConfig.GEO_ENABLE_SHORT_SIGNALS and effective_change <= short_threshold:
                signal_direction = "short"

            if signal_direction:
                # Calculate confidence
                direction_bias = DirectionBias.LONG if signal_direction == "long" else DirectionBias.SHORT
                ma20, price_above_ma20 = TrendAnalyzer.get_ma20_from_history(ticker, hist)

                confidence = signal_engine._calculate_confidence(
                    day_change_pct, volume_mult, price_above_ma20, direction_bias,
                    crisis_score=crisis_score,
                )

                # Calculate entry/stop/target
                entry = current_price
                if signal_direction == "long":
                    stop = round(entry * 0.90, 2)
                    target = round(entry * 1.20, 2)
                else:
                    stop = round(entry * 1.10, 2)
                    target = round(entry * 0.80, 2)

                sig_info = {
                    "ticker": ticker,
                    "sector": GEOPOLITICAL_SECTOR_MAP.get(ticker, "UNKNOWN"),
                    "direction": signal_direction,
                    "entry_price": entry,
                    "stop_loss": stop,
                    "target_price": target,
                    "confidence": round(confidence, 1),
                    "day_change_pct": day_change_pct,
                    "alpha_vs_spy": alpha_vs_spy,
                    "volume_multiplier": round(volume_mult, 2),
                    "atr14": round(atr14, 4) if atr14 else None,
                }
                signals.append(sig_info)

                diag["result"] = f"SIGNAL_{signal_direction.upper()}"
                diag["reason"] = (
                    f"{'alpha' if diag.get('change_type') == 'alpha' else 'raw'} "
                    f"{effective_change:+.2f}% {'>' if signal_direction == 'long' else '<'} "
                    f"{'long' if signal_direction == 'long' else 'short'} threshold "
                    f"{long_threshold if signal_direction == 'long' else short_threshold:.2f}%"
                )
                diag["confidence"] = round(confidence, 1)
            else:
                diag["result"] = "SKIP_THRESHOLD"
                diag["reason"] = (
                    f"effective_change {effective_change:+.2f}% "
                    f"between [{short_threshold:.2f}%, {long_threshold:.2f}%]"
                )

            diagnostics.append(diag)

        # Sort diagnostics: signals first, then by abs(day_change_pct) descending
        diagnostics.sort(
            key=lambda d: (
                0 if d["result"].startswith("SIGNAL") else 1,
                -abs(d.get("day_change_pct", 0) or 0),
            )
        )

        logger.info(f"Backtest completed: {len(signals)} signals from {len(diagnostics)} tickers scanned")

        return {
            "target_date": target_date,
            "global_info": global_info,
            "signals_generated": len(signals),
            "signals": signals,
            "total_scanned": len(diagnostics),
            "diagnostics": diagnostics,
        }

    except Exception as e:
        logger.error(f"Error in run_geopolitical_backtest: {e}")
        import traceback
        return {
            "target_date": target_date,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "signals_generated": 0,
            "signals": [],
            "diagnostics": [],
        }


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
