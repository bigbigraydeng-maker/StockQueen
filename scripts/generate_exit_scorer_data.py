#!/usr/bin/env python3
"""
generate_exit_scorer_data.py
────────────────────────────
Generates ML Exit Scorer training data by replaying the rotation backtest logic.
Uses AV API with a focused ~45-ticker universe (all ETFs + top 30 large caps).
~50 API calls total, completes in ~1 minute on AV paid plan.

Output: scripts/exit_scorer_training_data.csv  (~10K–20K rows)

Usage:
  python scripts/generate_exit_scorer_data.py
  python scripts/generate_exit_scorer_data.py --start 2021-01-01 --end 2026-03-01
"""

import csv
import sys
import time
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.services.rotation_service import (
    _compute_atr,
    _compute_rsi,
    DEFENSIVE_ETFS,
    INVERSE_ETFS,
    OFFENSIVE_ETFS,
    LARGECAP_STOCKS,
    RC,
)

# ── Universe (focused, ~45 tickers) ──────────────────────────────────────────
DEFENSIVE_TICKERS = [e["ticker"] for e in DEFENSIVE_ETFS]           # TLT, GLD, SHY
INVERSE_TICKERS   = [e["ticker"] for e in INVERSE_ETFS]             # SH, PSQ, RWM, DOG
OFFENSIVE_TICKERS = [e["ticker"] for e in OFFENSIVE_ETFS]           # SPY, QQQ, IWM...
LARGECAP_SAMPLE   = [e["ticker"] for e in LARGECAP_STOCKS[:100]]    # all 100 large caps

UNIVERSE = list(dict.fromkeys(
    ["SPY", "QQQ"]
    + DEFENSIVE_TICKERS
    + INVERSE_TICKERS
    + OFFENSIVE_TICKERS
    + LARGECAP_SAMPLE
))

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_START = "2022-01-01"
DEFAULT_END   = "2026-03-01"
TOP_N         = 6
STEP          = 5
OUTPUT_CSV    = ROOT / "scripts" / "exit_scorer_training_data.csv"

AV_KEY = os.getenv("ALPHA_VANTAGE_KEY", "O4HJD7GJ4LWSMHP5")
AV_BASE = "https://www.alphavantage.co/query"

# Label: will ATR trailing stop trigger within N trading days?
STOP_TRIGGER_WINDOW = 5   # look-ahead window (trading days)


# ── AV data fetch ─────────────────────────────────────────────────────────────

def fetch_av_daily(ticker: str) -> pd.DataFrame | None:
    """Fetch full daily OHLCV from Alpha Vantage (compact = last 100, full = 20+ years)."""
    params = {
        "function":   "TIME_SERIES_DAILY",
        "symbol":     ticker,
        "outputsize": "full",
        "apikey":     AV_KEY,
        "datatype":   "json",
    }
    try:
        r = requests.get(AV_BASE, params=params, timeout=30)
        data = r.json()
        ts = data.get("Time Series (Daily)")
        if not ts:
            return None
        df = pd.DataFrame.from_dict(ts, orient="index")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        df = df.rename(columns={
            "1. open":   "Open",
            "2. high":   "High",
            "3. low":    "Low",
            "4. close":  "Close",
            "5. volume": "Volume",
        })
        df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        return df
    except Exception as e:
        print(f"    [WARN] {ticker}: {e}")
        return None


def fetch_histories(tickers: list, start: str, end: str) -> dict:
    start_ts = pd.Timestamp(start) - pd.Timedelta(days=120)
    end_ts   = pd.Timestamp(end)   + pd.Timedelta(days=10)

    defensive_set = set(DEFENSIVE_TICKERS)
    inverse_set   = set(INVERSE_TICKERS)
    histories = {}

    print(f"  Downloading {len(tickers)} tickers via AV API ...")
    for idx, t in enumerate(tickers):
        df = fetch_av_daily(t)
        if df is None or len(df) < 63:
            print(f"    [{idx+1}/{len(tickers)}] {t}: no data, skip")
            continue

        df = df[(df.index >= start_ts) & (df.index <= end_ts)]
        if len(df) < 63:
            print(f"    [{idx+1}/{len(tickers)}] {t}: insufficient range, skip")
            continue

        sector = (
            "defensive" if t in defensive_set else
            "inverse"   if t in inverse_set   else
            "stock"
        )
        histories[t] = {
            "dates":  list(df.index),
            "close":  list(df["Close"]),
            "open":   list(df["Open"]),
            "high":   list(df["High"]),
            "low":    list(df["Low"]),
            "volume": list(df["Volume"]),
            "item":   {"ticker": t, "sector": sector},
        }

        print(f"    [{idx+1}/{len(tickers)}] {t}: {len(df)} rows ✓")

        # AV paid plan: 75 requests/min — 0.9s gap keeps us safely under limit
        if idx < len(tickers) - 1:
            time.sleep(0.9)

    print(f"  Got data for {len(histories)} / {len(tickers)} tickers")
    return histories


