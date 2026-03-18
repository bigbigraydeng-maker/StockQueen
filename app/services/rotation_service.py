"""
StockQueen V2.3 - Rotation Service
Weekly momentum rotation + daily entry/exit timing for ETFs and mid-cap US stocks.
Uses Alpha Vantage for market data (replaces yfinance).
"""

import logging
import numpy as np
from typing import Optional
from datetime import datetime, date, timedelta
import pytz

from app.database import get_db
from app.config.rotation_watchlist import (
    RotationConfig,
    OFFENSIVE_ETFS, DEFENSIVE_ETFS, MIDCAP_STOCKS, INVERSE_ETFS,
    LARGECAP_STOCKS,
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

# US market holidays (NYSE) — fixed dates and observed rules
_US_HOLIDAYS_FIXED = {
    (1, 1),   # New Year's Day
    (6, 19),  # Juneteenth
    (7, 4),   # Independence Day
    (12, 25), # Christmas Day
}


def _is_us_trading_day(d: date | None = None) -> bool:
    """
    Check if a date is a US stock trading day (NYSE).
    Skips weekends and major holidays. Not exhaustive but covers 95%+ cases.
    """
    if d is None:
        # Use US Eastern time to determine "today"
        eastern = pytz.timezone("US/Eastern")
        d = datetime.now(eastern).date()

    # Weekend check
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Fixed holidays (simplified — does not handle observed Monday/Friday shifts)
    if (d.month, d.day) in _US_HOLIDAYS_FIXED:
        return False

    # Floating holidays (approximate)
    # MLK Day: 3rd Monday of January
    # Presidents Day: 3rd Monday of February
    # Good Friday: varies (skip for now)
    # Memorial Day: last Monday of May
    # Labor Day: 1st Monday of September
    # Thanksgiving: 4th Thursday of November
    import calendar
    if d.month == 1 and d.weekday() == 0:  # MLK: 3rd Mon Jan
        if 15 <= d.day <= 21:
            return False
    if d.month == 2 and d.weekday() == 0:  # Presidents: 3rd Mon Feb
        if 15 <= d.day <= 21:
            return False
    if d.month == 5 and d.weekday() == 0:  # Memorial: last Mon May
        if d.day >= 25:
            return False
    if d.month == 9 and d.weekday() == 0:  # Labor: 1st Mon Sep
        if d.day <= 7:
            return False
    if d.month == 11 and d.weekday() == 3:  # Thanksgiving: 4th Thu Nov
        if 22 <= d.day <= 28:
            return False

    return True


def _last_trading_day() -> date:
    """Return the most recent US trading day (today if trading, else previous)."""
    eastern = pytz.timezone("US/Eastern")
    d = datetime.now(eastern).date()
    while not _is_us_trading_day(d):
        d -= timedelta(days=1)
    return d


async def run_rotation(trigger_source: str = "scheduler", dry_run: bool = False) -> dict:
    """
    Weekly rotation entry point.
    Steps: detect regime → score universe → select top N → persist snapshot → manage positions.
    trigger_source: 'scheduler' | 'manual_api' | 'weekly_report' | 'weekly_report_push' | 'restart'
    dry_run: if True, compute scores and show what WOULD change, but do NOT modify positions or place orders.
    """
    logger.info("=" * 50)
    logger.info(f"Starting Rotation Scan (source={trigger_source}, dry_run={dry_run})")
    logger.info("=" * 50)

    # --- Trading day guard (skip on weekends/holidays for auto triggers) ---
    if trigger_source == "scheduler" and not _is_us_trading_day(_last_trading_day()):
        logger.info("Skipping rotation: no recent US trading day")
        return {"skipped": True, "reason": "non_trading_day"}

    # --- Cooldown guard: prevent position changes if rotation already executed today ---
    # (scoring/snapshot is allowed; only position management is gated)
    trading_day = _last_trading_day()
    _rotation_cooldown_bypass = False
    if trigger_source != "scheduler":
        try:
            _cd_db = get_db()
            _cd_result = _cd_db.table("rotation_snapshots").select("id, trigger_source").eq(
                "snapshot_date", trading_day.isoformat()
            ).order("created_at", desc=True).limit(1).execute()
            if _cd_result.data:
                _prev_source = _cd_result.data[0].get("trigger_source", "")
                logger.warning(
                    f"Rotation cooldown: snapshot already exists for {trading_day} "
                    f"(source={_prev_source}). Position changes will be skipped unless dry_run."
                )
                _rotation_cooldown_bypass = True
        except Exception as e:
            logger.warning(f"Cooldown check failed (proceeding): {e}")

    # 1. Detect market regime
    regime = await _detect_regime()
    logger.info(f"Market regime: {regime}")

    # 2. Determine scoring universe based on regime
    #    - selection_universe: tickers eligible for position selection
    #    - full_universe: ALL tickers scored for heatmap/display (always includes all pools)
    inverse_scores: list[RotationScore] = []
    if regime == "bear":
        # Defensive ETFs + inverse ETFs eligible for selection
        selection_universe = DEFENSIVE_ETFS
        inverse_scores = await _score_inverse_etfs(regime)
    elif regime == "choppy":
        selection_universe = DEFENSIVE_ETFS + OFFENSIVE_ETFS + LARGECAP_STOCKS
    elif regime == "strong_bull":
        selection_universe = OFFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS
    else:
        selection_universe = OFFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS

    # Always score the full universe so heatmap has all sectors
    full_universe = list({
        item["ticker"]: item
        for pool in [DEFENSIVE_ETFS, OFFENSIVE_ETFS, LARGECAP_STOCKS, MIDCAP_STOCKS]
        for item in pool
    }.values())
    selection_tickers = {item["ticker"] for item in selection_universe}

    # 3. Score all tickers (with RAG + relative strength adjustment)
    from app.services.knowledge_service import get_knowledge_service
    ks = get_knowledge_service()

    # Fetch SPY closes for relative strength calculation
    spy_data = await _fetch_history(RC.REGIME_TICKER, days=RC.LOOKBACK_DAYS)
    spy_closes = spy_data["close"] if spy_data else None

    scores: list[RotationScore] = []
    for item in full_universe:
        score = await _score_ticker(item, regime, ks, spy_closes=spy_closes)
        if score:
            scores.append(score)

    # Merge inverse ETF scores (bear regime only)
    if inverse_scores:
        scores.extend(inverse_scores)

    # Holding inertia: give bonus to already-held tickers to reduce turnover
    current_holdings = await _get_previous_selected()
    if current_holdings:
        for s in scores:
            if s.ticker in current_holdings:
                s.score += RC.HOLDING_BONUS
                logger.info(f"  Holding bonus +{RC.HOLDING_BONUS} for {s.ticker}")

    # Sort descending by score
    scores.sort(key=lambda s: s.score, reverse=True)

    # Apply minimum score threshold — only select from regime-eligible tickers
    # (e.g. bear → only defensive/inverse; full universe still scored for heatmap)
    selectable = [s for s in scores if s.ticker in selection_tickers or s.ticker in {inv.ticker for inv in inverse_scores}]
    qualified = [s for s in selectable if s.score >= RC.MIN_SCORE_THRESHOLD]
    selected = [s.ticker for s in qualified[:RC.TOP_N]]

    n_qualified = len(qualified)
    n_excluded = len(scores) - n_qualified
    if n_excluded > 0:
        excluded_tickers = [f"{s.ticker}({s.score:+.2f})" for s in scores if s.score < RC.MIN_SCORE_THRESHOLD]
        logger.info(f"Score filter: excluded {n_excluded} below threshold {RC.MIN_SCORE_THRESHOLD}: {excluded_tickers}")

    logger.info(f"Top {len(selected)} (qualified {n_qualified}/{len(scores)}): {selected}")
    for s in scores[:10]:
        logger.info(f"  {s.ticker:6s} score={s.score:+.2f}  "
                     f"1w={s.return_1w:+.1%} 1m={s.return_1m:+.1%} 3m={s.return_3m:+.1%}  "
                     f"vol={s.volatility:.1%} MA20={'Y' if s.above_ma20 else 'N'}")

    # 4. Load previous snapshot for comparison
    previous_tickers = await _get_previous_selected()
    added = [t for t in selected if t not in previous_tickers]
    removed = [t for t in previous_tickers if t not in selected]

    # 5. Save snapshot (use last trading day as snapshot_date, not today)
    trading_day = _last_trading_day()
    spy_data = await _fetch_history(RC.REGIME_TICKER, days=RC.REGIME_MA_PERIOD + 10)
    spy_price = float(spy_data["close"][-1]) if spy_data else 0.0
    spy_ma50 = _compute_ma(spy_data["close"], RC.REGIME_MA_PERIOD) if spy_data else 0.0

    # --- Dedup: skip if same date + regime + selection already exists ---
    try:
        dup_db = get_db()
        dup_result = dup_db.table("rotation_snapshots").select("id, selected_tickers, regime").eq(
            "snapshot_date", trading_day.isoformat()
        ).order("created_at", desc=True).limit(1).execute()
        if dup_result.data:
            last = dup_result.data[0]
            if last["regime"] == regime and sorted(last.get("selected_tickers") or []) == sorted(selected):
                logger.info(f"Dedup: identical snapshot already exists for {trading_day}, skipping save")
                # Save current scores immediately, then background-score full universe
                await _save_sector_snapshots(scores, regime, trading_day)
                await _persist_all_scores_to_cache(scores, regime)
                import asyncio
                asyncio.create_task(_score_full_universe_background(scores, regime, ks, spy_closes, trading_day, inverse_scores))
                return {
                    "regime": regime,
                    "selected": selected,
                    "added": added,
                    "removed": removed,
                    "scores_top10": [s.model_dump() for s in scores[:10]],
                    "snapshot_id": last["id"],
                    "deduplicated": True,
                }
    except Exception as e:
        logger.warning(f"Dedup check failed (proceeding anyway): {e}")

    snapshot = RotationSnapshot(
        snapshot_date=trading_day.isoformat(),
        regime=regime,
        spy_price=spy_price,
        spy_ma50=spy_ma50,
        scores=[s.model_dump() for s in scores[:20]],
        selected_tickers=selected,
        previous_tickers=previous_tickers,
        changes={"added": added, "removed": removed},
    )
    snapshot_id = await _save_snapshot(snapshot, trigger_source=trigger_source)

    # 6. Manage positions (skip if dry_run or cooldown triggered for manual runs)
    _skip_position_mgmt = dry_run or _rotation_cooldown_bypass
    if _skip_position_mgmt:
        _reason = "dry_run" if dry_run else "cooldown (already executed today)"
        logger.info(f"Skipping position management: {_reason}")
    else:
        await _manage_positions_on_rotation(selected, removed, snapshot_id)

    # 7. Persist regime-filtered scores to cache + sector snapshots immediately
    await _persist_all_scores_to_cache(scores, regime)
    await _save_sector_snapshots(scores, regime, trading_day)

    # 8. Fire-and-forget: score remaining tickers in background for full sector data
    import asyncio
    asyncio.create_task(_score_full_universe_background(scores, regime, ks, spy_closes, trading_day, inverse_scores))

    result = {
        "regime": regime,
        "selected": selected,
        "added": added,
        "removed": removed,
        "scores_top10": [s.model_dump() for s in scores[:10]],
        "snapshot_id": snapshot_id,
    }
    if dry_run:
        result["dry_run"] = True
        result["positions_changed"] = False
    if _rotation_cooldown_bypass:
        result["cooldown"] = True
        result["positions_changed"] = False
    return result


async def _persist_all_scores_to_cache(scores: list[RotationScore], regime: str) -> None:
    """Persist ALL rotation scores to cache_store (not just top 20) for sector detail fallback."""
    try:
        scores_payload = {
            "regime": regime,
            "count": len(scores),
            "scores": [s.model_dump() for s in scores],
        }
        cache_db = get_db()
        cache_db.table("cache_store").upsert({
            "key": "rotation_scores",
            "value": scores_payload,
        }).execute()
        logger.info(f"Rotation scores persisted to cache_store ({len(scores)} total)")
    except Exception as e:
        logger.warning(f"Failed to persist scores to cache_store: {e}")


async def _score_full_universe_background(
    initial_scores: list[RotationScore],
    regime: str,
    ks,
    spy_closes,
    trading_day,
    inverse_scores: list[RotationScore],
) -> None:
    """Background task: score all tickers not yet scored (in batches), then update sector snapshots."""
    import asyncio
    try:
        full_universe = OFFENSIVE_ETFS + DEFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS + INVERSE_ETFS
        scored_tickers = {s.ticker for s in initial_scores}
        extra_items = [item for item in full_universe if item["ticker"] not in scored_tickers]
        if not extra_items:
            logger.info("[BG] All tickers already scored, skipping")
            return

        logger.info(f"[BG] Scoring {len(extra_items)} extra tickers for full sector snapshots...")
        all_scores = list(initial_scores)  # copy

        # Score in batches of 100 to reduce API pressure
        BATCH_SIZE = 100
        for batch_idx in range(0, len(extra_items), BATCH_SIZE):
            batch = extra_items[batch_idx:batch_idx + BATCH_SIZE]
            batch_num = batch_idx // BATCH_SIZE + 1
            total_batches = (len(extra_items) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"[BG] Batch {batch_num}/{total_batches}: scoring tickers {batch_idx + 1}-{batch_idx + len(batch)}...")

            for item in batch:
                s = await _score_ticker(item, regime, ks, spy_closes=spy_closes)
                if s:
                    all_scores.append(s)

            # Yield control between batches to avoid blocking the event loop
            if batch_idx + BATCH_SIZE < len(extra_items):
                await asyncio.sleep(2)

        # Also score inverse ETFs if not already included
        if not inverse_scores:
            inv_extra = await _score_inverse_etfs(regime)
            for s in inv_extra:
                if s.ticker not in scored_tickers:
                    all_scores.append(s)

        # Overwrite sector snapshots + cache with full data
        await _save_sector_snapshots(all_scores, regime, trading_day)
        await _persist_all_scores_to_cache(all_scores, regime)
        logger.info(f"[BG] Full universe sector snapshots saved: {len(all_scores)} tickers")
    except Exception as e:
        logger.error(f"[BG] Failed to score full universe: {e}")


async def _save_sector_snapshots(scores: list[RotationScore], regime: str, snapshot_date) -> None:
    """Aggregate scores by sector and persist to sector_snapshots for trend tracking."""
    sector_map: dict[str, dict] = {}
    for s in scores:
        sec = s.sector or "other"
        if not sec:
            continue
        if sec not in sector_map:
            sector_map[sec] = {"score_sum": 0, "ret_sum": 0, "count": 0, "tickers": []}
        sector_map[sec]["score_sum"] += s.score
        sector_map[sec]["ret_sum"] += s.return_1w
        sector_map[sec]["count"] += 1
        sector_map[sec]["tickers"].append({
            "ticker": s.ticker,
            "name": s.name,
            "score": round(s.score, 2),
            "return_1w": round(s.return_1w * 100, 2),
            "current_price": s.current_price,
        })

    try:
        db = get_db()
        rows = []
        for sec, data in sector_map.items():
            n = data["count"]
            data["tickers"].sort(key=lambda x: x["score"], reverse=True)
            rows.append({
                "snapshot_date": snapshot_date.isoformat() if hasattr(snapshot_date, 'isoformat') else str(snapshot_date),
                "sector": sec,
                "avg_score": round(data["score_sum"] / n, 4),
                "avg_ret_1w": round(data["ret_sum"] / n, 4),
                "stock_count": n,
                "top_tickers": data["tickers"],
                "regime": regime,
            })
        if rows:
            db.table("sector_snapshots").upsert(
                rows, on_conflict="snapshot_date,sector"
            ).execute()
            logger.info(f"Saved {len(rows)} sector snapshots for {snapshot_date}")
    except Exception as e:
        logger.warning(f"Failed to save sector snapshots: {e}")


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


async def detect_regime_details() -> dict:
    """
    返回 regime 的详细诊断信息，用于 Regime Transition Map 可视化。
    包含：当前 regime、总分、每个信号的贡献、以及到相邻 regime 的距离。
    """
    data = await _fetch_history(RC.REGIME_TICKER, days=80)
    if not data:
        return {"regime": "bull", "score": 0, "signals": [], "transitions": {}, "error": "no_data"}

    closes = data["close"]
    if len(closes) < 63:
        return {"regime": "bull", "score": 0, "signals": [], "transitions": {}, "error": "insufficient_data"}

    ma50 = _compute_ma(closes, 50)
    ma20 = _compute_ma(closes, 20)
    current = float(closes[-1])

    vol_arr = np.diff(closes[-22:]) / closes[-22:-1] if len(closes) > 22 else np.array([0])
    vol_21d = float(np.std(vol_arr) * np.sqrt(252))

    ret_1m = (current / float(closes[-22])) - 1 if len(closes) > 22 else 0

    # --- 逐信号计算 ---
    signals = []

    # Signal 1: SPY vs MA50
    spy_ma50_pct = (current / ma50 - 1) * 100  # e.g. +2.3%
    if current > ma50 * 1.02:
        s1 = 2
    elif current > ma50:
        s1 = 1
    elif current < ma50 * 0.98:
        s1 = -2
    else:
        s1 = -1
    signals.append({
        "name": "SPY vs MA50",
        "description": "趋势方向",
        "value": round(spy_ma50_pct, 2),
        "unit": "%",
        "contribution": s1,
        "range": [-2, 2],
        "thresholds": [
            {"label": "强看空", "condition": "< -2%", "points": -2, "met": current < ma50 * 0.98},
            {"label": "看空", "condition": "-2% ~ 0%", "points": -1, "met": ma50 * 0.98 <= current < ma50},
            {"label": "看多", "condition": "0% ~ +2%", "points": 1, "met": ma50 <= current < ma50 * 1.02},
            {"label": "强看多", "condition": "> +2%", "points": 2, "met": current >= ma50 * 1.02},
        ],
        "key_levels": {"MA50": round(ma50, 2), "+2%线": round(ma50 * 1.02, 2), "-2%线": round(ma50 * 0.98, 2)},
    })

    # Signal 2: SPY vs MA20
    spy_ma20_pct = (current / ma20 - 1) * 100
    s2 = 1 if current > ma20 else -1
    signals.append({
        "name": "SPY vs MA20",
        "description": "短期动量",
        "value": round(spy_ma20_pct, 2),
        "unit": "%",
        "contribution": s2,
        "range": [-1, 1],
        "thresholds": [
            {"label": "看空", "condition": "< MA20", "points": -1, "met": current <= ma20},
            {"label": "看多", "condition": "> MA20", "points": 1, "met": current > ma20},
        ],
        "key_levels": {"MA20": round(ma20, 2)},
    })

    # Signal 3: 21d Volatility
    vol_pct = round(vol_21d * 100, 1)
    if vol_21d > 0.25:
        s3 = -1
    elif vol_21d < 0.12:
        s3 = 1
    else:
        s3 = 0
    signals.append({
        "name": "波动率 (21d)",
        "description": "市场压力",
        "value": vol_pct,
        "unit": "%",
        "contribution": s3,
        "range": [-1, 1],
        "thresholds": [
            {"label": "高压", "condition": "> 25%", "points": -1, "met": vol_21d > 0.25},
            {"label": "中性", "condition": "12% ~ 25%", "points": 0, "met": 0.12 <= vol_21d <= 0.25},
            {"label": "平静", "condition": "< 12%", "points": 1, "met": vol_21d < 0.12},
        ],
        "key_levels": {"高压线": 25.0, "平静线": 12.0},
    })

    # Signal 4: 1M Return
    ret_pct = round(ret_1m * 100, 1)
    if ret_1m > 0.03:
        s4 = 1
    elif ret_1m < -0.03:
        s4 = -1
    else:
        s4 = 0
    signals.append({
        "name": "1个月回报",
        "description": "动量确认",
        "value": ret_pct,
        "unit": "%",
        "contribution": s4,
        "range": [-1, 1],
        "thresholds": [
            {"label": "下跌", "condition": "< -3%", "points": -1, "met": ret_1m < -0.03},
            {"label": "中性", "condition": "-3% ~ +3%", "points": 0, "met": -0.03 <= ret_1m <= 0.03},
            {"label": "上涨", "condition": "> +3%", "points": 1, "met": ret_1m > 0.03},
        ],
        "key_levels": {"上涨线": 3.0, "下跌线": -3.0},
    })

    score = s1 + s2 + s3 + s4

    if score >= 4:
        regime = "strong_bull"
    elif score >= 1:
        regime = "bull"
    elif score >= -1:
        regime = "choppy"
    else:
        regime = "bear"

    # --- 到各 regime 边界的距离 ---
    # score thresholds: strong_bull >= 4, bull >= 1, choppy >= -1, bear < -1
    transitions = {
        "strong_bull": {"threshold": 4, "distance": 4 - score, "direction": "up"},
        "bull":        {"threshold": 1, "distance": 1 - score, "direction": "up" if score < 1 else "down"},
        "choppy":      {"threshold": -1, "distance": -1 - score, "direction": "up" if score < -1 else "down"},
        "bear":        {"threshold": -2, "distance": score - (-2), "direction": "down"},
    }

    return {
        "regime": regime,
        "score": score,
        "score_range": [-5, 5],
        "spy_price": round(current, 2),
        "signals": signals,
        "transitions": transitions,
        "regime_thresholds": [
            {"regime": "strong_bull", "label": "强牛市", "min_score": 4, "max_score": 5},
            {"regime": "bull", "label": "牛市", "min_score": 1, "max_score": 3},
            {"regime": "choppy", "label": "震荡市", "min_score": -1, "max_score": 0},
            {"regime": "bear", "label": "熊市", "min_score": -5, "max_score": -2},
        ],
    }


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


async def _score_inverse_etfs(regime: str) -> list[RotationScore]:
    """
    Score inverse ETFs by underlying index weakness (NOT multi-factor).
    Fetches SPY/QQQ/IWM/DIA returns; the weaker the index, the higher
    the corresponding inverse ETF scores.
    """
    from app.config.rotation_watchlist import INVERSE_ETF_INDEX_MAP, INVERSE_ETFS

    index_weakness: dict[str, dict] = {}
    for inv_etf in INVERSE_ETFS:
        idx_ticker = INVERSE_ETF_INDEX_MAP.get(inv_etf["ticker"])
        if not idx_ticker:
            continue
        data = await _fetch_history(idx_ticker, days=RC.LOOKBACK_DAYS)
        if not data or len(data["close"]) < 21:
            continue
        closes = data["close"]
        ret_1w = _compute_return(closes, 5)
        ret_1m = _compute_return(closes, 21)
        # Higher weakness = index dropped more = inverse ETF more attractive
        weakness = -(0.4 * ret_1w + 0.6 * ret_1m)
        index_weakness[inv_etf["ticker"]] = {
            "weakness": weakness,
            "idx_ret_1w": ret_1w,
            "idx_ret_1m": ret_1m,
        }

    scores: list[RotationScore] = []
    for inv_etf in INVERSE_ETFS:
        tk = inv_etf["ticker"]
        if tk not in index_weakness:
            continue
        w = index_weakness[tk]
        # Fetch the inverse ETF's own price data for display fields
        inv_data = await _fetch_history(tk, days=RC.LOOKBACK_DAYS)
        if not inv_data or len(inv_data["close"]) < 21:
            continue
        inv_closes = inv_data["close"]

        score = round(w["weakness"] * 10, 2)  # Scale to match multi-factor range

        scores.append(RotationScore(
            ticker=tk,
            name=inv_etf["name"],
            asset_type="inverse_etf",
            sector=inv_etf.get("sector", ""),
            return_1w=_compute_return(inv_closes, 5),
            return_1m=_compute_return(inv_closes, 21),
            return_3m=_compute_return(inv_closes, 63) if len(inv_closes) >= 63 else 0,
            volatility=_compute_volatility(inv_closes),
            above_ma20=float(inv_closes[-1]) > _compute_ma(inv_closes, 20),
            score=score,
            current_price=float(inv_closes[-1]),
        ))

    logger.info(f"Inverse ETF scores (index weakness): {[(s.ticker, s.score) for s in scores]}")
    return scores


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
                pos["id"], current_price, atr, stop_loss, take_profit,
                ticker=ticker
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

        atr14 = float(pos.get("atr14", 0) or 0)
        highest_price = float(pos.get("highest_price", 0) or 0)

        data = await _fetch_history(ticker, days=30)
        if not data:
            continue

        closes = data["close"]
        current_price = float(closes[-1])

        # Update highest price for trailing stop
        if highest_price <= 0:
            highest_price = max(current_price, entry_price)
        else:
            highest_price = max(highest_price, current_price)

        # Update current price + highest_price in DB
        pnl_pct = (current_price / entry_price - 1.0) if entry_price > 0 else 0.0
        await _update_position_price(pos["id"], current_price, pnl_pct,
                                     highest_price=highest_price)

        exit_reason = None
        conditions = []

        # Compute effective stop (static or trailing, whichever is higher)
        effective_sl = stop_loss
        if RC.TRAILING_STOP_ENABLED and atr14 > 0 and entry_price > 0:
            profit = highest_price - entry_price
            if profit >= RC.TRAILING_ACTIVATE_ATR * atr14:
                trailing_sl = highest_price - RC.TRAILING_STOP_ATR_MULT * atr14
                if trailing_sl > effective_sl:
                    effective_sl = trailing_sl

        # Check stop loss (static or trailing)
        if effective_sl > 0 and current_price < effective_sl:
            is_trailing = effective_sl > stop_loss
            exit_reason = "trailing_stop" if is_trailing else "stop_loss"
            conditions.append(f"close ${current_price:.2f} < {'TSL' if is_trailing else 'SL'} ${effective_sl:.2f}"
                              f" (high=${highest_price:.2f})")

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

            pos_qty = int(pos.get("quantity", 0) or 0)
            await _close_position(pos["id"], reason=exit_reason,
                                  exit_price=current_price,
                                  ticker=ticker, quantity=pos_qty)
            logger.info(f"EXIT {exit_reason}: {ticker} @ ${current_price:.2f} "
                         f"(entry ${entry_price:.2f}, pnl {pnl_pct:+.1%})")

    return signals


# ============================================================
# 4. BACKTEST
# ============================================================

# Sector → representative ETF mapping for backtest sector_wind factor
_SECTOR_ETF_MAP = {
    "tech": "XLK",
    "semi": "SOXX",
    "bio": "IBB",
    "consumer": "XLC",      # closest proxy: Communication Services
    "industrial": "XLI",
    "fintech": "XLF",       # closest proxy: Financials
    "saas": "XLK",          # map to Technology
    "space": "XLI",         # closest proxy: Industrials
    "china": "VWO",         # closest proxy: Emerging Markets
    "ai": "XLK",            # map to Technology
}


def _compute_sector_returns_at(histories: dict, bar_index: int,
                                lookback: int = 21) -> Optional[dict]:
    """
    Compute 1-month sector returns from historical ETF data at a given bar index.
    Used in backtest to populate the sector_wind factor (instead of passing None).

    Returns: {"tech": 0.05, "semi": -0.02, ...} or None if data insufficient.
    """
    if bar_index < lookback + 1:
        return None

    sector_returns = {}
    for sector, etf in _SECTOR_ETF_MAP.items():
        h = histories.get(etf)
        if h is None or bar_index >= len(h["close"]):
            continue
        closes = h["close"]
        current = closes[bar_index]
        prev = closes[bar_index - lookback]
        if prev > 0:
            sector_returns[sector] = float((current / prev) - 1)

    return sector_returns if sector_returns else None


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


def _bt_entry_price(h: dict, i: int) -> float:
    """Get backtest entry price: next-day open (i+1) if enabled, else close(i)."""
    if RC.BACKTEST_NEXT_OPEN and i + 1 < len(h.get("open", h["close"])):
        return float(h.get("open", h["close"])[i + 1])
    return float(h["close"][i])


def _bt_exit_price(h: dict, i: int, step: int) -> float:
    """Get backtest exit price: close at i+step (held for full week)."""
    idx = min(i + step, len(h["close"]) - 1)
    return float(h["close"][idx])


def _score_weighted_returns(selected: list, scores_map: dict,
                            histories: dict, i: int, step: int,
                            prev_selected: list = None) -> float:
    """
    Compute score-weighted portfolio return (instead of equal weight).
    Higher scored tickers get proportionally larger allocation.
    Includes slippage for entry/exit and turnover.
    """
    weights = []
    returns = []
    slippage = RC.BACKTEST_SLIPPAGE
    added = set(selected) - set(prev_selected or [])
    removed = set(prev_selected or []) - set(selected)

    for t in selected:
        h = histories.get(t)
        if h is None or i + step >= len(h["close"]):
            continue
        entry_px = _bt_entry_price(h, i)
        exit_px = _bt_exit_price(h, i, step)
        week_ret = (exit_px / entry_px) - 1
        # Slippage: charge on entry for new positions, on exit for removed next week
        if t in added and slippage > 0:
            week_ret -= slippage  # entry slippage
        raw_score = max(scores_map.get(t, 0), 0.01)
        weights.append(raw_score)
        returns.append(week_ret)

    # Also charge exit slippage for positions being removed
    if slippage > 0 and removed:
        # Approximate: removed positions' exit slippage reduces total return
        n_total = len(selected) + len(removed)
        if n_total > 0:
            removed_slip = len(removed) * slippage / max(len(selected), 1)
            returns = [r - removed_slip / max(len(returns), 1) for r in returns]

    if not weights:
        return 0.0

    total_w = sum(weights)
    if total_w <= 0:
        return sum(returns) / len(returns) if returns else 0.0

    return sum(w / total_w * r for w, r in zip(weights, returns))


# ── Full-range OHLCV cache for sub-range slicing ──
# Stored by scheduler after weekly pre-compute; allows custom date ranges
# to slice from cached data instead of re-fetching 500 tickers from AV.
# Persisted to disk via pickle so it survives server restarts.
import os as _os
import pickle as _pickle

_PREFETCHED_FULL: dict = {}  # {"histories": {...}, "bt_fundamentals": {...}, "start": str, "end": str}
_PREFETCHED_DISK_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
    ".cache", "prefetched_full.pkl"
)


