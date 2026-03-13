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
    OFFENSIVE_ETFS, DEFENSIVE_ETFS, MIDCAP_STOCKS,
    get_offensive_tickers, get_defensive_tickers, get_ticker_info,
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

    # 2. Determine scoring universe
    if regime == "bear":
        universe = DEFENSIVE_ETFS
    else:
        universe = OFFENSIVE_ETFS + MIDCAP_STOCKS

    # 3. Score all tickers (with RAG adjustment)
    from app.services.knowledge_service import get_knowledge_service
    ks = get_knowledge_service()

    scores: list[RotationScore] = []
    for item in universe:
        score = await _score_ticker(item, regime, ks)
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
    """Detect bull/bear regime: SPY close vs MA50, 3-day confirmation."""
    data = await _fetch_history(RC.REGIME_TICKER, days=RC.REGIME_MA_PERIOD + 10)
    if not data:
        logger.warning("Cannot fetch SPY data for regime detection, defaulting to bull")
        return "bull"

    ma50 = _compute_ma(data["close"], RC.REGIME_MA_PERIOD)
    recent_closes = data["close"][-RC.REGIME_CONFIRM_DAYS:]

    above_count = sum(1 for c in recent_closes if c > ma50)
    below_count = sum(1 for c in recent_closes if c < ma50)

    if below_count >= RC.REGIME_CONFIRM_DAYS:
        return "bear"
    return "bull"