# ── Regime detection ──────────────────────────────────────────────────────────

def detect_regime(spy_closes: np.ndarray) -> str:
    if len(spy_closes) < 22:
        return "bull"
    ma50 = float(np.mean(spy_closes[-50:])) if len(spy_closes) >= 50 else float(spy_closes[-1])
    ma20 = float(np.mean(spy_closes[-20:]))
    cur  = float(spy_closes[-1])
    vol  = float(np.std(np.diff(spy_closes[-22:]) / spy_closes[-22:-1]) * np.sqrt(252))
    ret1 = float(cur / spy_closes[-22] - 1)

    rs = 0
    rs += 2 if cur > ma50 * 1.02 else (1 if cur > ma50 else (-2 if cur < ma50 * 0.98 else -1))
    rs += 1 if cur > ma20 else -1
    rs += (-1 if vol > 0.25 else (1 if vol < 0.12 else 0))
    rs += (1 if ret1 > 0.03 else (-1 if ret1 < -0.03 else 0))

    if rs >= 4:  return "strong_bull"
    if rs >= 1:  return "bull"
    if rs >= -1: return "choppy"
    return "bear"


def bt_entry_price(h: dict, i: int) -> float:
    opens = h.get("open", h["close"])
    if RC.BACKTEST_NEXT_OPEN and i + 1 < len(opens):
        return float(opens[i + 1])
    return float(h["close"][i])


def effective_stop(info: dict) -> float:
    stop = info["stop"]
    if RC.BACKTEST_TRAILING_MULT > 0 and info["atr"] > 0:
        profit = info["high"] - info["entry"]
        if profit >= RC.BACKTEST_TRAILING_ACTIVATE * info["atr"]:
            stop = max(stop, info["high"] - RC.BACKTEST_TRAILING_MULT * info["atr"])
    return stop


def will_profit_erode_via_trailing_stop(
    h: dict, info_snapshot: dict, from_day: int,
    window: int = 5, min_profit_pct: float = 0.5
) -> int:
    """
    Label = 1 ONLY when both conditions are met:
      1. Current position has unrealized profit >= min_profit_pct%  (profit to protect)
      2. The TRAILING stop (not fixed stop) triggers within `window` days  (profit gets eaten)

    Label = 0 in all other cases:
      - Position is flat or losing (fixed stop handles it, not Tranche B's job)
      - Trailing stop does NOT trigger in the window (hold is fine)
      - Only fixed stop triggers but trailing is inactive (still a loss scenario)

    This directly models Tranche B's mission: exit early to lock profits before
    the 1.5×ATR trailing drawdown eats them.
    """
    current_px = float(h["close"][from_day])
    entry      = info_snapshot["entry"]
    atr        = info_snapshot["atr"]

    # Condition 1: must have meaningful profit right now
    if atr <= 0 or (current_px - entry) / entry * 100 < min_profit_pct:
        return 0

    sim_high = info_snapshot["high"]
    sim_stop = info_snapshot["stop"]   # fixed stop baseline

    for fd in range(from_day + 1, min(from_day + window + 1, len(h["low"]))):
        day_high = float(h["high"][fd]) if fd < len(h["high"]) else float(h["close"][fd])
        if day_high > sim_high:
            sim_high = day_high

        # Is trailing stop active?
        trailing_stop = None
        profit_so_far = sim_high - entry
        if profit_so_far >= RC.BACKTEST_TRAILING_ACTIVATE * atr:
            trailing_stop = sim_high - RC.BACKTEST_TRAILING_MULT * atr

        eff = sim_stop if trailing_stop is None else max(sim_stop, trailing_stop)

        if float(h["low"][fd]) < eff:
            # Condition 2: only label=1 if TRAILING stop triggered (we had profit)
            if trailing_stop is not None and trailing_stop > sim_stop:
                return 1   # ✅ profit erosion — Tranche B should have exited
            return 0       # fixed stop hit (already a loss, not Tranche B's domain)

        if eff > sim_stop:
            sim_stop = eff

    return 0   # trailing stop NOT triggered in window → hold is correct