def set_prefetched_full(data: dict, start_date: str, end_date: str):
    """Cache full-range pre-fetched data for sub-range slicing (memory + disk)."""
    global _PREFETCHED_FULL
    _PREFETCHED_FULL = {**data, "start": start_date, "end": end_date}
    logger.info(f"Cached full-range OHLCV data: {start_date} to {end_date}, "
                f"{len(data.get('histories', {}))} tickers")
    # Persist to disk
    try:
        _os.makedirs(_os.path.dirname(_PREFETCHED_DISK_PATH), exist_ok=True)
        with open(_PREFETCHED_DISK_PATH, "wb") as f:
            _pickle.dump(_PREFETCHED_FULL, f, protocol=_pickle.HIGHEST_PROTOCOL)
        size_mb = _os.path.getsize(_PREFETCHED_DISK_PATH) / 1024 / 1024
        logger.info(f"Saved prefetched data to disk ({size_mb:.1f} MB)")
    except Exception as e:
        logger.warning(f"Failed to save prefetched data to disk: {e}")


def _load_prefetched_from_disk():
    """Load cached full-range data from disk if available."""
    global _PREFETCHED_FULL
    if _PREFETCHED_FULL and "histories" in _PREFETCHED_FULL:
        return  # Already loaded
    if not _os.path.exists(_PREFETCHED_DISK_PATH):
        return
    try:
        with open(_PREFETCHED_DISK_PATH, "rb") as f:
            _PREFETCHED_FULL = _pickle.load(f)
        logger.info(f"Loaded prefetched data from disk: "
                    f"{_PREFETCHED_FULL.get('start')} to {_PREFETCHED_FULL.get('end')}, "
                    f"{len(_PREFETCHED_FULL.get('histories', {}))} tickers")
    except Exception as e:
        logger.warning(f"Failed to load prefetched data from disk: {e}")


