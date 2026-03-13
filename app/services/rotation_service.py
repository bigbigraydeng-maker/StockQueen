"""
StockQueen V2.3 - Rotation Service
Weekly momentum rotation + daily entry/exit timing for ETFs and mid-cap US stocks.
Uses Alpha Vantage for market data (replaces yfinance).
"""

import logging
import numpy as np
from typing import Optional
from datetime import datetime, date, timedelta

from app.database import get_db
from app.config.rotation_watchlist import (
    RotationConfig,
    OFFENSIVE_ETFS, DEFENSIVE_ETFS, MIDCAP_STOCKS, INVERSE_ETFS,
    get_offensive_tickers, get_defensive_tickers, get_inverse_tickers,
    get_ticker_info,
)
from app.models import (
    RotationScore, RotationSnapshot, RotationPosition, DailyTimingSignal,
)
from app.services.alphavantage_client import get_av_client

logger = logging.getLogger(__name__)
RC = RotationConfig


# ============================================================
# HELPERS — Alpha Vantage data fetch
# ============================================================

async def _fetch_history(ticker: str, days: int = RC.LOOKBACK_DAYS) -> Optional[dict]:
    """
    Fetch OHLCV history via Alpha Vantage.
    Returns dict with 'close', 'volume' numpy arrays and 'dates' index,
    or None on failure.
    """
    try:
        av = get_av_client()
        result = await av.get_history_arrays(ticker, days=days)
        if result is None:
            return None
        # Ensure minimum data length
        if len(result["close"]) < 20:
            return None
        return result
    except Exception as e:
        logger.warning(f"Alpha Vantage fetch failed for {ticker}: {e}")
        return None


def _compute_return(closes: np.ndarray, days: int) -> float:
    """Period return over last N trading days."""
    if len(closes) < days + 1:
        return 0.0
    return float((closes[-1] / closes[-days - 1]) - 1.0)


def _compute_volatility(closes: np.ndarray, period: int = RC.VOL_LOOKBACK) -> float:
    """Annualized volatility over lookback period."""
    if len(closes) < period + 1:
        return 0.0
    daily_returns = np.diff(closes[-period - 1:]) / closes[-period - 1:-1]
    return float(np.std(daily_returns) * np.sqrt(252))


def _compute_ma(closes: np.ndarray, period: int) -> float:
    """Simple moving average of last N closes."""
    if len(closes) < period:
        return 0.0
    return float(np.mean(closes[-period:]))


def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                 period: int = RC.ATR_PERIOD) -> float:
    """Average True Range."""
    if len(closes) < period + 1:
        return 0.0
    tr_list = []
    for i in range(-period, 0):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(h_l, h_pc, l_pc))
    return float(np.mean(tr_list))


# ============================================================
# LOCAL TECHNICAL INDICATORS — for backtest (no API calls)
# ============================================================

