"""
Universe A/B Test: Static Pool (493) vs Dynamic Pool (1578)
===========================================================

Fetches OHLCV data ONCE for the full dynamic pool (superset),
then runs the rotation backtest twice with different ticker subsets.

Usage:
    python scripts/universe_ab_test.py

Estimated time: ~25-30 min (OHLCV fetch) + ~5 min (backtests)
"""

import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.rotation_watchlist import (
    LARGECAP_STOCKS, MIDCAP_STOCKS, OFFENSIVE_ETFS, DEFENSIVE_ETFS, INVERSE_ETFS,
    RotationConfig as RC,
)
from app.services.alphavantage_client import get_av_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("universe_ab_test")


# ── Config ──────────────────────────────────────────────────────────
BACKTEST_START = "2020-01-01"
BACKTEST_END = "2026-03-01"
TOP_N = RC.TOP_N  # 6
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "stress_test_results")


async def fetch_all_ohlcv(all_tickers: list, start: str, end: str) -> dict:
    """Fetch OHLCV for all tickers. Returns {ticker: history_dict}."""
    av = get_av_client()
    histories = {}
    fetched = 0
    failed = 0
    total = len(all_tickers)

    for item in all_tickers:
        ticker = item["ticker"]
        try:
            hist = await av.get_daily_history_range(ticker, start, end)
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
            logger.debug(f"Failed {ticker}: {e}")

        done = fetched + failed
        if done % 50 == 0:
            pct = done / total * 100
            logger.info(f"OHLCV progress: {done}/{total} ({pct:.0f}%) — OK: {fetched}, fail: {failed}")

    logger.info(f"OHLCV complete: {fetched} OK, {failed} failed out of {total}")
    return histories


def filter_histories(histories: dict, allowed_tickers: set) -> dict:
    """Return subset of histories matching allowed_tickers."""
    return {k: v for k, v in histories.items() if k in allowed_tickers}


async def run_backtest_with_pool(
    pool_name: str,
    histories: dict,
    bt_fundamentals: dict,
    start: str,
    end: str,
    top_n: int,
) -> dict:
    """Run rotation backtest using pre-fetched data."""
    from app.services.rotation_service import run_rotation_backtest

    logger.info(f"Running {pool_name} backtest: {len(histories)} tickers, {start} to {end}")
    t0 = time.time()

    result = await run_rotation_backtest(
        start_date=start,
        end_date=end,
        top_n=top_n,
        _prefetched={"histories": histories, "bt_fundamentals": bt_fundamentals},
    )

    elapsed = time.time() - t0
    logger.info(f"{pool_name} backtest done in {elapsed:.1f}s")
    return result


def extract_metrics(result: dict) -> dict:
    """Extract key metrics from backtest result."""
    if "error" in result:
        return {"error": result["error"]}

    cum_ret = result.get("cumulative_return", 0)  # e.g. 1.35 = +35%
    spy_cum = result.get("spy_cumulative_return", 0)
    trades = result.get("trades", [])

    return {
        "total_return_pct": round(cum_ret * 100, 1),
        "annual_return_pct": round(result.get("annualized_return", 0) * 100, 1),
        "sharpe_ratio": result.get("sharpe_ratio", 0),
        "max_drawdown_pct": round(result.get("max_drawdown", 0) * 100, 1),
        "win_rate_pct": round(result.get("win_rate", 0) * 100, 1),
        "total_trades": len(trades),
        "spy_return_pct": round(spy_cum * 100, 1),
        "alpha_vs_spy_pct": round((cum_ret - spy_cum) * 100, 1),
        "weeks": result.get("weeks", 0),
    }