async def _score_ticker(item: dict, regime: str, ks=None) -> Optional[RotationScore]:
    """Compute momentum score for a single ticker, with optional RAG adjustment."""
    ticker = item["ticker"]
    data = await _fetch_history(ticker)
    if not data:
        return None

    closes = data["close"]

    ret_1w = _compute_return(closes, 5)
    ret_1m = _compute_return(closes, 21)
    ret_3m = _compute_return(closes, 63)
    vol = _compute_volatility(closes)
    ma20 = _compute_ma(closes, 20)
    above_ma20 = float(closes[-1]) > ma20

    raw_momentum = (RC.WEIGHT_1W * ret_1w +
                    RC.WEIGHT_1M * ret_1m +
                    RC.WEIGHT_3M * ret_3m)
    vol_penalty = RC.VOL_PENALTY * vol
    trend_bonus = RC.TREND_BONUS if above_ma20 else 0.0

    # RAG knowledge adjustment (Phase 3)
    rag_adj = 0.0
    if ks:
        try:
            rag_adj = await ks.get_rag_score_adjustment(ticker)
        except Exception:
            pass

    score = raw_momentum - vol_penalty + trend_bonus + rag_adj

    # Determine asset type
    t_set = {e["ticker"] for e in OFFENSIVE_ETFS}
    d_set = {e["ticker"] for e in DEFENSIVE_ETFS}
    if ticker in t_set:
        asset_type = "etf_offensive"
    elif ticker in d_set:
        asset_type = "etf_defensive"
    else:
        asset_type = "stock"

    return RotationScore(
        ticker=ticker,
        name=item.get("name", ""),
        asset_type=asset_type,
        sector=item.get("sector", ""),
        return_1w=ret_1w,
        return_1m=ret_1m,
        return_3m=ret_3m,
        volatility=vol,
        above_ma20=above_ma20,
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

async def run_rotation_backtest(
    start_date: str = "2024-01-01",
    end_date: str = "2026-03-01",
    top_n: int = RC.TOP_N,
    holding_bonus: float = RC.HOLDING_BONUS,
) -> dict:
    """
    Historical backtest of the rotation strategy.
    Returns weekly returns and summary statistics.
    """
    logger.info(f"Running rotation backtest: {start_date} to {end_date}, top {top_n}")

    # Fetch full history for all tickers via Alpha Vantage
    av = get_av_client()
    all_items = OFFENSIVE_ETFS + MIDCAP_STOCKS + DEFENSIVE_ETFS
    histories = {}
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
        except Exception:
            pass

    if not histories:
        return {"error": "No data fetched"}

    # Use SPY as benchmark
    spy_hist = histories.get("SPY")
    if not spy_hist:
        return {"error": "SPY data not available"}

    # Simulate week by week
    spy_dates = spy_hist["dates"]
    weekly_returns = []
    spy_weekly_returns = []
    holdings = []
    # 新增：逐周明细数据
    equity_curve = []
    trade_log = []
    weekly_details = []
    cum_port_val = 1.0
    cum_spy_val = 1.0
    prev_selected = []

    # Walk through time in weekly steps
    step = 5  # ~1 trading week
    for i in range(63, len(spy_dates) - step, step):
        # Determine regime at this point
        spy_closes_so_far = spy_hist["close"][:i + 1]
        ma50 = float(np.mean(spy_closes_so_far[-50:])) if len(spy_closes_so_far) >= 50 else 0
        regime = "bear" if spy_closes_so_far[-1] < ma50 else "bull"

        # Score tickers
        scored = []
        for ticker, h in histories.items():
            # Find matching date index
            h_dates = h["dates"]
            if i >= len(h["close"]):
                continue
            closes = h["close"][:i + 1]
            if len(closes) < 63:
                continue

            ret_1w = (closes[-1] / closes[-6]) - 1 if len(closes) > 6 else 0
            ret_1m = (closes[-1] / closes[-22]) - 1 if len(closes) > 22 else 0
            ret_3m = (closes[-1] / closes[-63]) - 1 if len(closes) > 63 else 0

            vol_arr = np.diff(closes[-22:]) / closes[-22:-1] if len(closes) > 22 else np.array([0])
            vol = float(np.std(vol_arr) * np.sqrt(252))
            ma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else 0

            raw_m = RC.WEIGHT_1W * ret_1w + RC.WEIGHT_1M * ret_1m + RC.WEIGHT_3M * ret_3m
            score = raw_m - RC.VOL_PENALTY * vol + (RC.TREND_BONUS if closes[-1] > ma20 else 0)

            # In bear regime, only score defensive
            is_defensive = ticker in [e["ticker"] for e in DEFENSIVE_ETFS]
            if regime == "bear" and not is_defensive:
                continue
            if regime == "bull" and is_defensive:
                continue

            scored.append((ticker, score))

        # Holding inertia: bonus for already-held tickers
        if holding_bonus > 0 and prev_selected:
            scored = [(t, sc + holding_bonus) if t in prev_selected else (t, sc)
                      for t, sc in scored]

        scored.sort(key=lambda x: x[1], reverse=True)
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
        prev_selected = selected[:]

        # Compute equal-weight return for next week
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

        spy_ret = (spy_hist["close"][i + step] / spy_hist["close"][i]) - 1
        weekly_returns.append(port_ret)
        spy_weekly_returns.append(spy_ret)

        # 累计净值
        cum_port_val *= (1 + port_ret)
        cum_spy_val *= (1 + spy_ret)
        equity_curve.append({
            "date": week_date,
            "portfolio": round(cum_port_val, 4),
            "spy": round(cum_spy_val, 4),
        })
        weekly_details.append({
            "date": week_date,
            "regime": regime,
            "holdings": selected,
            "return_pct": round(port_ret * 100, 2),
            "spy_return_pct": round(spy_ret * 100, 2),
            "cum_return": round((cum_port_val - 1) * 100, 2),
            "spy_cum_return": round((cum_spy_val - 1) * 100, 2),
        })

    if not weekly_returns:
        return {"error": "Insufficient data for backtest"}

    # Compute cumulative returns
    cum_port = float(np.prod([1 + r for r in weekly_returns]) - 1)
    cum_spy = float(np.prod([1 + r for r in spy_weekly_returns]) - 1)
    ann_ret = float((1 + cum_port) ** (52 / len(weekly_returns)) - 1) if weekly_returns else 0
    ann_vol = float(np.std(weekly_returns) * np.sqrt(52))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    max_dd = _max_drawdown(weekly_returns)

    win_weeks = sum(1 for r in weekly_returns if r > 0)
    win_rate = win_weeks / len(weekly_returns) if weekly_returns else 0

    return {
        "period": f"{start_date} to {end_date}",
        "weeks": len(weekly_returns),
        "top_n": top_n,
        "cumulative_return": round(cum_port, 4),
        "spy_cumulative_return": round(cum_spy, 4),
        "annualized_return": round(ann_ret, 4),
        "annualized_vol": round(ann_vol, 4),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "win_rate": round(win_rate, 4),
        "alpha_vs_spy": round(cum_port - cum_spy, 4),
        "equity_curve": equity_curve,
        "trades": trade_log,
        "weekly_details": weekly_details,
    }


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
    universe = OFFENSIVE_ETFS + DEFENSIVE_ETFS + MIDCAP_STOCKS

    scores = []
    for item in universe:
        score = await _score_ticker(item, regime, ks)
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