def _build_prefetched_from_av_disk_cache(start_date: str, end_date: str) -> Optional[dict]:
    """
    当主预取缓存（2022+）不覆盖目标时间段时，尝试从 AV Client 的磁盘 OHLCV 缓存
    构建等效的 prefetched dict，支持 2018+ 历史回测。
    前提：需先运行 scripts/populate_ohlcv_cache.py 填充磁盘缓存。
    """
    import pandas as pd
    from app.services.alphavantage_client import get_av_client

    av = get_av_client()
    if not av._daily_cache:
        return None

    # 包含6个月热身期
    ts_start = pd.Timestamp(start_date) - pd.DateOffset(months=6)
    ts_end   = pd.Timestamp(end_date)

    # 取所有已缓存的 full OHLCV ticker（key 格式 "TICKER:full"）
    histories = {}
    for cache_key, entry in list(av._daily_cache.items()):
        if not cache_key.endswith(":full"):
            continue
        ticker = cache_key[:-5]  # strip ":full"
        if not ticker or ":" in ticker:
            continue  # 跳过 "daily:TICKER:full" 的旧格式key
        try:
            _, df = entry
            if not hasattr(df, "index"):
                continue
            mask = (df.index >= ts_start) & (df.index <= ts_end)
            df_s = df.loc[mask]
            if len(df_s) < 50:
                continue
            histories[ticker] = {
                "close":  df_s["Close"].values,
                "open":   df_s["Open"].values,
                "high":   df_s["High"].values,
                "low":    df_s["Low"].values,
                "volume": df_s["Volume"].values,
                "dates":  df_s.index,
                "item":   {"symbol": ticker},
            }
        except Exception:
            continue

    if len(histories) < 50 or "SPY" not in histories:
        logger.warning(
            f"[slice_prefetched] AV磁盘缓存不足以覆盖 {start_date}→{end_date}，"
            f"仅找到 {len(histories)} 支股票。请运行 scripts/populate_ohlcv_cache.py。"
        )
        return None

    logger.info(
        f"[slice_prefetched] 使用 AV 磁盘 OHLCV 缓存构建历史回测数据: "
        f"{start_date}→{end_date}, {len(histories)} tickers"
    )
    return {"histories": histories, "bt_fundamentals": {}}