def _compute_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Compute RSI locally from close prices. Returns 0-100."""
    if len(closes) < period + 1:
        return 50.0  # neutral default
    deltas = np.diff(closes[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_macd(closes: np.ndarray) -> dict:
    """Compute MACD(12,26,9) locally. Returns {macd, signal, histogram}."""
    if len(closes) < 35:
        return {"macd": 0, "signal": 0, "histogram": 0}
    # EMA helper using exponential weights
    def _ema(data, span):
        alpha = 2.0 / (span + 1)
        result = np.empty_like(data, dtype=float)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    histogram = macd_line - signal_line
    return {
        "macd": float(macd_line[-1]),
        "signal": float(signal_line[-1]),
        "histogram": float(histogram[-1]),
    }


def _compute_bbands(closes: np.ndarray, period: int = 20) -> dict:
    """Compute Bollinger Bands locally. Returns {upper, middle, lower, position}."""
    if len(closes) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "position": 0.5}
    window = closes[-period:]
    middle = float(np.mean(window))
    std = float(np.std(window))
    upper = middle + 2 * std
    lower = middle - 2 * std
    current = float(closes[-1])
    band_width = upper - lower
    position = (current - lower) / band_width if band_width > 0 else 0.5
    return {"upper": upper, "middle": middle, "lower": lower, "position": position}


def _compute_obv_trend(closes: np.ndarray, volumes: np.ndarray) -> str:
    """Compute OBV trend locally. Returns 'rising', 'falling', or 'flat'."""
    if len(closes) < 6 or len(volumes) < 6:
        return "flat"
    # Compute OBV for last 20 data points
    n = min(20, len(closes))
    obv = np.zeros(n)
    for i in range(1, n):
        idx = len(closes) - n + i
        if closes[idx] > closes[idx - 1]:
            obv[i] = obv[i - 1] + volumes[idx]
        elif closes[idx] < closes[idx - 1]:
            obv[i] = obv[i - 1] - volumes[idx]
        else:
            obv[i] = obv[i - 1]
    avg_obv = float(np.mean(obv[-5:]))
    latest_obv = float(obv[-1])
    if avg_obv == 0:
        return "flat"
    pct_diff = (latest_obv - avg_obv) / abs(avg_obv) if avg_obv != 0 else 0
    if pct_diff > 0.02:
        return "rising"
    elif pct_diff < -0.02:
        return "falling"
    return "flat"


def _compute_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                 period: int = 14) -> float:
    """Compute ADX locally. Returns 0-100."""
    n = len(closes)
    if n < period + 1:
        return 0.0
    # True Range, +DM, -DM
    tr_list = []
    plus_dm = []
    minus_dm = []
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(h_l, h_pc, l_pc))
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

    # Smoothed averages (Wilder's smoothing)
    if len(tr_list) < period:
        return 0.0
    atr = float(np.mean(tr_list[-period:]))
    avg_plus_dm = float(np.mean(plus_dm[-period:]))
    avg_minus_dm = float(np.mean(minus_dm[-period:]))

    if atr == 0:
        return 0.0
    plus_di = 100 * avg_plus_dm / atr
    minus_di = 100 * avg_minus_dm / atr
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    dx = 100 * abs(plus_di - minus_di) / di_sum
    return float(dx)


def _evaluate_tech_local(closes: np.ndarray, volumes: np.ndarray,
                         highs: np.ndarray, lows: np.ndarray) -> float:
    """
    Evaluate technical indicators locally and return adjustment score.
    Mirrors signal_service.py's _evaluate_tech_indicators logic.
    Returns value in range [-2.0, +2.0].
    """
    long_score = 0
    short_score = 0

    # RSI
    rsi = _compute_rsi(closes)
    if rsi < 30:
        long_score += 1   # oversold → bullish
    elif rsi > 70:
        short_score += 1  # overbought → bearish

    # MACD
    macd = _compute_macd(closes)
    if macd["histogram"] > 0:
        long_score += 1   # bullish momentum
    elif macd["histogram"] < 0:
        short_score += 1  # bearish momentum

    # Bollinger Bands
    bb = _compute_bbands(closes)
    if bb["position"] < 0.2:
        long_score += 1   # near lower band → oversold
    elif bb["position"] > 0.8:
        short_score += 1  # near upper band → overbought

    # OBV
    obv = _compute_obv_trend(closes, volumes)
    if obv == "rising":
        long_score += 1
    elif obv == "falling":
        short_score += 1

    # ADX (trend strength amplifier)
    adx = _compute_adx(highs, lows, closes)
    if adx > 25:
        # Strong trend — amplify the dominant direction
        if long_score > short_score:
            long_score += 1
        elif short_score > long_score:
            short_score += 1

    # Net score: normalize to [-2, +2]
    # Max possible: long=6,short=0 → net=6 → capped at 2
    # Min possible: long=0,short=6 → net=-6 → capped at -2
    net = long_score - short_score
    return max(-2.0, min(2.0, net * 0.5))


# ============================================================
# 1. WEEKLY ROTATION — score, regime, select top N
# ============================================================

async def run_rotation() -> dict:
    """
    Weekly rotation entry point.
    Steps: detect regime → score universe → select top N → persist snapshot → return result.
    """
    logger.info("=" * 50)
    logger.info("Starting Weekly Rotation")
    logger.info("=" * 50)

    # 1. Detect market regime
    regime = await _detect_regime()
    logger.info(f"Market regime: {regime}")

    # 2. Determine scoring universe based on regime
    if regime == "bear":
        universe = DEFENSIVE_ETFS + INVERSE_ETFS  # 防守 + 做空
    elif regime == "choppy":
        # Choppy: mix of defensive + large-cap ETFs (no mid-cap stocks)
        universe = DEFENSIVE_ETFS + OFFENSIVE_ETFS
    elif regime == "strong_bull":
        # Strong bull: full universe including mid-cap growth
        universe = OFFENSIVE_ETFS + MIDCAP_STOCKS
    else:
        # Normal bull: ETFs + mid-caps
        universe = OFFENSIVE_ETFS + MIDCAP_STOCKS

    # 3. Score all tickers (with RAG + relative strength adjustment)
    from app.services.knowledge_service import get_knowledge_service
    ks = get_knowledge_service()

    # Fetch SPY closes for relative strength calculation
    spy_data = await _fetch_history(RC.REGIME_TICKER, days=RC.LOOKBACK_DAYS)
    spy_closes = spy_data["close"] if spy_data else None

    scores: list[RotationScore] = []
    for item in universe:
        score = await _score_ticker(item, regime, ks, spy_closes=spy_closes)
        if score:
            scores.append(score)

    # Holding inertia: give bonus to already-held tickers to reduce turnover
    current_holdings = await _get_previous_selected()
    if current_holdings:
        for s in scores:
            if s.ticker in current_holdings:
                s.score += RC.HOLDING_BONUS
                logger.info(f"  Holding bonus +{RC.HOLDING_BONUS} for {s.ticker}")

    # Sort descending by score
    scores.sort(key=lambda s: s.score, reverse=True)
    selected = [s.ticker for s in scores[:RC.TOP_N]]

    logger.info(f"Top {RC.TOP_N}: {selected}")
    for s in scores[:10]:
        logger.info(f"  {s.ticker:6s} score={s.score:+.2f}  "
                     f"1w={s.return_1w:+.1%} 1m={s.return_1m:+.1%} 3m={s.return_3m:+.1%}  "
                     f"vol={s.volatility:.1%} MA20={'Y' if s.above_ma20 else 'N'}")

    # 4. Load previous snapshot for comparison
    previous_tickers = await _get_previous_selected()
    added = [t for t in selected if t not in previous_tickers]
    removed = [t for t in previous_tickers if t not in selected]

    # 5. Save snapshot
    spy_data = await _fetch_history(RC.REGIME_TICKER, days=RC.REGIME_MA_PERIOD + 10)
    spy_price = float(spy_data["close"][-1]) if spy_data else 0.0
    spy_ma50 = _compute_ma(spy_data["close"], RC.REGIME_MA_PERIOD) if spy_data else 0.0

    snapshot = RotationSnapshot(
        snapshot_date=date.today().isoformat(),
        regime=regime,
        spy_price=spy_price,
        spy_ma50=spy_ma50,
        scores=[s.model_dump() for s in scores[:20]],
        selected_tickers=selected,
        previous_tickers=previous_tickers,
        changes={"added": added, "removed": removed},
    )
    snapshot_id = await _save_snapshot(snapshot)

    # 6. Manage positions
    await _manage_positions_on_rotation(selected, removed, snapshot_id)

    return {
        "regime": regime,
        "selected": selected,
        "added": added,
        "removed": removed,
        "scores_top10": [s.model_dump() for s in scores[:10]],
        "snapshot_id": snapshot_id,
    }


async def _detect_regime() -> str:
    """
    Detect market regime using multi-signal approach.
    Returns one of: 'strong_bull', 'bull', 'choppy', 'bear'

    Signals:
    1. SPY vs MA50 (trend direction)
    2. SPY vs MA20 (short-term momentum)
    3. 21-day realized volatility (market stress)
    4. SPY 1-month return (momentum confirmation)
    """
    data = await _fetch_history(RC.REGIME_TICKER, days=80)
    if not data:
        logger.warning("Cannot fetch SPY data for regime detection, defaulting to bull")
        return "bull"

    closes = data["close"]
    if len(closes) < 63:
        return "bull"

    ma50 = _compute_ma(closes, 50)
    ma20 = _compute_ma(closes, 20)
    current = float(closes[-1])

    # 21-day realized volatility (annualized)
    vol_arr = np.diff(closes[-22:]) / closes[-22:-1] if len(closes) > 22 else np.array([0])
    vol_21d = float(np.std(vol_arr) * np.sqrt(252))

    # 1-month return
    ret_1m = (current / float(closes[-22])) - 1 if len(closes) > 22 else 0

    # Score-based regime classification
    score = 0

    # Signal 1: SPY vs MA50 (±2 points)
    if current > ma50 * 1.02:
        score += 2  # Clearly above
    elif current > ma50:
        score += 1  # Slightly above
    elif current < ma50 * 0.98:
        score -= 2  # Clearly below
    else:
        score -= 1  # Slightly below

    # Signal 2: SPY vs MA20 (±1 point)
    if current > ma20:
        score += 1
    else:
        score -= 1

    # Signal 3: Volatility (high vol = stress)
    if vol_21d > 0.25:  # > 25% annualized = high stress
        score -= 1
    elif vol_21d < 0.12:  # < 12% = calm market
        score += 1

    # Signal 4: 1-month momentum (±1 point)
    if ret_1m > 0.03:
        score += 1
    elif ret_1m < -0.03:
        score -= 1

    # Map score to regime
    if score >= 4:
        regime = "strong_bull"
    elif score >= 1:
        regime = "bull"
    elif score >= -1:
        regime = "choppy"
    else:
        regime = "bear"

    logger.info(
        f"Regime detection: score={score} → {regime}  "
        f"(SPY={current:.1f}, MA50={ma50:.1f}, MA20={ma20:.1f}, "
        f"vol={vol_21d:.1%}, 1m_ret={ret_1m:+.1%})"
    )
    return regime


async def _score_ticker(item: dict, regime: str, ks=None,
                        spy_closes: Optional[np.ndarray] = None) -> Optional[RotationScore]:
    """
    Compute multi-factor score for a single ticker via unified MultiFactorScorer.
    Fetches OHLCV + fundamental/earnings/cashflow/sentiment data from knowledge base.
    """
    from app.services.multi_factor_scorer import compute_multi_factor_score

    ticker = item["ticker"]
    data = await _fetch_history(ticker)
    if not data:
        return None

    closes = data["close"]
    volumes = data["volume"]
    highs = data["high"]
    lows = data["low"]

    # Fetch fundamental data from knowledge base
    overview = None
    earnings_data = None
    cashflow_data = None
    sentiment_value = None
    sector_returns = None

    if ks:
        try:
            factor_data = await ks.get_factor_data_for_scorer(ticker)
            overview = factor_data.get("overview")
            earnings_data = factor_data.get("earnings_data")
            cashflow_data = factor_data.get("cashflow_data")
            sentiment_value = factor_data.get("sentiment_value")
            sector_returns = factor_data.get("sector_returns")
        except Exception:
            pass

    # Unified multi-factor scoring
    result = compute_multi_factor_score(
        closes=closes,
        volumes=volumes,
        highs=highs,
        lows=lows,
        spy_closes=spy_closes,
        regime=regime,
        overview=overview,
        earnings_data=earnings_data,
        cashflow_data=cashflow_data,
        sentiment_value=sentiment_value,
        sector_returns=sector_returns,
        ticker_sector=item.get("sector", ""),
    )

    score = result["total_score"]
    factors = result["factors"]

    # Extract components from MultiFactorScorer output
    mom = factors.get("momentum", {})
    trend = factors.get("trend", {})

    # Determine asset type
    t_set = {e["ticker"] for e in OFFENSIVE_ETFS}
    d_set = {e["ticker"] for e in DEFENSIVE_ETFS}
    i_set = {e["ticker"] for e in INVERSE_ETFS}
    if ticker in t_set:
        asset_type = "etf_offensive"
    elif ticker in d_set:
        asset_type = "etf_defensive"
    elif ticker in i_set:
        asset_type = "inverse_etf"
    else:
        asset_type = "stock"

    return RotationScore(
        ticker=ticker,
        name=item.get("name", ""),
        asset_type=asset_type,
        sector=item.get("sector", ""),
        return_1w=mom.get("ret_1w", 0),
        return_1m=mom.get("ret_1m", 0),
        return_3m=mom.get("ret_3m", 0),
        volatility=mom.get("vol", 0),
        above_ma20=trend.get("above_ma20", False),
        score=score,
        current_price=float(closes[-1]),
    )


# ============================================================
# 2. DAILY ENTRY CHECK
# ============================================================

async def run_daily_entry_check() -> list[DailyTimingSignal]:
    """
    Daily entry confirmation for pending_entry positions.
    Conditions: close > MA5 AND volume > 20-day avg.
    """
    logger.info("Starting Daily Entry Check")
    signals: list[DailyTimingSignal] = []

    positions = await _get_positions_by_status("pending_entry")
    if not positions:
        logger.info("No pending_entry positions")
        return signals

    for pos in positions:
        ticker = pos["ticker"]
        data = await _fetch_history(ticker, days=30)
        if not data:
            continue

        closes = data["close"]
        volumes = data["volume"]
        highs = data["high"]
        lows = data["low"]

        ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
        avg_vol = float(np.mean(volumes[-RC.ENTRY_VOL_PERIOD:])) if len(volumes) >= RC.ENTRY_VOL_PERIOD else 0

        current_price = float(closes[-1])
        current_vol = float(volumes[-1])

        conditions = []
        above_ma5 = current_price > ma5
        vol_ok = current_vol > avg_vol if avg_vol > 0 else False

        if above_ma5:
            conditions.append(f"close ${current_price:.2f} > MA5 ${ma5:.2f}")
        if vol_ok:
            conditions.append(f"vol {current_vol/1e6:.1f}M > avg {avg_vol/1e6:.1f}M")

        if above_ma5 and vol_ok:
            # Entry confirmed — compute ATR stop/target
            atr = _compute_atr(highs, lows, closes)
            stop_loss = current_price - RC.ATR_STOP_MULTIPLIER * atr
            take_profit = current_price + RC.ATR_TARGET_MULTIPLIER * atr

            signal = DailyTimingSignal(
                ticker=ticker,
                signal_type="entry",
                trigger_conditions=conditions,
                current_price=current_price,
                entry_price=current_price,
                stop_loss=round(stop_loss, 2),
                take_profit=round(take_profit, 2),
            )
            signals.append(signal)

            # Update position to active
            await _activate_position(
                pos["id"], current_price, atr, stop_loss, take_profit
            )
            logger.info(f"ENTRY confirmed: {ticker} @ ${current_price:.2f} "
                         f"SL=${stop_loss:.2f} TP=${take_profit:.2f}")
        else:
            # Check if max wait exceeded
            created = pos.get("created_at", "")
            if _days_since(created) >= RC.ENTRY_MAX_WAIT_DAYS:
                await _close_position(pos["id"], reason="entry_timeout")
                logger.info(f"Entry timeout for {ticker}, closing position")

    return signals


# ============================================================
# 3. DAILY EXIT CHECK
# ============================================================

async def run_daily_exit_check() -> list[DailyTimingSignal]:
    """
    Daily exit check for active positions.
    - ATR stop loss: close < entry - 2*ATR
    - ATR take profit: close > entry + 3*ATR
    - Rotation exit: kicked from top N AND close < MA5
    """
    logger.info("Starting Daily Exit Check")
    signals: list[DailyTimingSignal] = []

    positions = await _get_positions_by_status("active")
    if not positions:
        logger.info("No active positions")
        return signals

    # Get current top N for rotation exit check
    current_selected = await _get_latest_selected()

    for pos in positions:
        ticker = pos["ticker"]
        entry_price = float(pos.get("entry_price", 0))
        stop_loss = float(pos.get("stop_loss", 0))
        take_profit = float(pos.get("take_profit", 0))

        data = await _fetch_history(ticker, days=30)
        if not data:
            continue

        closes = data["close"]
        current_price = float(closes[-1])

        # Update current price
        pnl_pct = (current_price / entry_price - 1.0) if entry_price > 0 else 0.0
        await _update_position_price(pos["id"], current_price, pnl_pct)

        exit_reason = None
        conditions = []

        # Check stop loss
        if stop_loss > 0 and current_price < stop_loss:
            exit_reason = "stop_loss"
            conditions.append(f"close ${current_price:.2f} < SL ${stop_loss:.2f}")

        # Check take profit
        elif take_profit > 0 and current_price > take_profit:
            exit_reason = "take_profit"
            conditions.append(f"close ${current_price:.2f} > TP ${take_profit:.2f}")

        # Check rotation exit: not in top N AND below MA5
        elif ticker not in current_selected:
            ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
            if current_price < ma5:
                exit_reason = "rotation_exit"
                conditions.append(f"not in top {RC.TOP_N}")
                conditions.append(f"close ${current_price:.2f} < MA5 ${ma5:.2f}")

        if exit_reason:
            signal = DailyTimingSignal(
                ticker=ticker,
                signal_type="exit",
                trigger_conditions=conditions,
                current_price=current_price,
                entry_price=entry_price,
                exit_reason=exit_reason,
            )
            signals.append(signal)

            await _close_position(pos["id"], reason=exit_reason,
                                  exit_price=current_price)
            logger.info(f"EXIT {exit_reason}: {ticker} @ ${current_price:.2f} "
                         f"(entry ${entry_price:.2f}, pnl {pnl_pct:+.1%})")

    return signals


# ============================================================
# 4. BACKTEST
# ============================================================

def _compute_relative_strength(ticker_closes: np.ndarray, spy_closes: np.ndarray,
                                period: int = 21) -> float:
    """
    Compute relative strength vs SPY over period.
    RS > 0 means outperforming SPY, RS < 0 means underperforming.
    """
    if len(ticker_closes) < period + 1 or len(spy_closes) < period + 1:
        return 0.0
    ticker_ret = (ticker_closes[-1] / ticker_closes[-period - 1]) - 1
    spy_ret = (spy_closes[-1] / spy_closes[-period - 1]) - 1
    return float(ticker_ret - spy_ret)


def _graduated_trend_bonus(closes: np.ndarray) -> float:
    """
    Graduated trend bonus based on price position relative to multiple MAs.
    Returns 0 ~ 3.0 (replaces binary MA20 bonus of 2.0).
    - Above MA10: +0.5
    - Above MA20: +1.0
    - Above MA50: +1.0
    - MA20 sloping up: +0.5
    """
    if len(closes) < 50:
        return 0.0
    bonus = 0.0
    current = float(closes[-1])
    ma10 = float(np.mean(closes[-10:]))
    ma20 = float(np.mean(closes[-20:]))
    ma50 = float(np.mean(closes[-50:]))

    if current > ma10:
        bonus += 0.5
    if current > ma20:
        bonus += 1.0
    if current > ma50:
        bonus += 1.0
    # MA20 slope: compare current MA20 vs 5 days ago MA20
    if len(closes) >= 25:
        ma20_prev = float(np.mean(closes[-25:-5]))
        if ma20 > ma20_prev:
            bonus += 0.5
    return bonus


def _apply_sector_cap(scored: list[tuple], histories: dict,
                      max_per_sector: int = RC.MAX_SECTOR_CONCENTRATION,
                      top_n: int = RC.TOP_N) -> list[str]:
    """
    Select top_n tickers with sector concentration limit.
    Returns list of selected tickers.
    """
    selected = []
    sector_count = {}
    for ticker, score in scored:
        item = histories.get(ticker, {}).get("item", {})
        sector = item.get("sector", item.get("asset_type", "etf"))
        if not sector:
            sector = "etf"
        count = sector_count.get(sector, 0)
        if count >= max_per_sector:
            continue
        selected.append(ticker)
        sector_count[sector] = count + 1
        if len(selected) >= top_n:
            break
    return selected


def _score_weighted_returns(selected: list, scores_map: dict,
                            histories: dict, i: int, step: int) -> float:
    """
    Compute score-weighted portfolio return (instead of equal weight).
    Higher scored tickers get proportionally larger allocation.
    """
    weights = []
    returns = []
    for t in selected:
        h = histories.get(t)
        if h is None or i + step >= len(h["close"]):
            continue
        week_ret = (h["close"][i + step] / h["close"][i]) - 1
        raw_score = max(scores_map.get(t, 0), 0.01)  # floor to avoid negative weights
        weights.append(raw_score)
        returns.append(week_ret)

    if not weights:
        return 0.0

    total_w = sum(weights)
    if total_w <= 0:
        # fallback to equal weight
        return sum(returns) / len(returns) if returns else 0.0

    return sum(w / total_w * r for w, r in zip(weights, returns))


async def _fetch_backtest_data(start_date: str, end_date: str) -> dict:
    """
    Fetch all OHLCV + fundamental data needed for backtesting.
    Returns {'histories': {...}, 'bt_fundamentals': {...}} or {'error': '...'}.
    Call once and pass to run_rotation_backtest() to avoid repeated API calls.

    Uses the AV client's built-in 1-hour cache: first call is slow (~3-4min),
    subsequent calls within 1 hour are nearly instant.
    """
    import time as _time
    t0 = _time.time()

    av = get_av_client()
    all_items = OFFENSIVE_ETFS + MIDCAP_STOCKS + DEFENSIVE_ETFS + INVERSE_ETFS
    histories = {}
    fetched = 0
    failed = 0
    for item in all_items:
        ticker = item["ticker"]
        try:
            hist = await av.get_daily_history_range(ticker, start_date, end_date)
            if hist is not None and not hist.empty and len(hist) > 20:
                histories[ticker] = {
                    "close": hist["Close"].values,
                    "volume": hist["Volume"].values,
                    "high": hist["High"].values,
                    "low": hist["Low"].values,
                    "dates": hist.index,
                    "item": item,
                }
                fetched += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.debug(f"Failed to fetch {ticker}: {e}")

        # Progress logging every 20 tickers
        total_done = fetched + failed
        if total_done % 20 == 0:
            logger.info(f"OHLCV progress: {total_done}/{len(all_items)} "
                        f"(OK: {fetched}, failed: {failed})")

    t1 = _time.time()
    logger.info(f"OHLCV fetch complete in {t1 - t0:.1f}s: "
                f"{fetched}/{len(all_items)} tickers OK, {failed} failed")

    if not histories:
        return {"error": f"No data fetched (tried {len(all_items)} tickers, all failed). "
                         f"Check Alpha Vantage API key and rate limits."}
    if "SPY" not in histories:
        return {"error": "SPY data not available — cannot compute benchmark"}

    # ── Fetch fundamentals for midcap stocks ──
    # Ensures backtest scoring is consistent with real-time scoring (9 factors)
    bt_fundamentals = {}
    midcap_tickers = [s["ticker"] for s in MIDCAP_STOCKS if s["ticker"] in histories]
    fund_count = 0

    for ticker in midcap_tickers:
        fund = {}
        try:
            earnings = await av.get_earnings(ticker)
            if earnings and earnings.get("quarterly"):
                fund["earnings_data"] = earnings
            cashflow = await av.get_cash_flow(ticker)
            if cashflow and cashflow.get("quarterly"):
                fund["cashflow_data"] = cashflow
            overview = await av.get_company_overview(ticker)
            if overview:
                fund["overview"] = overview
            if fund:
                bt_fundamentals[ticker] = fund
                fund_count += 1
        except Exception:
            pass
        # Progress logging every 15 tickers
        done = midcap_tickers.index(ticker) + 1
        if done % 15 == 0:
            logger.info(f"Fundamental progress: {done}/{len(midcap_tickers)} tickers "
                        f"({fund_count} with data)")

    t2 = _time.time()
    logger.info(f"Fundamental fetch complete in {t2 - t1:.1f}s: "
                f"{fund_count}/{len(midcap_tickers)} tickers with data")

    logger.info(f"Pre-fetched data: {len(histories)} tickers, {len(bt_fundamentals)} fundamentals")

    return {"histories": histories, "bt_fundamentals": bt_fundamentals}


async def run_rotation_backtest(
    start_date: str = "2023-01-01",
    end_date: str = "2026-03-01",
    top_n: int = RC.TOP_N,
    holding_bonus: float = RC.HOLDING_BONUS,
    _prefetched: dict = None,
) -> dict:
    """
    Historical backtest of the rotation strategy with alpha enhancements.
    Pass _prefetched (from _fetch_backtest_data) to skip redundant API calls.
    """
    logger.info(f"Running rotation backtest: {start_date} to {end_date}, top {top_n}")

    # Use pre-fetched data or fetch fresh
    if _prefetched and "histories" in _prefetched:
        histories = _prefetched["histories"]
        bt_fundamentals = _prefetched.get("bt_fundamentals", {})
    else:
        data = await _fetch_backtest_data(start_date, end_date)
        if "error" in data:
            return data
        histories = data["histories"]
        bt_fundamentals = data["bt_fundamentals"]

    if not histories:
        return {"error": "No data fetched"}

    # Use SPY + QQQ as benchmarks
    spy_hist = histories.get("SPY")
    if not spy_hist:
        return {"error": "SPY data not available"}
    qqq_hist = histories.get("QQQ")  # Nasdaq benchmark (may be None)

    # Pre-compute sets for regime filtering
    defensive_set = {e["ticker"] for e in DEFENSIVE_ETFS}
    inverse_set = {e["ticker"] for e in INVERSE_ETFS}
    offensive_set = {e["ticker"] for e in OFFENSIVE_ETFS}

    # Simulate week by week
    spy_dates = spy_hist["dates"]
    weekly_returns = []
    spy_weekly_returns = []
    qqq_weekly_returns = []
    holdings = []
    equity_curve = []
    trade_log = []
    weekly_details = []
    cum_port_val = 1.0
    cum_spy_val = 1.0
    cum_qqq_val = 1.0
    prev_selected = []

    # ATR stop-loss tracking: {ticker: stop_price}
    active_stops = {}
    stop_triggered_count = 0

    # Walk through time in weekly steps
    step = 5  # ~1 trading week
    for i in range(63, len(spy_dates) - step, step):
        # ── Regime detection ──
        spy_closes_so_far = spy_hist["close"][:i + 1]
        ma50_bt = float(np.mean(spy_closes_so_far[-50:])) if len(spy_closes_so_far) >= 50 else 0
        ma20_bt = float(np.mean(spy_closes_so_far[-20:])) if len(spy_closes_so_far) >= 20 else 0
        spy_cur = float(spy_closes_so_far[-1])

        vol_arr_bt = np.diff(spy_closes_so_far[-22:]) / spy_closes_so_far[-22:-1] if len(spy_closes_so_far) > 22 else np.array([0])
        vol_bt = float(np.std(vol_arr_bt) * np.sqrt(252))
        ret_1m_bt = (spy_cur / float(spy_closes_so_far[-22])) - 1 if len(spy_closes_so_far) > 22 else 0

        rscore = 0
        if spy_cur > ma50_bt * 1.02: rscore += 2
        elif spy_cur > ma50_bt: rscore += 1
        elif spy_cur < ma50_bt * 0.98: rscore -= 2
        else: rscore -= 1
        if spy_cur > ma20_bt: rscore += 1
        else: rscore -= 1
        if vol_bt > 0.25: rscore -= 1
        elif vol_bt < 0.12: rscore += 1
        if ret_1m_bt > 0.03: rscore += 1
        elif ret_1m_bt < -0.03: rscore -= 1

        if rscore >= 4: regime = "strong_bull"
        elif rscore >= 1: regime = "bull"
        elif rscore >= -1: regime = "choppy"
        else: regime = "bear"

        # ── Score tickers via unified MultiFactorScorer ──
        from app.services.multi_factor_scorer import compute_multi_factor_score

        scored = []
        scores_map = {}
        spy_closes_for_rs = spy_hist["close"][:i + 1]

        # as_of_date for fundamental data (prevent lookahead bias)
        bt_date = str(spy_dates[i].date()) if hasattr(spy_dates[i], "date") else str(spy_dates[i])[:10]

        for ticker, h in histories.items():
            if i >= len(h["close"]):
                continue
            closes = h["close"][:i + 1]
            if len(closes) < 63:
                continue

            volumes = h["volume"][:i + 1]
            highs = h["high"][:i + 1]
            lows = h["low"][:i + 1]

            # Get pre-fetched fundamental data for this ticker (if available)
            overview_bt = bt_fundamentals.get(ticker, {}).get("overview")
            earnings_bt = bt_fundamentals.get(ticker, {}).get("earnings_data")
            cashflow_bt = bt_fundamentals.get(ticker, {}).get("cashflow_data")

            # Unified multi-factor score
            result = compute_multi_factor_score(
                closes=closes,
                volumes=volumes,
                highs=highs,
                lows=lows,
                spy_closes=spy_closes_for_rs,
                regime=regime,
                overview=overview_bt,
                earnings_data=earnings_bt,
                cashflow_data=cashflow_bt,
                sentiment_value=None,  # no historical sentiment
                sector_returns=None,   # no historical sector data
                ticker_sector=h["item"].get("sector", ""),
                as_of_date=bt_date,
            )

            score = result["total_score"]

            # ── Relative strength filter ──
            is_defensive = ticker in defensive_set
            is_inverse = ticker in inverse_set
            is_etf = ticker in offensive_set
            is_midcap = not is_defensive and not is_etf and not is_inverse

            if RC.RELATIVE_STRENGTH_FILTER and not is_defensive and not is_inverse:
                rs = _compute_relative_strength(closes, spy_closes_for_rs, period=21)
                if rs < -0.02:  # underperforming SPY by >2% → skip
                    continue

            # Regime filter
            if regime == "bear" and not is_defensive and not is_inverse:
                continue
            elif regime == "choppy" and (is_midcap or is_inverse):
                continue
            elif regime in ("bull", "strong_bull") and (is_defensive or is_inverse):
                continue

            scored.append((ticker, score))
            scores_map[ticker] = score

        # Holding inertia
        if holding_bonus > 0 and prev_selected:
            scored = [(t, sc + holding_bonus) if t in prev_selected else (t, sc)
                      for t, sc in scored]
            for t, sc in scored:
                scores_map[t] = sc

        scored.sort(key=lambda x: x[1], reverse=True)

        # ── Sector concentration cap ──
        if RC.MAX_SECTOR_CONCENTRATION > 0:
            selected = _apply_sector_cap(scored, histories,
                                         max_per_sector=RC.MAX_SECTOR_CONCENTRATION,
                                         top_n=top_n)
        else:
            selected = [t for t, _ in scored[:top_n]]

        holdings.append(selected)

        # 记录换仓
        added = [t for t in selected if t not in prev_selected]
        removed = [t for t in prev_selected if t not in selected]
        week_date = str(spy_dates[i].date()) if hasattr(spy_dates[i], "date") else str(spy_dates[i])[:10]
        trade_log.append({
            "date": week_date,
            "regime": regime,
            "holdings": selected,
            "added": added,
            "removed": removed,
        })

        # ── ATR stop-loss simulation ──
        # Set stops for newly added tickers
        if RC.BACKTEST_STOP_LOSS:
            for t in added:
                h = histories.get(t)
                if h and i < len(h["close"]) and i < len(h["high"]) and i < len(h["low"]):
                    closes_t = h["close"][:i + 1]
                    highs_t = h["high"][:i + 1]
                    lows_t = h["low"][:i + 1]
                    atr = _compute_atr(highs_t, lows_t, closes_t)
                    entry_px = float(closes_t[-1])
                    active_stops[t] = entry_px - RC.BACKTEST_STOP_MULT * atr
            # Remove stops for removed tickers
            for t in removed:
                active_stops.pop(t, None)

        prev_selected = selected[:]

        # ── Compute portfolio return for next week ──
        if RC.SCORE_WEIGHTED_ALLOC:
            port_ret = _score_weighted_returns(selected, scores_map, histories, i, step)
        else:
            port_ret = 0.0
            valid = 0
            for t in selected:
                h = histories.get(t)
                if h is None or i + step >= len(h["close"]):
                    continue
                week_ret = (h["close"][i + step] / h["close"][i]) - 1
                port_ret += week_ret
                valid += 1
            if valid > 0:
                port_ret /= valid

        # ── ATR stop-loss check within the week ──
        if RC.BACKTEST_STOP_LOSS:
            for t in list(selected):
                h = histories.get(t)
                if h is None:
                    continue
                stop_px = active_stops.get(t)
                if stop_px is None:
                    continue
                # Check daily lows within the week for stop trigger
                for d in range(i + 1, min(i + step + 1, len(h["low"]))):
                    if h["low"][d] < stop_px:
                        # Stop triggered — cap loss at stop level
                        actual_loss = (stop_px / h["close"][i]) - 1
                        normal_ret = (h["close"][min(i + step, len(h["close"]) - 1)] / h["close"][i]) - 1

                        if normal_ret < actual_loss:
                            # Stop saved us from worse loss
                            weight = scores_map.get(t, 1.0) if RC.SCORE_WEIGHTED_ALLOC else 1.0
                            total_w = sum(max(scores_map.get(s, 1.0), 0.01) for s in selected) if RC.SCORE_WEIGHTED_ALLOC else len(selected)
                            w_frac = max(weight, 0.01) / total_w if total_w > 0 else 1.0 / len(selected)
                            port_ret += (actual_loss - normal_ret) * w_frac
                            stop_triggered_count += 1

                        active_stops.pop(t, None)
                        break

        spy_ret = (spy_hist["close"][i + step] / spy_hist["close"][i]) - 1
        qqq_ret = 0.0
        if qqq_hist and i + step < len(qqq_hist["close"]):
            qqq_ret = (qqq_hist["close"][i + step] / qqq_hist["close"][i]) - 1
        weekly_returns.append(port_ret)
        spy_weekly_returns.append(spy_ret)
        qqq_weekly_returns.append(qqq_ret)

        # 累计净值
        cum_port_val *= (1 + port_ret)
        cum_spy_val *= (1 + spy_ret)
        cum_qqq_val *= (1 + qqq_ret)
        equity_curve.append({
            "date": week_date,
            "portfolio": round(cum_port_val, 4),
            "spy": round(cum_spy_val, 4),
            "qqq": round(cum_qqq_val, 4),
        })
        weekly_details.append({
            "date": week_date,
            "regime": regime,
            "holdings": selected,
            "return_pct": round(port_ret * 100, 2),
            "spy_return_pct": round(spy_ret * 100, 2),
            "qqq_return_pct": round(qqq_ret * 100, 2),
            "cum_return": round((cum_port_val - 1) * 100, 2),
            "spy_cum_return": round((cum_spy_val - 1) * 100, 2),
            "qqq_cum_return": round((cum_qqq_val - 1) * 100, 2),
        })

    if not weekly_returns:
        return {"error": "Insufficient data for backtest"}

    # Compute cumulative returns
    cum_port = float(np.prod([1 + r for r in weekly_returns]) - 1)
    cum_spy = float(np.prod([1 + r for r in spy_weekly_returns]) - 1)
    cum_qqq = float(np.prod([1 + r for r in qqq_weekly_returns]) - 1)
    ann_ret = float((1 + cum_port) ** (52 / len(weekly_returns)) - 1) if weekly_returns else 0
    ann_vol = float(np.std(weekly_returns) * np.sqrt(52))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    max_dd = _max_drawdown(weekly_returns)

    win_weeks = sum(1 for r in weekly_returns if r > 0)
    win_rate = win_weeks / len(weekly_returns) if weekly_returns else 0

    # Alpha enhancement stats
    alpha_enhancements = {
        "relative_strength_filter": RC.RELATIVE_STRENGTH_FILTER,
        "score_weighted_alloc": RC.SCORE_WEIGHTED_ALLOC,
        "sector_concentration_cap": RC.MAX_SECTOR_CONCENTRATION,
        "graduated_trend_bonus": RC.GRADUATED_TREND_BONUS,
        "stop_loss_simulation": RC.BACKTEST_STOP_LOSS,
        "dynamic_momentum_weights": True,
        "stop_triggered_count": stop_triggered_count,
    }

    return {
        "period": f"{start_date} to {end_date}",
        "weeks": len(weekly_returns),
        "top_n": top_n,
        "cumulative_return": round(cum_port, 4),
        "spy_cumulative_return": round(cum_spy, 4),
        "qqq_cumulative_return": round(cum_qqq, 4),
        "annualized_return": round(ann_ret, 4),
        "annualized_vol": round(ann_vol, 4),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "alpha_vs_spy": round(cum_port - cum_spy, 4),
        "alpha_vs_qqq": round(cum_port - cum_qqq, 4),
        "equity_curve": equity_curve,
        "trades": trade_log,
        "weekly_details": weekly_details,
        "alpha_enhancements": alpha_enhancements,
    }


async def run_parameter_optimization(
    start_date: str = "2023-01-01",
    end_date: str = "2026-03-01",
) -> dict:
    """
    Grid search over top_n × holding_bonus to find optimal parameter combination.
    Returns sorted results matrix with best combo highlighted.
    """
    logger.info(f"Starting parameter optimization: {start_date} to {end_date}")

    # Fetch data ONCE, share across all 24 parameter combos
    prefetched = await _fetch_backtest_data(start_date, end_date)
    if "error" in prefetched:
        return prefetched

    top_n_values = [2, 3, 4, 5]
    bonus_values = [0, 0.5, 1.0, 1.5, 2.0, 2.5]

    results = []
    best_sharpe = -999
    best_combo = {}

    for tn in top_n_values:
        for hb in bonus_values:
            try:
                bt = await run_rotation_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    top_n=tn,
                    holding_bonus=hb,
                    _prefetched=prefetched,
                )
                if "error" in bt:
                    continue

                entry = {
                    "top_n": tn,
                    "holding_bonus": hb,
                    "sharpe_ratio": bt["sharpe_ratio"],
                    "annualized_return": bt["annualized_return"],
                    "max_drawdown": bt["max_drawdown"],
                    "win_rate": bt["win_rate"],
                    "alpha_vs_spy": bt["alpha_vs_spy"],
                    "cumulative_return": bt["cumulative_return"],
                }
                results.append(entry)

                if bt["sharpe_ratio"] > best_sharpe:
                    best_sharpe = bt["sharpe_ratio"]
                    best_combo = entry

            except Exception as e:
                logger.warning(f"Optimization failed for top_n={tn}, bonus={hb}: {e}")

    # Sort by Sharpe ratio descending
    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

    logger.info(f"Optimization complete: {len(results)} combos tested, "
                f"best Sharpe={best_sharpe:.2f} with top_n={best_combo.get('top_n')}, "
                f"bonus={best_combo.get('holding_bonus')}")

    return {
        "period": f"{start_date} to {end_date}",
        "total_combos": len(results),
        "best": best_combo,
        "results": results,
        "top_n_values": top_n_values,
        "bonus_values": bonus_values,
    }


async def run_adaptive_backtest(
    start_date: str = "2023-01-01",
    end_date: str = "2026-03-01",
) -> dict:
    """
    Walk-Forward Optimization: 月度自适应最优组合分析。
    1) 对24种参数组合各跑一次完整回测
    2) 按月切片，用前3个月训练窗口选最优参数
    3) 拼接自适应权益曲线，对比固定最优和SPY
    """
    from collections import defaultdict
    import math

    logger.info(f"Starting adaptive backtest: {start_date} to {end_date}")

    # Fetch data ONCE, share across all 24 parameter combos
    prefetched = await _fetch_backtest_data(start_date, end_date)
    if "error" in prefetched:
        return prefetched
    logger.info("Adaptive: data pre-fetched, running 24 parameter combos...")

    top_n_values = [2, 3, 4, 5]
    bonus_values = [0, 0.5, 1.0, 1.5, 2.0, 2.5]

    # ── Step 1: Run 24 full backtests (reusing pre-fetched data) ──
    all_results = {}  # (top_n, hb) -> backtest result dict
    total_combos = len(top_n_values) * len(bonus_values)
    combo_count = 0
    import time as _time
    step1_start = _time.time()
    for tn in top_n_values:
        for hb in bonus_values:
            combo_count += 1
            try:
                bt = await run_rotation_backtest(
                    start_date=start_date,
                    end_date=end_date,
                    top_n=tn,
                    holding_bonus=hb,
                    _prefetched=prefetched,
                )
                if "error" not in bt:
                    all_results[(tn, hb)] = bt
                    logger.info(f"Adaptive [{combo_count}/{total_combos}]: "
                                f"combo ({tn},{hb}) done — "
                                f"sharpe={bt['sharpe_ratio']}, cum={bt['cumulative_return']:.2%}")
                else:
                    logger.warning(f"Adaptive [{combo_count}/{total_combos}]: "
                                   f"combo ({tn},{hb}) returned error: {bt.get('error')}")
            except Exception as e:
                logger.warning(f"Adaptive [{combo_count}/{total_combos}]: "
                               f"combo ({tn},{hb}) failed: {e}")
    step1_elapsed = _time.time() - step1_start
    logger.info(f"Adaptive Step 1 complete: {len(all_results)}/{total_combos} combos OK "
                f"in {step1_elapsed:.1f}s")

    if not all_results:
        return {"error": "所有参数组合回测均失败"}

    # ── Step 2: Slice weekly_details by month ──
    # monthly_data[(tn,hb)][YYYY-MM] = list of weekly dicts
    monthly_data = defaultdict(lambda: defaultdict(list))
    for combo, bt in all_results.items():
        for wd in bt["weekly_details"]:
            month_key = wd["date"][:7]  # "YYYY-MM"
            monthly_data[combo][month_key].append(wd)

    # Get sorted list of all months
    all_months = sorted(set(
        m for combo_months in monthly_data.values() for m in combo_months
    ))

    if len(all_months) < 4:
        return {"error": "数据不足4个月，无法进行Walk-Forward分析"}

    # ── Helper: compute compound return from weekly returns ──
    def _compound_return(weekly_dicts: list) -> float:
        cum = 1.0
        for wd in weekly_dicts:
            cum *= (1 + wd["return_pct"] / 100.0)
        return cum - 1.0

    def _compound_spy_return(weekly_dicts: list) -> float:
        cum = 1.0
        for wd in weekly_dicts:
            cum *= (1 + wd["spy_return_pct"] / 100.0)
        return cum - 1.0

    def _compound_qqq_return(weekly_dicts: list) -> float:
        cum = 1.0
        for wd in weekly_dicts:
            cum *= (1 + wd.get("qqq_return_pct", 0.0) / 100.0)
        return cum - 1.0

    # ── Step 3: Monthly returns matrix ──
    # monthly_returns[(tn,hb)][YYYY-MM] = compound return
    monthly_returns = {}
    for combo in all_results:
        monthly_returns[combo] = {}
        for month in all_months:
            weeks = monthly_data[combo].get(month, [])
            monthly_returns[combo][month] = _compound_return(weeks) if weeks else 0.0

    # ── Step 4: Walk-Forward selection ──
    training_window = 3  # months
    monthly_report = []
    adaptive_weekly = []       # stitched weekly_details for adaptive
    adaptive_returns = []      # weekly return floats
    spy_returns_adaptive = []  # SPY weekly returns for the same weeks

    for i in range(training_window, len(all_months)):
        current_month = all_months[i]
        train_months = all_months[i - training_window: i]

        # Find best combo during training window
        best_combo = None
        best_train_return = -999
        for combo in all_results:
            train_cum = 1.0
            for tm in train_months:
                train_cum *= (1 + monthly_returns[combo].get(tm, 0.0))
            train_ret = train_cum - 1.0
            if train_ret > best_train_return:
                best_train_return = train_ret
                best_combo = combo

        if best_combo is None:
            continue

        # Get this month's data from the selected combo
        month_weeks = monthly_data[best_combo].get(current_month, [])
        if not month_weeks:
            continue

        monthly_ret = _compound_return(month_weeks)
        spy_monthly_ret = _compound_spy_return(month_weeks)
        qqq_monthly_ret = _compound_qqq_return(month_weeks)

        # Get dominant regime for the month
        regime_counts = defaultdict(int)
        for wd in month_weeks:
            regime_counts[wd.get("regime", "unknown")] += 1
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"

        # Get top holdings (most frequently held during the month)
        holding_counts = defaultdict(int)
        for wd in month_weeks:
            for h in wd.get("holdings", []):
                holding_counts[h] += 1
        top_holdings = sorted(holding_counts, key=holding_counts.get, reverse=True)[:5]

        monthly_report.append({
            "month": current_month,
            "selected_top_n": best_combo[0],
            "selected_holding_bonus": best_combo[1],
            "training_window": f"{train_months[0]} ~ {train_months[-1]}",
            "training_return": round(best_train_return * 100, 2),
            "regime": dominant_regime,
            "monthly_return": round(monthly_ret * 100, 2),
            "spy_monthly_return": round(spy_monthly_ret * 100, 2),
            "qqq_monthly_return": round(qqq_monthly_ret * 100, 2),
            "alpha": round((monthly_ret - spy_monthly_ret) * 100, 2),
            "top_holdings": top_holdings,
        })

        # Collect weekly data for equity curve
        for wd in month_weeks:
            adaptive_weekly.append(wd)
            adaptive_returns.append(wd["return_pct"] / 100.0)
            spy_returns_adaptive.append(wd["spy_return_pct"] / 100.0)

    # ── Step 5: Find fixed best combo (全周期最优) ──
    best_fixed_combo = max(all_results, key=lambda c: all_results[c]["sharpe_ratio"])
    fixed_best_bt = all_results[best_fixed_combo]

    # ── Step 6: Build equity curves ──
    equity_curve = []
    cum_adaptive = 1.0
    cum_spy = 1.0
    cum_qqq = 1.0

    # Also build fixed_best weekly returns aligned with adaptive weeks
    fixed_best_weekly = {wd["date"]: wd for wd in fixed_best_bt["weekly_details"]}
    cum_fixed = 1.0

    for wd in adaptive_weekly:
        date_str = wd["date"]
        cum_adaptive *= (1 + wd["return_pct"] / 100.0)
        cum_spy *= (1 + wd["spy_return_pct"] / 100.0)
        cum_qqq *= (1 + wd.get("qqq_return_pct", 0.0) / 100.0)

        fb_wd = fixed_best_weekly.get(date_str)
        if fb_wd:
            cum_fixed *= (1 + fb_wd["return_pct"] / 100.0)

        equity_curve.append({
            "date": date_str,
            "adaptive": round(cum_adaptive, 4),
            "fixed_best": round(cum_fixed, 4),
            "spy": round(cum_spy, 4),
            "qqq": round(cum_qqq, 4),
        })

    # ── Step 7: Compute statistics for all three ──
    def _compute_stats(weekly_rets, spy_rets):
        if not weekly_rets:
            return {}
        cum = float(np.prod([1 + r for r in weekly_rets]) - 1)
        cum_spy = float(np.prod([1 + r for r in spy_rets]) - 1)
        n = len(weekly_rets)
        ann_ret = float((1 + cum) ** (52 / n) - 1) if n > 0 else 0
        ann_vol = float(np.std(weekly_rets) * np.sqrt(52))
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        max_dd = _max_drawdown(weekly_rets)
        win = sum(1 for r in weekly_rets if r > 0) / n if n else 0
        return {
            "cumulative_return": round(cum, 4),
            "annualized_return": round(ann_ret, 4),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 4),
            "win_rate": round(win, 4),
            "alpha_vs_spy": round(cum - cum_spy, 4),
            "weeks": n,
        }

    # Fixed best returns for the same period
    adaptive_start = adaptive_weekly[0]["date"] if adaptive_weekly else start_date
    fixed_returns_aligned = []
    spy_returns_fixed = []
    for wd in fixed_best_bt["weekly_details"]:
        if wd["date"] >= adaptive_start:
            fixed_returns_aligned.append(wd["return_pct"] / 100.0)
            spy_returns_fixed.append(wd["spy_return_pct"] / 100.0)

    # QQQ returns for the adaptive period
    qqq_returns_adaptive = [wd.get("qqq_return_pct", 0.0) / 100.0 for wd in adaptive_weekly]

    stats = {
        "adaptive": _compute_stats(adaptive_returns, spy_returns_adaptive),
        "fixed_best": _compute_stats(fixed_returns_aligned, spy_returns_fixed),
        "spy": {
            "cumulative_return": round(float(np.prod([1 + r for r in spy_returns_adaptive]) - 1), 4)
            if spy_returns_adaptive else 0,
        },
        "qqq": {
            "cumulative_return": round(float(np.prod([1 + r for r in qqq_returns_adaptive]) - 1), 4)
            if qqq_returns_adaptive else 0,
        },
    }

    # ── Step 8: Parameter distribution ──
    param_distribution = defaultdict(int)
    prev_combo = None
    total_changes = 0
    for mr in monthly_report:
        combo_key = f"Top{mr['selected_top_n']} / 惯性{mr['selected_holding_bonus']}"
        param_distribution[combo_key] += 1
        curr_combo = (mr['selected_top_n'], mr['selected_holding_bonus'])
        if prev_combo and curr_combo != prev_combo:
            total_changes += 1
        prev_combo = curr_combo

    # Best/worst months
    sorted_months = sorted(monthly_report, key=lambda x: x["monthly_return"], reverse=True)
    best_months = sorted_months[:3]
    worst_months = sorted_months[-3:][::-1] if len(sorted_months) >= 3 else sorted_months[::-1]

    result = {
        "period": f"{start_date} to {end_date}",
        "training_months": training_window,
        "total_combos_tested": len(all_results),
        "monthly_report": monthly_report,
        "equity_curve": equity_curve,
        "statistics": stats,
        "fixed_best_params": {
            "top_n": best_fixed_combo[0],
            "holding_bonus": best_fixed_combo[1],
        },
        "param_changes": {
            "total_changes": total_changes,
            "param_distribution": dict(param_distribution),
        },
        "best_months": best_months,
        "worst_months": worst_months,
    }

    logger.info(f"Adaptive backtest complete: {len(monthly_report)} months analyzed, "
                f"adaptive cum={stats.get('adaptive', {}).get('cumulative_return', 0):.2%}")

    return result


def _max_drawdown(returns: list[float]) -> float:
    """Compute max drawdown from a list of period returns."""
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        max_dd = max(max_dd, dd)
    return max_dd


# ============================================================
# 5. SCORES — compute current scores without persisting
# ============================================================

async def get_current_scores() -> dict:
    """Get live rotation scores for all tickers (always show full universe)."""
    from app.services.knowledge_service import get_knowledge_service
    ks = get_knowledge_service()

    regime = await _detect_regime()
    # Always score ALL tickers for dashboard display
    universe = OFFENSIVE_ETFS + DEFENSIVE_ETFS + MIDCAP_STOCKS + INVERSE_ETFS

    # Fetch SPY closes for relative strength
    spy_data = await _fetch_history(RC.REGIME_TICKER, days=RC.LOOKBACK_DAYS)
    spy_closes = spy_data["close"] if spy_data else None

    scores = []
    for item in universe:
        score = await _score_ticker(item, regime, ks, spy_closes=spy_closes)
        if score:
            scores.append(score)

    scores.sort(key=lambda s: s.score, reverse=True)

    return {
        "regime": regime,
        "count": len(scores),
        "scores": [s.model_dump() for s in scores],
    }


# ============================================================
# DB HELPERS
# ============================================================

async def _save_snapshot(snapshot: RotationSnapshot) -> str:
    """Save rotation snapshot to DB."""
    try:
        db = get_db()
        data = {
            "snapshot_date": snapshot.snapshot_date,
            "regime": snapshot.regime,
            "spy_price": float(snapshot.spy_price),
            "spy_ma50": float(snapshot.spy_ma50),
            "scores": snapshot.scores,
            "selected_tickers": snapshot.selected_tickers,
            "previous_tickers": snapshot.previous_tickers,
            "changes": snapshot.changes,
        }
        result = db.table("rotation_snapshots").insert(data).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        logger.error(f"Error saving rotation snapshot: {e}")
    return ""


async def _get_previous_selected() -> list[str]:
    """Get selected tickers from the most recent snapshot."""
    try:
        db = get_db()
        result = (
            db.table("rotation_snapshots")
            .select("selected_tickers")
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("selected_tickers", [])
    except Exception as e:
        logger.error(f"Error getting previous selected: {e}")
    return []


async def _get_latest_selected() -> list[str]:
    """Get the latest selected tickers (same as previous for exit check)."""
    return await _get_previous_selected()


async def _get_positions_by_status(status: str) -> list[dict]:
    """Get rotation positions by status."""
    try:
        db = get_db()
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", status)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return []


async def _manage_positions_on_rotation(
    selected: list[str], removed: list[str], snapshot_id: str
):
    """
    After weekly rotation: create pending_entry for new tickers,
    mark removed tickers for exit if they're still active.
    """
    db = get_db()

    # Create pending_entry for newly selected tickers
    existing = await _get_positions_by_status("pending_entry")
    existing.extend(await _get_positions_by_status("active"))
    existing_tickers = {p["ticker"] for p in existing}

    for ticker in selected:
        if ticker not in existing_tickers:
            try:
                db.table("rotation_positions").insert({
                    "ticker": ticker,
                    "status": "pending_entry",
                    "snapshot_id": snapshot_id,
                }).execute()
                logger.info(f"Created pending_entry position for {ticker}")
            except Exception as e:
                logger.error(f"Error creating position for {ticker}: {e}")

    # Mark removed tickers as pending_exit (if active)
    for ticker in removed:
        active = [p for p in existing if p["ticker"] == ticker and p["status"] == "active"]
        for pos in active:
            try:
                db.table("rotation_positions").update({
                    "status": "pending_exit",
                }).eq("id", pos["id"]).execute()
                logger.info(f"Marked {ticker} as pending_exit (rotation removal)")
            except Exception as e:
                logger.error(f"Error updating position for {ticker}: {e}")


async def _activate_position(
    position_id: str, entry_price: float, atr: float,
    stop_loss: float, take_profit: float
):
    """Activate a pending_entry position."""
    try:
        db = get_db()
        db.table("rotation_positions").update({
            "status": "active",
            "entry_price": entry_price,
            "entry_date": date.today().isoformat(),
            "atr14": round(atr, 4),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "current_price": entry_price,
            "unrealized_pnl_pct": 0.0,
        }).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error activating position: {e}")


async def _update_position_price(position_id: str, price: float, pnl_pct: float):
    """Update current price and unrealized P&L."""
    try:
        db = get_db()
        db.table("rotation_positions").update({
            "current_price": price,
            "unrealized_pnl_pct": round(pnl_pct, 4),
        }).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error updating position price: {e}")


async def _close_position(
    position_id: str, reason: str, exit_price: float = None
):
    """Close a position."""
    try:
        db = get_db()
        update = {
            "status": "closed",
            "exit_reason": reason,
            "exit_date": date.today().isoformat(),
        }
        if exit_price:
            update["exit_price"] = exit_price
        db.table("rotation_positions").update(update).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error closing position: {e}")


async def get_current_positions() -> list[dict]:
    """Get all non-closed positions."""
    try:
        db = get_db()
        result = (
            db.table("rotation_positions")
            .select("*")
            .neq("status", "closed")
            .order("created_at", desc=True)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting current positions: {e}")
        return []


async def get_rotation_history(limit: int = 10) -> list[dict]:
    """Get recent rotation snapshots."""
    try:
        db = get_db()
        result = (
            db.table("rotation_snapshots")
            .select("*")
            .order("snapshot_date", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting rotation history: {e}")
        return []


def _days_since(timestamp_str: str) -> int:
    """Calculate days since a timestamp string."""
    try:
        if not timestamp_str:
            return 0
        dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        return (datetime.now(dt.tzinfo) - dt).days
    except Exception:
        return 0
