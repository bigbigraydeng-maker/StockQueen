"""
StockQueen V5 - Dynamic Universe Service
Automatically filters the full US stock market to build the rotation candidate pool.
Uses Alpha Vantage LISTING_STATUS + daily history for screening.
"""

import logging
import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Cache directory
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cache", "universe")
os.makedirs(_CACHE_DIR, exist_ok=True)


class UniverseService:
    """Dynamic stock universe builder with multi-step filtering."""

    def __init__(self):
        from app.config.rotation_watchlist import RotationConfig as RC
        self.min_market_cap = RC.UNIVERSE_MIN_MARKET_CAP
        self.min_avg_volume = RC.UNIVERSE_MIN_AVG_VOLUME
        self.min_listed_days = RC.UNIVERSE_MIN_LISTED_DAYS
        self.min_price = RC.UNIVERSE_MIN_PRICE

    async def refresh_universe(self) -> dict:
        """
        Full universe refresh. Run weekly (Saturday 06:00 NZT).
        3-step filtering pipeline:
        1. LISTING_STATUS -> ~7000 stocks -> filter exchange/type/ipo -> ~3000
        2. Daily history (compact) -> filter price>$5 & vol>500K -> ~800
        3. Company overview -> filter market_cap>$500M -> ~500

        Returns: {"total_screened": int, "passed": int, "tickers": list, "timestamp": str}
        """
        from app.services.alphavantage_client import get_av_client
        av = get_av_client()

        logger.info("=" * 50)
        logger.info("Starting Dynamic Universe Refresh")
        logger.info("=" * 50)

        # Step 1: Get all active US listings
        listings = await av.get_listing_status()
        if not listings:
            logger.error("Failed to fetch listing status")
            return {"error": "listing_status_failed"}

        # Filter: NYSE/NASDAQ stocks only, listed > min_days
        cutoff_date = (datetime.now() - timedelta(days=self.min_listed_days)).strftime("%Y-%m-%d")
        candidates = []
        for row in listings:
            if row.get("assetType") != "Stock":
                continue
            if row.get("exchange") not in ("NYSE", "NASDAQ"):
                continue
            ipo_date = row.get("ipoDate", "")
            if not ipo_date or ipo_date > cutoff_date:
                continue
            candidates.append(row)

        logger.info(f"Step 1: {len(listings)} total -> {len(candidates)} candidates (exchange+type+ipo filter)")

        # Step 2: Check price and volume via daily history
        step2_passed = []
        step2_count = 0
        for item in candidates:
            ticker = item["symbol"]
            step2_count += 1
            if step2_count % 100 == 0:
                logger.info(f"  Step 2 progress: {step2_count}/{len(candidates)}")
            try:
                hist = await av.get_history_arrays(ticker, days=30)
                if hist is None or len(hist["close"]) < 10:
                    continue
                avg_vol = float(sum(hist["volume"][-20:]) / min(20, len(hist["volume"])))
                current_price = float(hist["close"][-1])
                if avg_vol >= self.min_avg_volume and current_price >= self.min_price:
                    item["_avg_vol"] = avg_vol
                    item["_price"] = current_price
                    step2_passed.append(item)
            except Exception:
                continue

        logger.info(f"Step 2: {len(candidates)} -> {len(step2_passed)} (price>=${self.min_price}, vol>={self.min_avg_volume})")

        # Step 3: Check market cap via company overview
        final_tickers = []
        step3_count = 0
        for item in step2_passed:
            ticker = item["symbol"]
            step3_count += 1
            if step3_count % 50 == 0:
                logger.info(f"  Step 3 progress: {step3_count}/{len(step2_passed)}")
            try:
                overview = await av.get_company_overview(ticker)
                if overview is None:
                    continue
                market_cap = float(overview.get("market_cap") or overview.get("MarketCap") or 0)
                if market_cap >= self.min_market_cap:
                    final_tickers.append({
                        "ticker": ticker,
                        "name": item.get("name", ""),
                        "exchange": item.get("exchange", ""),
                        "ipoDate": item.get("ipoDate", ""),
                        "market_cap": market_cap,
                        "avg_volume": item.get("_avg_vol", 0),
                        "price": item.get("_price", 0),
                        "sector": overview.get("sector", ""),
                    })
            except Exception:
                continue

        logger.info(f"Step 3: {len(step2_passed)} -> {len(final_tickers)} (market_cap>={self.min_market_cap / 1e6:.0f}M)")

        # Save to cache
        result = {
            "total_screened": len(listings),
            "step1_candidates": len(candidates),
            "step2_passed": len(step2_passed),
            "final_count": len(final_tickers),
            "tickers": final_tickers,
            "timestamp": datetime.now().isoformat(),
        }

        cache_path = os.path.join(_CACHE_DIR, f"universe_{datetime.now().strftime('%Y%m%d')}.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info(f"Universe cached: {cache_path} ({len(final_tickers)} tickers)")
        except Exception as e:
            logger.warning(f"Failed to cache universe: {e}")

        # Also save a "latest" copy
        latest_path = os.path.join(_CACHE_DIR, "universe_latest.json")
        try:
            with open(latest_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save latest universe: {e}")

        logger.info(f"Dynamic Universe Refresh complete: {len(final_tickers)} tickers")
        return result

    async def get_current_universe(self) -> list:
        """
        Return current dynamic universe tickers.
        Reads from latest cached file.
        Returns list of ticker strings, or empty list if not available.
        """
        latest_path = os.path.join(_CACHE_DIR, "universe_latest.json")
        try:
            if os.path.exists(latest_path):
                # Check freshness (max 8 days old)
                age_days = (time.time() - os.path.getmtime(latest_path)) / 86400
                if age_days > 8:
                    logger.warning(f"Universe cache is {age_days:.1f} days old, may be stale")

                with open(latest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tickers = [t["ticker"] for t in data.get("tickers", [])]
                logger.info(f"Dynamic universe loaded: {len(tickers)} tickers")
                return tickers
        except Exception as e:
            logger.warning(f"Failed to load dynamic universe: {e}")
        return []

    async def get_historical_universe(self, as_of_date: str) -> list:
        """
        Reconstruct historical universe for backtesting.
        Uses LISTING_STATUS with date parameter.
        Returns list of ticker strings that were listed and active on as_of_date.
        """
        from app.services.alphavantage_client import get_av_client
        av = get_av_client()

        listings = await av.get_listing_status(date=as_of_date)
        if not listings:
            return []

        # Basic filter: exchange + type + ipo date
        cutoff = (datetime.strptime(as_of_date, "%Y-%m-%d") - timedelta(days=self.min_listed_days)).strftime("%Y-%m-%d")
        tickers = []
        for row in listings:
            if row.get("assetType") != "Stock":
                continue
            if row.get("exchange") not in ("NYSE", "NASDAQ"):
                continue
            ipo_date = row.get("ipoDate", "")
            if not ipo_date or ipo_date > cutoff:
                continue
            tickers.append(row["symbol"])

        return tickers