def _slice_prefetched(start_date: str, end_date: str) -> Optional[dict]:
    """
    Slice the cached full-range data to a sub-range.
    Returns prefetched dict suitable for run_rotation_backtest(_prefetched=...),
    or None if cached data doesn't cover the requested range.

    回退逻辑：
      1. 内存预取（最快）→ 2. 磁盘 pickle（重启后）→ 3. AV 磁盘 OHLCV 缓存（历史 2018+）
    """
    # Try loading from disk if not in memory
    if not _PREFETCHED_FULL or "histories" not in _PREFETCHED_FULL:
        _load_prefetched_from_disk()

    if not _PREFETCHED_FULL or "histories" not in _PREFETCHED_FULL:
        # 主缓存不可用，直接尝试 AV 磁盘缓存
        return _build_prefetched_from_av_disk_cache(start_date, end_date)

    cached_start = _PREFETCHED_FULL.get("start", "")
    cached_end = _PREFETCHED_FULL.get("end", "")
    if start_date < cached_start or end_date > cached_end:
        # 请求范围超出主缓存 → 回退到 AV 磁盘缓存
        logger.info(
            f"[slice_prefetched] 请求 {start_date}→{end_date} 超出主缓存范围 "
            f"{cached_start}→{cached_end}，尝试 AV 磁盘缓存..."
        )
        return _build_prefetched_from_av_disk_cache(start_date, end_date)

    # If requesting the full range, return directly (no slicing needed)
    if start_date == cached_start and end_date == cached_end:
        return {
            "histories": _PREFETCHED_FULL["histories"],
            "bt_fundamentals": _PREFETCHED_FULL.get("bt_fundamentals", {}),
        }

    import pandas as pd
    ts_start = pd.Timestamp(start_date)
    ts_end = pd.Timestamp(end_date)

    # Include 6 months of lookback before start_date for momentum/MA calculations
    # (backtest needs ≥63 trading days before start_idx).
    # Clamp to cache start so we use all available data even if 6mo exceeds cache.
    lookback_start = max(
        ts_start - pd.DateOffset(months=6),
        pd.Timestamp(cached_start),
    )

    sliced_histories = {}
    for ticker, h in _PREFETCHED_FULL["histories"].items():
        dates = h["dates"]
        mask = (dates >= lookback_start) & (dates <= ts_end)
        if mask.sum() > 20:
            sliced_histories[ticker] = {
                "close": h["close"][mask],
                "open": h["open"][mask],
                "volume": h["volume"][mask],
                "high": h["high"][mask],
                "low": h["low"][mask],
                "dates": dates[mask],
                "item": h["item"],
            }

    if not sliced_histories or "SPY" not in sliced_histories:
        return None

    return {
        "histories": sliced_histories,
        "bt_fundamentals": _PREFETCHED_FULL.get("bt_fundamentals", {}),
    }


