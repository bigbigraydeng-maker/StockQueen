"""
StockQueen V5 - Dynamic Universe Refresh Script
================================================
Runs the 3-step filtering pipeline to build the dynamic stock universe.

Pipeline:
  Step 1: LISTING_STATUS → filter NYSE/NASDAQ stocks, IPO > 1yr → ~3000
  Step 2: Daily history   → filter price > $5, volume > 500K   → ~800
  Step 3: Company overview → filter market cap > $500M          → ~500

Usage:
    cd StockQueen
    python scripts/refresh_universe.py

Estimated time: 30-60 minutes (depends on AV API speed)
Output: .cache/universe/universe_latest.json
"""

import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    stream=sys.stdout,
)
# Reduce noise from sub-modules
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("refresh_universe")


async def main():
    logger.info("=" * 70)
    logger.info("StockQueen V5 — Dynamic Universe Refresh")
    logger.info("=" * 70)

    from app.services.universe_service import UniverseService
    svc = UniverseService()

    logger.info(f"Filters: market_cap >= ${svc.min_market_cap/1e6:.0f}M, "
                f"avg_vol >= {svc.min_avg_volume:,}, "
                f"price >= ${svc.min_price}, "
                f"listed >= {svc.min_listed_days} days")
    logger.info("")

    t0 = time.time()
    result = await svc.refresh_universe(concurrency=5)
    elapsed = time.time() - t0

    if "error" in result:
        logger.error(f"Universe refresh failed: {result['error']}")
        return

    logger.info("")
    logger.info("=" * 70)
    logger.info("Results Summary")
    logger.info("=" * 70)
    logger.info(f"Total screened:    {result.get('total_screened', 0):,}")
    logger.info(f"Step 1 (exchange): {result.get('step1_candidates', 0):,}")
    logger.info(f"Step 2 (vol+price):{result.get('step2_passed', 0):,}")
    logger.info(f"Step 3 (mkt cap):  {result.get('final_count', 0):,}")
    logger.info(f"Total time:        {elapsed:.0f}s")
    logger.info("")

    # Show top 20 by market cap
    tickers = result.get("tickers", [])
    if tickers:
        logger.info("Top 20 by market cap:")
        for i, t in enumerate(tickers[:20], 1):
            mcap_b = t.get("market_cap", 0) / 1e9
            logger.info(
                f"  {i:2d}. {t['ticker']:<6s} {t.get('name', '')[:30]:<30s} "
                f"${mcap_b:>8.1f}B  {t.get('sector', '')}"
            )

    # Compare with static watchlist
    from app.config.rotation_watchlist import (
        OFFENSIVE_ETFS, LARGECAP_STOCKS, MIDCAP_STOCKS
    )
    static_tickers = set(
        item["ticker"] for item in OFFENSIVE_ETFS + LARGECAP_STOCKS + MIDCAP_STOCKS
    )
    dynamic_tickers = set(t["ticker"] for t in tickers)

    new_tickers = dynamic_tickers - static_tickers
    removed_tickers = static_tickers - dynamic_tickers

    logger.info("")
    logger.info(f"Static watchlist:  {len(static_tickers)} tickers")
    logger.info(f"Dynamic universe:  {len(dynamic_tickers)} tickers")
    logger.info(f"New (not in static):     {len(new_tickers)}")
    logger.info(f"Removed (not in dynamic): {len(removed_tickers)}")

    if new_tickers:
        logger.info(f"Sample new tickers: {sorted(new_tickers)[:20]}")
    if removed_tickers:
        logger.info(f"Sample removed:     {sorted(removed_tickers)[:20]}")

    logger.info("")
    logger.info(f"Universe saved to: .cache/universe/universe_latest.json")


if __name__ == "__main__":
    asyncio.run(main())
