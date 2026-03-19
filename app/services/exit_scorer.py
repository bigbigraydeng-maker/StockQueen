"""
exit_scorer.py
──────────────
ML Exit Scorer — Signal Collection Mode (Phase 1)

Daily post-market inference for active positions:
  1. Load model from models/exit_scorer/exit_scorer.pkl
  2. Fetch live feature data for each active position
  3. Run inference → exit_probability
  4. Log signals to exit_scorer_signals table (NO trade execution)

Runs daily at 09:47 NZT (after daily_exit_check at 09:45).
"""

import json
import logging
import pickle
from datetime import date, datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent.parent.parent
MODEL_PATH = ROOT / "models" / "exit_scorer" / "exit_scorer.pkl"
FEAT_PATH  = ROOT / "models" / "exit_scorer" / "feature_names.json"

# Must match train_exit_scorer.py
THRESHOLD = 0.65
REGIME_MAP   = {"bear": 0, "choppy": 1, "bull": 2, "strong_bull": 3}
CATEGORY_MAP = {"defensive": 0, "inverse": 1, "stock": 2}


# ── Model loader (singleton) ──────────────────────────────────────────────────

_model = None
_feature_names = None


def _load_model():
    global _model, _feature_names
    if _model is not None:
        return _model, _feature_names

    if not MODEL_PATH.exists():
        logger.warning(f"Exit scorer model not found at {MODEL_PATH}. Run train_exit_scorer.py first.")
        return None, None

    with open(MODEL_PATH, "rb") as f:
        _model = pickle.load(f)

    if FEAT_PATH.exists():
        with open(FEAT_PATH, "r") as f:
            _feature_names = json.load(f)
    else:
        _feature_names = [
            "days_held", "unrealized_pnl_pct", "pnl_peak_pct",
            "pnl_drawdown_from_peak", "rsi_14", "price_vs_ma5_pct",
            "spy_3d_return_pct", "atr_ratio", "regime_code", "etf_type_code",
        ]

    logger.info(f"Exit scorer model loaded from {MODEL_PATH}")
    return _model, _feature_names


# ── Feature builder ───────────────────────────────────────────────────────────

def _etf_category(ticker: str, defensive_set: set, inverse_set: set) -> str:
    if ticker in inverse_set:
        return "inverse"
    if ticker in defensive_set:
        return "defensive"
    return "stock"