async def _fetch_backtest_ohlcv_only(start_date: str, end_date: str) -> dict:
    """
    Lightweight startup prefetch: OHLCV only, skip fundamentals.
    ~500 API calls (~6.5 min) vs full fetch with fundamentals.
    Enough for _slice_prefetched() to serve custom date ranges.
    """
    import time as _time
    t0 = _time.time()

    av = get_av_client()
    all_items = OFFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS + DEFENSIVE_ETFS + INVERSE_ETFS
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
                    "open": hist["Open"].values if "Open" in hist.columns else hist["Close"].values,
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
        total_done = fetched + failed
        if total_done % 20 == 0:
            logger.info(f"OHLCV-only progress: {total_done}/{len(all_items)} "
                        f"(OK: {fetched}, failed: {failed})")

    elapsed = _time.time() - t0
    logger.info(f"OHLCV-only fetch complete in {elapsed:.1f}s: "
                f"{fetched}/{len(all_items)} tickers OK, {failed} failed")

    if not histories:
        return {"error": f"No data fetched (tried {len(all_items)} tickers, all failed)."}
    if "SPY" not in histories:
        return {"error": "SPY data not available — cannot compute benchmark"}

    return {"histories": histories, "bt_fundamentals": {}}


async def _fetch_backtest_data(start_date: str, end_date: str) -> dict:
    """
    Fetch all OHLCV + fundamental data needed for backtesting.
    Returns {'histories': {...}, 'bt_fundamentals': {...}} or {'error': '...'}.
    Call once and pass to run_rotation_backtest() to avoid repeated API calls.

    Uses the AV client's built-in 1-hour cache: first call is slow (~3-4min),
    subsequent calls within 1 hour are nearly instant.

    NEW: If full-range data is cached (from scheduler), slices from it instead
    of re-fetching from Alpha Vantage.
    """
    # Try slicing from cached full-range data first
    sliced = _slice_prefetched(start_date, end_date)
    if sliced:
        logger.info(f"Using cached full-range data sliced to {start_date}..{end_date} "
                    f"({len(sliced['histories'])} tickers)")
        return sliced

    import time as _time
    t0 = _time.time()

    av = get_av_client()
    all_items = OFFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS + DEFENSIVE_ETFS + INVERSE_ETFS
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
                    "open": hist["Open"].values if "Open" in hist.columns else hist["Close"].values,
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
    # Only earnings + cashflow (overview DISABLED due to look-ahead bias —
    # AV OVERVIEW returns current-snapshot data, not point-in-time).
    # The auto-normalize in compute_multi_factor_score() redistributes weight.
    bt_fundamentals = {}
    stock_items = LARGECAP_STOCKS + MIDCAP_STOCKS
    midcap_tickers = [s["ticker"] for s in stock_items if s["ticker"] in histories]
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
            # NOTE: overview (COMPANY_OVERVIEW) intentionally skipped —
            # it returns current values, not point-in-time historical data,
            # causing look-ahead bias in backtesting.
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
    start_date: str = "2023-04-01",
    end_date: str = "2026-03-01",
    top_n: int = RC.TOP_N,
    holding_bonus: float = RC.HOLDING_BONUS,
    _prefetched: dict = None,
    regime_version: str = "v1",
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
    largecap_set = {e["ticker"] for e in LARGECAP_STOCKS}

    # Simulate week by week
    spy_dates = spy_hist["dates"]

    # ── Date-range filter: find index bounds for start_date / end_date ──
    import pandas as pd
    _sd = pd.Timestamp(start_date)
    _ed = pd.Timestamp(end_date)
    start_idx = 63
    for _si in range(len(spy_dates)):
        if spy_dates[_si] >= _sd:
            start_idx = max(_si, 63)
            break
    end_idx = len(spy_dates)
    for _ei in range(len(spy_dates) - 1, -1, -1):
        if spy_dates[_ei] <= _ed:
            end_idx = _ei + 1
            break

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

    # ATR stop-loss tracking: {ticker: {"stop": px, "entry": px, "high": px, "atr": atr}}
    active_stops = {}
    stop_triggered_count = 0
    trailing_triggered_count = 0

    # Walk through time in weekly steps (within the date range)
    step = 5  # ~1 trading week
    for i in range(start_idx, min(end_idx, len(spy_dates)) - step, step):
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

        # V2: bounce detection — faster bear→choppy transition
        if regime_version == "v2" and len(spy_closes_so_far) >= 10:
            recent_low = float(np.min(spy_closes_so_far[-10:]))
            if recent_low > 0:
                bounce_pct = (spy_cur - recent_low) / recent_low
                if bounce_pct >= 0.05 and spy_cur > ma20_bt:
                    rscore += 2

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

            # ── IPO date filter: skip tickers not yet listed at bt_date ──
            listed_since = h["item"].get("listed_since")
            if listed_since and bt_date < listed_since:
                continue

            volumes = h["volume"][:i + 1]

            # ── Liquidity filter: skip tickers with low avg volume ──
            if RC.BACKTEST_MIN_AVG_VOL > 0 and len(volumes) >= 20:
                avg_vol_20d = float(np.mean(volumes[-20:]))
                if avg_vol_20d < RC.BACKTEST_MIN_AVG_VOL:
                    continue
            highs = h["high"][:i + 1]
            lows = h["low"][:i + 1]

            # Get pre-fetched fundamental data for this ticker (if available)
            # NOTE: overview (COMPANY_OVERVIEW) is DISABLED in backtest because
            # Alpha Vantage returns current-snapshot data, causing look-ahead bias.
            # The auto-normalize in compute_multi_factor_score() will redistribute
            # the fundamental weight to other available factors automatically.
            earnings_bt = bt_fundamentals.get(ticker, {}).get("earnings_data")
            cashflow_bt = bt_fundamentals.get(ticker, {}).get("cashflow_data")

            # Compute sector returns from historical ETF data (if available)
            bt_sector_returns = _compute_sector_returns_at(histories, i) if histories else None

            # Unified multi-factor score
            result = compute_multi_factor_score(
                closes=closes,
                volumes=volumes,
                highs=highs,
                lows=lows,
                spy_closes=spy_closes_for_rs,
                regime=regime,
                overview=None,              # DISABLED: look-ahead bias
                earnings_data=earnings_bt,
                cashflow_data=cashflow_bt,
                sentiment_value=None,        # no historical sentiment data
                sector_returns=bt_sector_returns,
                ticker_sector=h["item"].get("sector", ""),
                as_of_date=bt_date,
            )

            score = result["total_score"]

            # ── Relative strength filter ──
            is_defensive = ticker in defensive_set
            is_inverse = ticker in inverse_set
            is_etf = ticker in offensive_set
            is_largecap = ticker in largecap_set
            is_midcap = not is_defensive and not is_etf and not is_inverse and not is_largecap

            if RC.RELATIVE_STRENGTH_FILTER and not is_defensive and not is_inverse:
                rs = _compute_relative_strength(closes, spy_closes_for_rs, period=21)
                if rs < -0.02:  # underperforming SPY by >2% → skip
                    continue

            # Regime filter (matches run_rotation() universe logic)
            if regime == "bear" and not is_defensive and not is_inverse:
                continue
            elif regime == "choppy" and (is_midcap or is_inverse):
                # choppy: allow defensive + offensive ETFs + largecap
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

        # ── ATR stop-loss simulation (with trailing stop) ──
        # Set stops for newly added tickers
        if RC.BACKTEST_STOP_LOSS:
            for t in added:
                h = histories.get(t)
                if h and i < len(h["close"]) and i < len(h["high"]) and i < len(h["low"]):
                    closes_t = h["close"][:i + 1]
                    highs_t = h["high"][:i + 1]
                    lows_t = h["low"][:i + 1]
                    atr = _compute_atr(highs_t, lows_t, closes_t)
                    entry_px = _bt_entry_price(h, i)
                    active_stops[t] = {
                        "stop": entry_px - RC.BACKTEST_STOP_MULT * atr,
                        "entry": entry_px,
                        "high": entry_px,
                        "atr": atr,
                    }
            # Remove stops for removed tickers
            for t in removed:
                active_stops.pop(t, None)

        prev_selected = selected[:]

        # ── Compute portfolio return for next week ──
        if RC.SCORE_WEIGHTED_ALLOC:
            port_ret = _score_weighted_returns(selected, scores_map, histories, i, step,
                                               prev_selected=prev_selected)
        else:
            slippage = RC.BACKTEST_SLIPPAGE
            port_ret = 0.0
            valid = 0
            for t in selected:
                h = histories.get(t)
                if h is None or i + step >= len(h["close"]):
                    continue
                entry_px = _bt_entry_price(h, i)
                exit_px = _bt_exit_price(h, i, step)
                week_ret = (exit_px / entry_px) - 1
                # Entry slippage for new positions
                if t in added and slippage > 0:
                    week_ret -= slippage
                port_ret += week_ret
                valid += 1
            if valid > 0:
                port_ret /= valid
            # Exit slippage for removed positions
            if slippage > 0 and removed and valid > 0:
                port_ret -= len(removed) * slippage / valid

        # ── ATR stop-loss + trailing stop check within the week ──
        if RC.BACKTEST_STOP_LOSS:
            for t in list(selected):
                h = histories.get(t)
                if h is None:
                    continue
                info = active_stops.get(t)
                if info is None:
                    continue
                triggered = False
                effective_stop = info["stop"]
                # Check daily bars within the week
                for d in range(i + 1, min(i + step + 1, len(h["low"]))):
                    # Update highest price with daily high
                    day_high = float(h["high"][d])
                    if day_high > info["high"]:
                        info["high"] = day_high
                    # Trailing stop: activate when profit >= ACTIVATE × ATR
                    if RC.BACKTEST_TRAILING_MULT > 0 and info["atr"] > 0:
                        profit = info["high"] - info["entry"]
                        if profit >= RC.BACKTEST_TRAILING_ACTIVATE * info["atr"]:
                            trailing_sl = info["high"] - RC.BACKTEST_TRAILING_MULT * info["atr"]
                            effective_stop = max(info["stop"], trailing_sl)
                    # Check if low breaches effective stop
                    if h["low"][d] < effective_stop:
                        bt_entry = _bt_entry_price(h, i)
                        actual_loss = (effective_stop / bt_entry) - 1
                        normal_ret = (_bt_exit_price(h, i, step) / bt_entry) - 1
                        is_trailing = effective_stop > info["stop"]

                        if normal_ret < actual_loss:
                            weight = scores_map.get(t, 1.0) if RC.SCORE_WEIGHTED_ALLOC else 1.0
                            total_w = sum(max(scores_map.get(s, 1.0), 0.01) for s in selected) if RC.SCORE_WEIGHTED_ALLOC else len(selected)
                            w_frac = max(weight, 0.01) / total_w if total_w > 0 else 1.0 / len(selected)
                            port_ret += (actual_loss - normal_ret) * w_frac
                            if is_trailing:
                                trailing_triggered_count += 1
                            else:
                                stop_triggered_count += 1

                        active_stops.pop(t, None)
                        triggered = True
                        break
                # Update effective stop in info if not triggered
                if not triggered and effective_stop > info["stop"]:
                    info["stop"] = effective_stop

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

    # ── Per-year statistics (Sharpe, win_rate, max_dd per year) ──
    from collections import defaultdict
    _yearly_weeks = defaultdict(list)  # year_str -> [(port_ret, spy_ret, qqq_ret), ...]
    for wd in weekly_details:
        yr = wd["date"][:4]
        _yearly_weeks[yr].append((
            wd["return_pct"] / 100.0,
            wd["spy_return_pct"] / 100.0,
            wd.get("qqq_return_pct", 0.0) / 100.0,
        ))
    yearly_stats = []
    for yr in sorted(_yearly_weeks.keys()):
        wk_list = _yearly_weeks[yr]
        n = len(wk_list)
        port_rets = [w[0] for w in wk_list]
        spy_rets = [w[1] for w in wk_list]
        qqq_rets = [w[2] for w in wk_list]
        yr_cum_port = float(np.prod([1 + r for r in port_rets]) - 1)
        yr_cum_spy = float(np.prod([1 + r for r in spy_rets]) - 1)
        yr_cum_qqq = float(np.prod([1 + r for r in qqq_rets]) - 1)
        yr_ann_ret = float((1 + yr_cum_port) ** (52 / n) - 1) if n > 0 else 0
        yr_ann_vol = float(np.std(port_rets) * np.sqrt(52)) if n > 1 else 0
        yr_sharpe = round(yr_ann_ret / yr_ann_vol, 2) if yr_ann_vol > 0 else 0
        yr_win = sum(1 for r in port_rets if r > 0)
        yr_max_dd = _max_drawdown(port_rets)
        yearly_stats.append({
            "year": yr if yr != str(date.today().year) else f"{yr} YTD",
            "strategy_return": round(yr_cum_port, 4),
            "spy_return": round(yr_cum_spy, 4),
            "qqq_return": round(yr_cum_qqq, 4),
            "annualized_return": round(yr_ann_ret, 4),
            "sharpe": yr_sharpe,
            "max_drawdown": round(yr_max_dd, 4),
            "win_rate": round(yr_win / n, 4) if n > 0 else 0,
            "weeks": n,
        })

    # Alpha enhancement stats
    alpha_enhancements = {
        "relative_strength_filter": RC.RELATIVE_STRENGTH_FILTER,
        "score_weighted_alloc": RC.SCORE_WEIGHTED_ALLOC,
        "sector_concentration_cap": RC.MAX_SECTOR_CONCENTRATION,
        "graduated_trend_bonus": RC.GRADUATED_TREND_BONUS,
        "stop_loss_simulation": RC.BACKTEST_STOP_LOSS,
        "dynamic_momentum_weights": True,
        "stop_triggered_count": stop_triggered_count,
        "trailing_triggered_count": trailing_triggered_count,
        "slippage_per_trade": RC.BACKTEST_SLIPPAGE,
        "min_avg_volume": RC.BACKTEST_MIN_AVG_VOL,
        "next_open_entry": RC.BACKTEST_NEXT_OPEN,
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
        "yearly_stats": yearly_stats,
        "regime_version": regime_version,
    }