def etf_category(ticker: str) -> str:
    if ticker in set(INVERSE_TICKERS):   return "inverse"
    if ticker in set(DEFENSIVE_TICKERS): return "defensive"
    return "stock"


# ── Main simulation ───────────────────────────────────────────────────────────

def run(start_date: str, end_date: str) -> None:
    print(f"[1/4] Fetching data for {len(UNIVERSE)} tickers ...")
    histories = fetch_histories(UNIVERSE, start_date, end_date)

    spy_hist = histories.get("SPY")
    if not spy_hist:
        print("ERROR: SPY data missing")
        return

    spy_dates  = spy_hist["dates"]
    spy_closes = np.array(spy_hist["close"], dtype=float)

    defensive_set = set(DEFENSIVE_TICKERS)
    inverse_set   = set(INVERSE_TICKERS)
    offensive_set = set(OFFENSIVE_TICKERS)
    largecap_set  = set(LARGECAP_SAMPLE)

    _sd = pd.Timestamp(start_date)
    start_idx = 63
    for si, d in enumerate(spy_dates):
        if pd.Timestamp(d) >= _sd:
            start_idx = max(si, 63)
            break

    active_stops: dict  = {}
    prev_selected: list = []
    raw_snapshots: list = []

    print(f"\n[2/4] Simulating {start_date} → {end_date} ...")
    week_count = 0

    for i in range(start_idx, len(spy_dates) - STEP - 3, STEP):
        regime = detect_regime(spy_closes[:i + 1])

        scored = []
        for ticker, h in histories.items():
            if ticker in ("SPY", "QQQ"):
                continue
            if i >= len(h["close"]):
                continue
            closes = h["close"][:i + 1]
            if len(closes) < 63:
                continue

            is_defensive = ticker in defensive_set
            is_inverse   = ticker in inverse_set
            is_etf       = ticker in offensive_set
            is_largecap  = ticker in largecap_set
            is_midcap    = not is_defensive and not is_etf and not is_inverse and not is_largecap

            if regime == "bear" and not is_defensive and not is_inverse:
                continue
            if regime == "choppy" and (is_midcap or is_inverse):
                continue
            if regime in ("bull", "strong_bull") and (is_defensive or is_inverse):
                continue

            mom = float(closes[-1] / closes[-22] - 1) if len(closes) >= 22 else 0.0
            scored.append((ticker, mom))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [t for t, _ in scored[:TOP_N]]

        added   = [t for t in selected if t not in prev_selected]
        removed = [t for t in prev_selected if t not in selected]

        for t in added:
            h = histories.get(t)
            if not h or i >= len(h["close"]):
                continue
            entry_px = bt_entry_price(h, i)
            atr = _compute_atr(
                np.array(h["high"][:i + 1]),
                np.array(h["low"][:i + 1]),
                np.array(h["close"][:i + 1]),
            )
            active_stops[t] = {
                "entry": entry_px, "stop": entry_px - RC.BACKTEST_STOP_MULT * atr,
                "high": entry_px, "atr": atr, "entry_day_idx": i,
            }
        for t in removed:
            active_stops.pop(t, None)

        prev_selected = selected[:]

        for t in list(selected):
            h    = histories.get(t)
            info = active_stops.get(t)
            if not h or not info:
                continue

            entry_px = info["entry"]
            category = etf_category(t)

            for d in range(i + 1, min(i + STEP + 1, len(spy_closes) - 3)):
                if d >= len(h["close"]):
                    break

                current_px = float(h["close"][d])
                day_high   = float(h["high"][d]) if d < len(h["high"]) else current_px
                if day_high > info["high"]:
                    info["high"] = day_high

                peak_px   = info["high"]
                days_held = d - info["entry_day_idx"]

                unrealized = (current_px - entry_px) / entry_px * 100
                peak_pct   = (peak_px   - entry_px) / entry_px * 100
                drawdown   = (peak_px   - current_px) / entry_px * 100

                closes_d = np.array(h["close"][:d + 1])
                rsi_14   = _compute_rsi(closes_d, 14)
                ma5      = float(np.mean(closes_d[-5:])) if len(closes_d) >= 5 else current_px
                vs_ma5   = (current_px / ma5 - 1) * 100 if ma5 > 0 else 0.0
                spy_3d   = float(spy_closes[d] / spy_closes[d - 3] - 1) * 100 if d >= 3 else 0.0

                eff_stp   = effective_stop(info)
                atr_ratio = (current_px - eff_stp) / (info["atr"] * 1.5) if info["atr"] > 0 else 0.0

                date_str = (
                    str(spy_dates[d].date())
                    if hasattr(spy_dates[d], "date")
                    else str(spy_dates[d])[:10]
                )

                raw_snapshots.append({
                    "_d": d, "_t": t,
                    # frozen copy of stop state at this moment (for label computation)
                    "_info": {"high": info["high"], "stop": info["stop"],
                              "entry": info["entry"], "atr": info["atr"]},
                    "date":                   date_str,
                    "ticker":                 t,
                    "regime":                 regime,
                    "etf_category":           category,
                    "days_held":              days_held,
                    "unrealized_pnl_pct":     round(unrealized, 4),
                    "pnl_peak_pct":           round(peak_pct, 4),
                    "pnl_drawdown_from_peak": round(drawdown, 4),
                    "rsi_14":                 round(rsi_14, 2),
                    "price_vs_ma5_pct":       round(vs_ma5, 4),
                    "spy_3d_return_pct":      round(spy_3d, 4),
                    "atr_ratio":              round(atr_ratio, 4),
                })

                if (d < len(h["low"]) and float(h["low"][d]) < eff_stp) or current_px < eff_stp:
                    active_stops.pop(t, None)
                    break

        week_count += 1
        if week_count % 50 == 0:
            print(f"  {week_count} weeks | {len(raw_snapshots):,} snapshots ...")

    print(f"  Done: {week_count} weeks, {len(raw_snapshots):,} raw snapshots")

    print(f"[3/4] Computing labels (ATR stop trigger within {STOP_TRIGGER_WINDOW} days) ...")
    rows, skipped = [], 0

    for snap in raw_snapshots:
        t         = snap["_t"]
        d         = snap["_d"]
        info_snap = snap["_info"]
        h = histories.get(t)
        if not h or d + STOP_TRIGGER_WINDOW >= len(h["low"]):
            skipped += 1
            continue

        lbl = will_profit_erode_via_trailing_stop(h, info_snap, d, window=STOP_TRIGGER_WINDOW)
        # Keep forward_3d_return as informational (not used in training)
        fwd = (float(h["close"][d + 3]) / float(h["close"][d]) - 1) * 100 if d + 3 < len(h["close"]) else 0.0

        row = {k: v for k, v in snap.items() if not k.startswith("_")}
        row["forward_3d_return_pct"] = round(fwd, 4)   # informational only
        row["label"]                 = lbl
        rows.append(row)

    print(f"  Valid rows: {len(rows):,}  |  Skipped: {skipped:,}")

    print(f"[4/4] Writing → {OUTPUT_CSV} ...")
    if not rows:
        print("No data generated.")
        return

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    labels    = [r["label"] for r in rows]
    n_exit    = sum(labels)
    exit_rate = n_exit / len(labels)
    cats = {}
    regs = {}
    for r in rows:
        cats[r["etf_category"]] = cats.get(r["etf_category"], 0) + 1
        regs[r["regime"]]       = regs.get(r["regime"], 0) + 1
    unrl = [r["unrealized_pnl_pct"] for r in rows]
    draw = [r["pnl_drawdown_from_peak"] for r in rows]

    print(f"""
╔══════════════════════════════════════════════════════════╗
║          Exit Scorer Training Data — Summary             ║
╠══════════════════════════════════════════════════════════╣
║  Total rows    : {len(rows):>8,}                              ║
║  Label=1 (出场): {n_exit:>8,}  ({exit_rate:.1%})                  ║
║  Label=0 (持有): {len(rows)-n_exit:>8,}  ({1-exit_rate:.1%})                  ║
╠══════════════════════════════════════════════════════════╣
║  ETF categories : {cats}
║  Regime mix     : {regs}
╠══════════════════════════════════════════════════════════╣
║  Unrealized P&L : {min(unrl):.2f}% ~ {max(unrl):.2f}%  (mean {sum(unrl)/len(unrl):.2f}%)
║  Peak drawdown  : {min(draw):.2f}% ~ {max(draw):.2f}%  (mean {sum(draw)/len(draw):.2f}%)
╚══════════════════════════════════════════════════════════╝
✅  Saved → {OUTPUT_CSV}
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end",   default=DEFAULT_END)
    args = parser.parse_args()
    run(args.start, args.end)