def _build_feature_row(
    pos: dict,
    closes: list,
    high_arr: list,
    low_arr: list,
    spy_closes: list,
    regime: str,
    etf_category: str,
) -> dict:
    """Compute all 10 features for one position snapshot."""
    closes_np  = np.array(closes, dtype=float)
    current_px = float(closes_np[-1])
    entry_px   = float(pos.get("entry_price", current_px))
    highest_px = float(pos.get("highest_price") or current_px)
    atr14      = float(pos.get("atr14") or 0)
    stop_loss  = float(pos.get("stop_loss") or 0)

    # days_held
    entry_date_raw = pos.get("entry_date")
    if entry_date_raw:
        try:
            if isinstance(entry_date_raw, str):
                entry_dt = date.fromisoformat(entry_date_raw[:10])
            else:
                entry_dt = entry_date_raw
            days_held = (date.today() - entry_dt).days
        except Exception:
            days_held = 0
    else:
        days_held = 0

    # P&L features
    unrealized_pct      = (current_px - entry_px) / entry_px * 100 if entry_px > 0 else 0.0
    peak_pct            = (highest_px - entry_px)   / entry_px * 100 if entry_px > 0 else 0.0
    drawdown_from_peak  = (highest_px - current_px) / entry_px * 100 if entry_px > 0 else 0.0

    # RSI-14
    from app.services.rotation_service import _compute_rsi
    rsi_14 = _compute_rsi(closes_np, 14)

    # Price vs MA5
    ma5 = float(np.mean(closes_np[-5:])) if len(closes_np) >= 5 else current_px
    price_vs_ma5 = (current_px / ma5 - 1) * 100 if ma5 > 0 else 0.0

    # SPY 3-day return
    spy_arr = np.array(spy_closes, dtype=float)
    spy_3d_ret = float(spy_arr[-1] / spy_arr[-4] - 1) * 100 if len(spy_arr) >= 4 else 0.0

    # ATR ratio: distance from effective stop, normalised
    from app.config.rotation_watchlist import RotationConfig as _RC
    rc = _RC
    effective_stop = stop_loss
    if atr14 > 0 and entry_px > 0:
        profit = highest_px - entry_px
        if profit >= rc.TRAILING_ACTIVATE_ATR * atr14:
            trailing_sl = highest_px - rc.TRAILING_STOP_ATR_MULT * atr14
            if trailing_sl > effective_stop:
                effective_stop = trailing_sl
    atr_ratio = (current_px - effective_stop) / (atr14 * 1.5) if atr14 > 0 else 0.0

    # Categorical codes
    regime_code   = REGIME_MAP.get(regime, 1)
    etf_type_code = CATEGORY_MAP.get(etf_category, 2)

    return {
        "days_held":              days_held,
        "unrealized_pnl_pct":     round(unrealized_pct, 4),
        "pnl_peak_pct":           round(peak_pct, 4),
        "pnl_drawdown_from_peak": round(drawdown_from_peak, 4),
        "rsi_14":                 round(rsi_14, 2),
        "price_vs_ma5_pct":       round(price_vs_ma5, 4),
        "spy_3d_return_pct":      round(spy_3d_ret, 4),
        "atr_ratio":              round(atr_ratio, 4),
        "regime_code":            regime_code,
        "etf_type_code":          etf_type_code,
    }


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _upsert_signal(row: dict) -> None:
    """Insert or update (on conflict date+ticker) a signal row."""
    from app.database import get_db
    try:
        db = get_db()
        db.table("exit_scorer_signals").upsert(
            row,
            on_conflict="date,ticker",
        ).execute()
    except Exception as e:
        logger.error(f"Error upserting exit_scorer_signals: {e}")


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_exit_scorer_signals() -> list[dict]:
    """
    Compute and log ML exit signals for all active positions.
    Returns list of signals where exit_prob >= THRESHOLD.
    """
    model, feature_names = _load_model()
    if model is None:
        logger.warning("Exit scorer model unavailable — skipping signal collection")
        return []

    from app.services.rotation_service import (
        _get_positions_by_status,
        _fetch_history,
        _detect_regime,
        DEFENSIVE_ETFS,
        INVERSE_ETFS,
    )

    positions = await _get_positions_by_status("active")
    if not positions:
        logger.info("Exit scorer: no active positions")
        return []

    # Pre-fetch SPY for SPY-3d-return feature
    spy_data = await _fetch_history("SPY", days=10)
    spy_closes = list(spy_data["close"]) if spy_data else []

    regime = await _detect_regime()

    defensive_set = {e["ticker"] for e in DEFENSIVE_ETFS}
    inverse_set   = {e["ticker"] for e in INVERSE_ETFS}

    today_str = date.today().isoformat()
    signals_fired = []

    for pos in positions:
        ticker = pos["ticker"]

        # Only score positions where Tranche B is "activated" (unrealized >= 0.5%)
        unrealized = float(pos.get("unrealized_pnl_pct") or 0)
        if unrealized < 0.5:
            logger.debug(f"Exit scorer: {ticker} unrealized={unrealized:.2f}% < 0.5% — skipping")
            continue

        data = await _fetch_history(ticker, days=30)
        if not data or len(data["close"]) < 10:
            logger.warning(f"Exit scorer: insufficient history for {ticker}")
            continue

        closes    = list(data["close"])
        high_arr  = list(data.get("high", closes))
        low_arr   = list(data.get("low",  closes))
        category  = _etf_category(ticker, defensive_set, inverse_set)

        try:
            feat = _build_feature_row(
                pos, closes, high_arr, low_arr, spy_closes, regime, category
            )
        except Exception as e:
            logger.error(f"Exit scorer: feature build failed for {ticker}: {e}")
            continue

        # Inference
        try:
            import pandas as pd
            X = pd.DataFrame([{k: feat[k] for k in feature_names}])
            exit_prob = float(model.predict_proba(X)[0, 1])
        except Exception as e:
            logger.error(f"Exit scorer: inference failed for {ticker}: {e}")
            continue

        signal_fired = exit_prob >= THRESHOLD

        row = {
            "date":                    today_str,
            "ticker":                  ticker,
            "exit_prob":               round(exit_prob, 4),
            "signal":                  signal_fired,
            "threshold":               THRESHOLD,
            "days_held":               feat["days_held"],
            "unrealized_pnl_pct":      feat["unrealized_pnl_pct"],
            "pnl_peak_pct":            feat["pnl_peak_pct"],
            "pnl_drawdown_from_peak":  feat["pnl_drawdown_from_peak"],
            "regime":                  regime,
            "etf_category":            category,
            "features_json":           feat,
        }

        await _upsert_signal(row)

        log_level = logger.warning if signal_fired else logger.info
        log_level(
            f"Exit scorer [{ticker}]: prob={exit_prob:.3f} "
            f"({'🔴 EXIT SIGNAL' if signal_fired else '🟢 hold'}) "
            f"unrealized={unrealized:.2f}% drawdown={feat['pnl_drawdown_from_peak']:.2f}%"
        )

        if signal_fired:
            signals_fired.append(row)

    logger.info(
        f"Exit scorer complete: {len(positions)} positions scored, "
        f"{len(signals_fired)} exit signals fired (threshold={THRESHOLD})"
    )
    return signals_fired