async def run_parameter_optimization(
    start_date: str = "2023-04-01",
    end_date: str = "2026-03-01",
) -> dict:
    """
    Grid search over top_n × holding_bonus to find optimal parameter combination.
    Returns sorted results matrix with best combo highlighted.
    """
    logger.info(f"Starting parameter optimization: {start_date} to {end_date}")

    # Fetch data ONCE, share across all 25 parameter combos
    prefetched = await _fetch_backtest_data(start_date, end_date)
    if "error" in prefetched:
        return prefetched

    top_n_values = [2, 3, 4, 5, 6]
    bonus_values = [0, 0.25, 0.5, 0.75, 1.0]

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
    start_date: str = "2022-07-01",
    end_date: str = "2026-03-15",
    progress_callback=None,
) -> dict:
    """
    Walk-Forward Optimization: 月度自适应最优组合分析。
    1) 对25种参数组合各跑一次完整回测
    2) 按月切片，用前3个月训练窗口选最优参数
    3) 拼接自适应权益曲线，对比固定最优和SPY
    """
    from collections import defaultdict
    import math

    logger.info(f"Starting adaptive backtest: {start_date} to {end_date}")

    # Fetch data ONCE, share across all 25 parameter combos
    prefetched = await _fetch_backtest_data(start_date, end_date)
    if "error" in prefetched:
        return prefetched
    logger.info("Adaptive: data pre-fetched, running 25 parameter combos...")

    top_n_values = [2, 3, 4, 5, 6]
    bonus_values = [0, 0.25, 0.5, 0.75, 1.0]

    # ── Step 1: Run 25 full backtests (reusing pre-fetched data) ──
    all_results = {}  # (top_n, hb) -> backtest result dict
    total_combos = len(top_n_values) * len(bonus_values)
    combo_count = 0
    import time as _time
    step1_start = _time.time()
    for tn in top_n_values:
        for hb in bonus_values:
            combo_count += 1
            if progress_callback:
                progress_callback(f"回测组合 {combo_count}/{total_combos}（Top{tn}, 惯性{hb}）")
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

    if progress_callback:
        progress_callback(f"24组回测完成，正在进行月度Walk-Forward优化...")

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

        # Find best combo during training window (by Sharpe, not raw return)
        best_combo = None
        best_train_sharpe = -999
        for combo in all_results:
            # Collect all weekly returns in training window
            train_weekly_rets = []
            for tm in train_months:
                for wd in monthly_data[combo].get(tm, []):
                    train_weekly_rets.append(wd["return_pct"] / 100.0)
            if not train_weekly_rets:
                continue
            # Compute Sharpe-like metric for training window
            mean_ret = float(np.mean(train_weekly_rets))
            std_ret = float(np.std(train_weekly_rets))
            train_sharpe = (mean_ret / std_ret * math.sqrt(52)) if std_ret > 0 else 0
            if train_sharpe > best_train_sharpe:
                best_train_sharpe = train_sharpe
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
            "training_sharpe": round(best_train_sharpe, 2),
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
    universe = OFFENSIVE_ETFS + DEFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS + INVERSE_ETFS

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