async def main():
    logger.info("=" * 70)
    logger.info("Universe A/B Test: Static Pool vs Dynamic Pool")
    logger.info("=" * 70)

    # ── 1. Build ticker lists ──
    static_pool = LARGECAP_STOCKS + MIDCAP_STOCKS
    static_tickers = {item["ticker"] for item in static_pool}
    etfs = OFFENSIVE_ETFS + DEFENSIVE_ETFS + INVERSE_ETFS
    etf_tickers = {item["ticker"] for item in etfs}

    # Dynamic pool from universe file
    univ_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "universe", "universe_latest.json")
    with open(univ_path, "r", encoding="utf-8") as f:
        univ_data = json.load(f)

    dynamic_items = univ_data["tickers"]
    dynamic_tickers = {t["ticker"] for t in dynamic_items}

    # Stats
    overlap = static_tickers & dynamic_tickers
    only_static = static_tickers - dynamic_tickers
    only_dynamic = dynamic_tickers - static_tickers

    logger.info(f"Static pool:  {len(static_tickers)} tickers")
    logger.info(f"Dynamic pool: {len(dynamic_tickers)} tickers")
    logger.info(f"Overlap:      {len(overlap)}")
    logger.info(f"Only static:  {len(only_static)} — {sorted(only_static)[:20]}...")
    logger.info(f"Only dynamic: {len(only_dynamic)}")
    logger.info(f"ETFs:         {len(etf_tickers)} (shared)")

    # ── 2. Fetch OHLCV for full superset (dynamic + ETFs + static-only) ──
    # Merge: dynamic pool is superset of most static, but some static may not be in dynamic
    all_items_map = {}
    for item in etfs:
        all_items_map[item["ticker"]] = item
    for item in dynamic_items:
        all_items_map[item["ticker"]] = item
    for item in static_pool:
        if item["ticker"] not in all_items_map:
            all_items_map[item["ticker"]] = item

    all_items = list(all_items_map.values())
    logger.info(f"Total tickers to fetch: {len(all_items)}")

    t_start = time.time()
    all_histories = await fetch_all_ohlcv(all_items, BACKTEST_START, BACKTEST_END)
    t_fetch = time.time() - t_start
    logger.info(f"Total fetch time: {t_fetch:.0f}s ({t_fetch/60:.1f}min)")

    # ── 3. Load fundamentals (from disk cache) ──
    bt_fundamentals = {}
    cache_dir = os.path.join(os.path.dirname(__file__), "..", ".cache", "av")
    if os.path.isdir(cache_dir):
        for fname in os.listdir(cache_dir):
            if fname.startswith("earnings_") and fname.endswith(".json"):
                ticker = fname.replace("earnings_", "").replace(".json", "")
                fpath = os.path.join(cache_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if ticker not in bt_fundamentals:
                        bt_fundamentals[ticker] = {}
                    bt_fundamentals[ticker]["earnings_data"] = data
                except Exception:
                    pass

            elif fname.startswith("cashflow_") and fname.endswith(".json"):
                ticker = fname.replace("cashflow_", "").replace(".json", "")
                fpath = os.path.join(cache_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if ticker not in bt_fundamentals:
                        bt_fundamentals[ticker] = {}
                    bt_fundamentals[ticker]["cashflow_data"] = data
                except Exception:
                    pass

        logger.info(f"Loaded {len(bt_fundamentals)} tickers with fundamental data from disk")

    # ── 4. Run backtests ──
    # Static pool histories
    static_allowed = static_tickers | etf_tickers
    static_histories = filter_histories(all_histories, static_allowed)

    # Dynamic pool histories
    dynamic_allowed = dynamic_tickers | etf_tickers
    dynamic_histories = filter_histories(all_histories, dynamic_allowed)

    logger.info(f"Static histories:  {len(static_histories)} tickers")
    logger.info(f"Dynamic histories: {len(dynamic_histories)} tickers")

    # Run baseline (static)
    static_result = await run_backtest_with_pool(
        "STATIC", static_histories, bt_fundamentals,
        BACKTEST_START, BACKTEST_END, TOP_N,
    )

    # Run dynamic
    dynamic_result = await run_backtest_with_pool(
        "DYNAMIC", dynamic_histories, bt_fundamentals,
        BACKTEST_START, BACKTEST_END, TOP_N,
    )

    # ── 5. Compare ──
    static_m = extract_metrics(static_result)
    dynamic_m = extract_metrics(dynamic_result)

    logger.info("")
    logger.info("=" * 70)
    logger.info("A/B TEST RESULTS")
    logger.info("=" * 70)
    logger.info(f"Period: {BACKTEST_START} to {BACKTEST_END}")
    logger.info(f"Static pool:  {len(static_tickers)} stocks")
    logger.info(f"Dynamic pool: {len(dynamic_tickers)} stocks")
    logger.info("")

    header = f"{'Metric':<25} {'Static':>12} {'Dynamic':>12} {'Delta':>12}"
    logger.info(header)
    logger.info("-" * 61)

    for key in ["total_return_pct", "annual_return_pct", "sharpe_ratio",
                "max_drawdown_pct", "win_rate_pct", "total_trades",
                "spy_return_pct", "alpha_vs_spy_pct"]:
        sv = static_m.get(key, 0)
        dv = dynamic_m.get(key, 0)
        delta = dv - sv
        sign = "+" if delta >= 0 else ""

        if key in ("total_return_pct", "annual_return_pct", "max_drawdown_pct",
                    "win_rate_pct", "alpha_vs_spy_pct", "spy_return_pct"):
            logger.info(f"{key:<25} {sv:>11.1f}% {dv:>11.1f}% {sign}{delta:>10.1f}%")
        elif key == "sharpe_ratio":
            logger.info(f"{key:<25} {sv:>12.2f} {dv:>12.2f} {sign}{delta:>11.2f}")
        else:
            logger.info(f"{key:<25} {sv:>12.0f} {dv:>12.0f} {sign}{delta:>11.0f}")

    # ── 6. Compare selected tickers ──
    logger.info("")
    logger.info("── Selected Ticker Analysis ──")

    static_trades = static_result.get("trades", [])
    dynamic_trades = dynamic_result.get("trades", [])

    # Each trade entry has 'holdings': [list of tickers held that week]
    static_unique = set()
    for t in static_trades:
        for ticker in t.get("holdings", []):
            static_unique.add(ticker)
    dynamic_unique = set()
    for t in dynamic_trades:
        for ticker in t.get("holdings", []):
            dynamic_unique.add(ticker)
    new_picks = dynamic_unique - static_unique

    logger.info(f"Static unique tickers held:    {len(static_unique)}")
    logger.info(f"Dynamic unique tickers held:   {len(dynamic_unique)}")
    logger.info(f"New tickers found by dynamic:  {len(new_picks)}")
    if new_picks:
        logger.info(f"New picks: {sorted(new_picks)[:30]}")
    logger.info(f"Static tickers:  {sorted(static_unique)}")
    logger.info(f"Dynamic tickers: {sorted(dynamic_unique)}")

    # ── 7. Save results ──
    os.makedirs(RESULTS_DIR, exist_ok=True)
    output = {
        "test_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backtest_period": {"start": BACKTEST_START, "end": BACKTEST_END},
        "pools": {
            "static_count": len(static_tickers),
            "dynamic_count": len(dynamic_tickers),
            "overlap": len(overlap),
            "only_static": len(only_static),
            "only_dynamic": len(only_dynamic),
            "static_with_data": len(static_histories),
            "dynamic_with_data": len(dynamic_histories),
        },
        "static_metrics": static_m,
        "dynamic_metrics": dynamic_m,
        "delta": {k: dynamic_m.get(k, 0) - static_m.get(k, 0)
                  for k in static_m if k != "error"},
        "new_tickers_traded": sorted(new_picks) if new_picks else [],
        "static_tickers_traded": sorted(static_unique),
        "dynamic_tickers_traded": sorted(dynamic_unique),
        "fetch_time_sec": t_fetch,
    }

    out_path = os.path.join(RESULTS_DIR, "universe_ab_test_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"\nResults saved to: {out_path}")

    # Final verdict
    logger.info("")
    sharpe_delta = dynamic_m.get("sharpe_ratio", 0) - static_m.get("sharpe_ratio", 0)
    ret_delta = dynamic_m.get("total_return_pct", 0) - static_m.get("total_return_pct", 0)

    if sharpe_delta > 0.1 and ret_delta > 0:
        logger.info("✅ VERDICT: Dynamic pool WINS — higher Sharpe AND returns")
    elif sharpe_delta > 0.1:
        logger.info("⚠️ VERDICT: Dynamic pool improves Sharpe but not returns")
    elif ret_delta > 5:
        logger.info("⚠️ VERDICT: Dynamic pool improves returns but not Sharpe")
    else:
        logger.info("❌ VERDICT: Dynamic pool shows no significant improvement")


if __name__ == "__main__":
    asyncio.run(main())