async def _save_snapshot(snapshot: RotationSnapshot, trigger_source: str = "scheduler") -> str:
    """Save rotation snapshot to DB with trigger source tracking."""
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
            "trigger_source": trigger_source,
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
                row = {
                    "ticker": ticker,
                    "status": "pending_entry",
                }
                if snapshot_id:  # only include if valid UUID
                    row["snapshot_id"] = snapshot_id
                db.table("rotation_positions").insert(row).execute()
                logger.info(f"Created pending_entry position for {ticker}")
            except Exception as e:
                logger.error(f"Error creating position for {ticker}: {e}")

    # Close removed tickers via Tiger sell order (if active with quantity)
    for ticker in removed:
        active = [p for p in existing if p["ticker"] == ticker and p["status"] == "active"]
        for pos in active:
            pos_qty = int(pos.get("quantity", 0) or 0)
            current_price = float(pos.get("current_price", 0) or 0)
            try:
                await _close_position(
                    pos["id"],
                    reason="rotation_removal",
                    exit_price=current_price if current_price > 0 else None,
                    ticker=ticker,
                    quantity=pos_qty,
                )
                logger.info(
                    f"Rotation removal: {ticker} qty={pos_qty} "
                    f"exit_price=${current_price:.2f} → Tiger MKT SELL queued"
                )
                # Send exit notification
                try:
                    from app.services.notification_service import notify_rotation_exit
                    signal = DailyTimingSignal(
                        ticker=ticker,
                        signal_type="exit",
                        trigger_conditions=[
                            f"rotation removal: dropped from top {RC.TOP_N}",
                        ],
                        current_price=current_price,
                        entry_price=float(pos.get("entry_price", 0) or 0),
                        exit_reason="rotation_removal",
                    )
                    await notify_rotation_exit(signal)
                except Exception:
                    pass  # notification failure is non-critical
            except Exception as e:
                logger.error(f"Error closing position for {ticker}: {e}")


async def _activate_position(
    position_id: str, entry_price: float, atr: float,
    stop_loss: float, take_profit: float, ticker: str = ""
):
    """Activate a pending_entry position and place Tiger buy order."""
    try:
        db = get_db()
        update_data = {
            "status": "active",
            "entry_price": entry_price,
            "entry_date": date.today().isoformat(),
            "atr14": round(atr, 4),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "current_price": entry_price,
            "unrealized_pnl_pct": 0.0,
        }

        # --- Tiger Order Execution (MKT, no bracket legs) ---
        try:
            from app.services.order_service import (
                get_tiger_trade_client, calculate_position_size,
            )
            tiger = get_tiger_trade_client()
            qty = await calculate_position_size(tiger, entry_price, max_positions=RC.TOP_N)
            if qty > 0:
                result = await tiger.place_buy_order(
                    ticker, qty, order_type="MKT",
                )
                if result:
                    update_data["quantity"] = qty
                    order_id_str = str(result.get("id") or result.get("order_id", ""))
                    update_data["tiger_order_id"] = order_id_str
                    update_data["tiger_order_status"] = "submitted"
                    logger.info(f"[TIGER-TRADE] MKT BUY {qty}x {ticker} "
                                f"SL=${stop_loss:.2f} TP=${take_profit:.2f} "
                                f"order_id={result.get('order_id')}")

                    # Immediately poll fill price — MKT orders typically fill within seconds
                    async def _poll_fill_price(pos_id: str, oid: str, atr_val: float):
                        await asyncio.sleep(5)
                        try:
                            fill_info = await tiger.get_order_status(int(oid))
                            if fill_info and "FILLED" in str(fill_info.get("status", "")).upper():
                                fp = float(fill_info.get("avg_fill_price") or 0)
                                if fp > 0:
                                    fill_update: dict = {
                                        "entry_price": round(fp, 4),
                                        "current_price": round(fp, 4),
                                        "tiger_order_status": "filled",
                                    }
                                    if atr_val > 0:
                                        fill_update["stop_loss"] = round(fp - RC.ATR_STOP_MULTIPLIER * atr_val, 2)
                                        fill_update["take_profit"] = round(fp + RC.ATR_TARGET_MULTIPLIER * atr_val, 2)
                                    get_db().table("rotation_positions").update(fill_update).eq("id", pos_id).execute()
                                    logger.info(f"[TIGER-TRADE] {ticker} immediate fill confirmed @ ${fp:.2f}")
                        except Exception as pe:
                            logger.debug(f"[TIGER-TRADE] Immediate fill poll skipped: {pe}")

                    asyncio.create_task(_poll_fill_price(position_id, order_id_str, atr))
                else:
                    logger.warning(f"[TIGER-TRADE] BUY order failed for {ticker}, position still activated")
            else:
                logger.warning(f"[TIGER-TRADE] Position size = 0 for {ticker} @ ${entry_price:.2f}")
        except Exception as te:
            logger.error(f"[TIGER-TRADE] Order error for {ticker}: {te}")
            # Don't block activation — signal is still valid

        db.table("rotation_positions").update(update_data).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error activating position: {e}")


async def _update_position_price(position_id: str, price: float, pnl_pct: float,
                                 highest_price: float = None):
    """Update current price, unrealized P&L, and highest price for trailing stop."""
    try:
        db = get_db()
        update_data = {
            "current_price": price,
            "unrealized_pnl_pct": round(pnl_pct, 4),
        }
        if highest_price is not None:
            update_data["highest_price"] = round(highest_price, 2)
        db.table("rotation_positions").update(update_data).eq("id", position_id).execute()
    except Exception as e:
        logger.error(f"Error updating position price: {e}")


async def _close_position(
    position_id: str, reason: str, exit_price: float = None,
    ticker: str = "", quantity: int = 0
):
    """Close a position and place Tiger sell order.
    If a Tiger sell order is placed, set status=pending_exit first;
    sync_tiger_orders will finalize to closed once the sell is filled.
    """
    try:
        db = get_db()
        update = {
            "status": "closed",
            "exit_reason": reason,
            "exit_date": date.today().isoformat(),
        }
        if exit_price:
            update["exit_price"] = exit_price

        # --- Tiger Sell Order ---
        if ticker and quantity > 0:
            try:
                from app.services.order_service import get_tiger_trade_client
                tiger = get_tiger_trade_client()
                result = await tiger.place_sell_order(ticker, quantity)  # market order
                if result:
                    update["tiger_exit_order_id"] = str(
                        result.get("id") or result.get("order_id", "")
                    )
                    update["status"] = "pending_exit"  # will be finalized by sync
                    logger.info(f"[TIGER-TRADE] SELL {quantity}x {ticker} "
                                f"reason={reason} order_id={result.get('order_id')}")
                else:
                    logger.warning(f"[TIGER-TRADE] SELL order failed for {ticker}")
            except Exception as te:
                logger.error(f"[TIGER-TRADE] Sell order error for {ticker}: {te}")

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


# ============================================================
# 5. INTRADAY PRICE SCAN — full watchlist live quotes
# ============================================================

# Module-level cache for intraday scan results (avoids blocking the UI)
_intraday_scan_cache: dict = {}
_scan_cache_db_checked: bool = False  # prevent repeated Supabase queries

_SCAN_CACHE_DB_KEY = "intraday_scan_cache"


def _persist_scan_cache(data: dict) -> None:
    """Persist intraday scan cache to Supabase (survives deploys)."""
    try:
        db = get_db()
        db.table("cache_store").upsert({
            "key": _SCAN_CACHE_DB_KEY,
            "value": data,
        }).execute()
        logger.info(f"Scan cache persisted to Supabase ({data.get('total', 0)} tickers)")
    except Exception as e:
        logger.warning(f"Scan cache persist failed: {e}")


def _load_scan_cache_from_db() -> dict:
    """Load intraday scan cache from Supabase (instant, no API calls).
    Only queries DB once — subsequent calls return cached result."""
    global _intraday_scan_cache, _scan_cache_db_checked
    if _intraday_scan_cache:
        return _intraday_scan_cache
    if _scan_cache_db_checked:
        return {}
    _scan_cache_db_checked = True
    try:
        from datetime import datetime, timezone
        db = get_db()
        result = db.table("cache_store").select("value, updated_at").eq(
            "key", _SCAN_CACHE_DB_KEY
        ).execute()
        if result.data:
            row = result.data[0]
            updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
            if age_hours < 24:  # 24h TTL — stale data better than no data
                _intraday_scan_cache = row["value"]
                logger.info(
                    f"Scan cache loaded from Supabase: {_intraday_scan_cache.get('total', 0)} tickers "
                    f"(age={age_hours:.1f}h)"
                )
                return _intraday_scan_cache
            else:
                logger.info(f"Scan cache in Supabase expired (age={age_hours:.1f}h)")
    except Exception as e:
        logger.warning(f"Scan cache DB load failed: {e}")
    return {}


async def run_intraday_price_scan() -> dict:
    """
    Fetch live GLOBAL_QUOTE for the full watchlist (180+ tickers).
    Uses 5-min quote TTL in AV client, so results refresh automatically.
    Runs as a background task; result stored in _intraday_scan_cache.

    Returns dict with:
        scan_time, total, alerts, results (list sorted by change% desc)
    """
    global _intraday_scan_cache

    logger.info("Starting Intraday Price Scan (full watchlist)")

    universe = (
        OFFENSIVE_ETFS + DEFENSIVE_ETFS + LARGECAP_STOCKS +
        MIDCAP_STOCKS + INVERSE_ETFS
    )
    ticker_info = {item["ticker"]: item for item in universe}

    # Get active & pending positions for stop-loss/take-profit context
    positions: list[dict] = []
    try:
        positions = await get_current_positions()
    except Exception as e:
        logger.warning(f"Intraday scan: could not load positions: {e}")
    position_map = {p["ticker"]: p for p in positions}

    av = get_av_client()
    results = []
    failed = 0

    # 并发批量获取报价（替代逐个顺序调用，180 tickers: 144s → ~15s）
    all_tickers = list(ticker_info.keys())
    quotes_map = await av.batch_get_quotes(all_tickers)

    for ticker, item in ticker_info.items():
        try:
            quote = quotes_map.get(ticker)
            if not quote:
                failed += 1
                continue

            price = float(quote.get("latest_price") or 0)
            change_pct = float(quote.get("change_percent") or 0)
            volume = int(quote.get("volume") or 0)
            prev_close = float(quote.get("prev_close") or 0)

            # Position context
            pos = position_map.get(ticker)
            is_held = pos is not None
            stop_loss_breach = False
            take_profit_breach = False
            pnl_pct = None
            entry_price = None
            stop_loss = None
            take_profit = None

            if pos:
                entry_price = float(pos.get("entry_price") or 0)
                stop_loss = float(pos.get("stop_loss") or 0)
                take_profit = float(pos.get("take_profit") or 0)
                if entry_price > 0 and price > 0:
                    pnl_pct = round((price / entry_price - 1) * 100, 2)
                if stop_loss > 0 and price < stop_loss:
                    stop_loss_breach = True
                if take_profit > 0 and price > take_profit:
                    take_profit_breach = True

            results.append({
                "ticker": ticker,
                "name": item.get("name", ""),
                "sector": item.get("sector", ""),
                "price": price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "volume": volume,
                "is_held": is_held,
                "pnl_pct": pnl_pct,
                "stop_loss_breach": stop_loss_breach,
                "take_profit_breach": take_profit_breach,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "status": pos.get("status") if pos else None,
            })
        except Exception as e:
            logger.warning(f"Intraday scan: quote failed for {ticker}: {e}")
            failed += 1

    # Sort: alerts → held positions → change% desc
    results.sort(key=lambda x: (
        -(1 if x["stop_loss_breach"] or x["take_profit_breach"] else 0),
        -x["is_held"],
        -x["change_pct"],
    ))

    eastern = pytz.timezone("US/Eastern")
    scan_time = datetime.now(eastern).strftime("%Y-%m-%d %H:%M ET")
    alerts = [r for r in results if r["stop_loss_breach"] or r["take_profit_breach"]]

    result = {
        "scan_time": scan_time,
        "total": len(results),
        "failed": failed,
        "alerts": len(alerts),
        "alert_tickers": [a["ticker"] for a in alerts],
        "results": results,
    }

    _intraday_scan_cache = result
    _persist_scan_cache(result)
    logger.info(
        f"Intraday scan complete: {len(results)} tickers, "
        f"{len(alerts)} alerts, {failed} failed"
    )
    return result


def get_intraday_prices() -> dict:
    """Return the last intraday scan result from cache (instant, no API calls).
    Falls back to Supabase if in-memory cache is empty (e.g. after deploy)."""
    if _intraday_scan_cache:
        return _intraday_scan_cache
    return _load_scan_cache_from_db()
