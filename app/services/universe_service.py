"""
StockQueen V5 - Dynamic Universe Service
Automatically filters the full US stock market to build the rotation candidate pool.
Uses Alpha Vantage LISTING_STATUS + daily history for screening.

Pipeline:
  Step 1: LISTING_STATUS → ~7000 → filter exchange/type/ipo → ~3000
  Step 2: Daily history (compact) → filter price>$5 & vol>500K → ~800
  Step 3: Company overview → filter market_cap>$500M → ~500

Designed for weekly refresh (e.g. Saturday 06:00 NZT).
"""

import asyncio
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

    async def refresh_universe(self, concurrency: int = 5) -> dict:
        """
        Full universe refresh with 3-step filtering pipeline.

        Args:
            concurrency: max concurrent AV API calls for Step 2/3.
                         Default 5 to stay well within 75 req/min limit.

        Returns:
            {"total_screened": int, "final_count": int, "tickers": list, ...}
        """
        from app.services.alphavantage_client import get_av_client
        av = get_av_client()

        t_start = time.time()
        logger.info("=" * 60)
        logger.info("Dynamic Universe Refresh — Starting")
        logger.info("=" * 60)

        # ── Step 1: LISTING_STATUS → basic filter ──
        listings = await av.get_listing_status()
        if not listings:
            logger.error("Failed to fetch LISTING_STATUS from Alpha Vantage")
            return {"error": "listing_status_failed"}

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

        logger.info(
            f"Step 1: {len(listings)} total listings → "
            f"{len(candidates)} candidates (NYSE/NASDAQ stocks, IPO before {cutoff_date})"
        )

        # ── Step 2: Price + Volume filter via daily history ──
        logger.info(f"Step 2: Checking price & volume for {len(candidates)} candidates "
                    f"(concurrency={concurrency})...")

        sem = asyncio.Semaphore(concurrency)
        step2_passed = []
        step2_lock = asyncio.Lock()
        step2_progress = {"done": 0, "passed": 0, "failed": 0}

        async def _check_price_volume(item):
            ticker = item["symbol"]
            async with sem:
                try:
                    hist = await av.get_history_arrays(ticker, days=30)
                    if hist is None or len(hist["close"]) < 10:
                        async with step2_lock:
                            step2_progress["failed"] += 1
                        return

                    vol_data = hist["volume"][-20:]
                    avg_vol = float(sum(vol_data) / len(vol_data))
                    current_price = float(hist["close"][-1])

                    if avg_vol >= self.min_avg_volume and current_price >= self.min_price:
                        item["_avg_vol"] = avg_vol
                        item["_price"] = current_price
                        async with step2_lock:
                            step2_passed.append(item)
                            step2_progress["passed"] += 1
                    else:
                        async with step2_lock:
                            step2_progress["failed"] += 1
                except Exception:
                    async with step2_lock:
                        step2_progress["failed"] += 1

                async with step2_lock:
                    step2_progress["done"] += 1
                    done = step2_progress["done"]
                    if done % 200 == 0 or done == len(candidates):
                        logger.info(
                            f"  Step 2 progress: {done}/{len(candidates)} "
                            f"(passed: {step2_progress['passed']})"
                        )

        tasks = [_check_price_volume(item) for item in candidates]
        await asyncio.gather(*tasks)

        logger.info(
            f"Step 2: {len(candidates)} → {len(step2_passed)} "
            f"(price>=${self.min_price}, vol>={self.min_avg_volume:,})"
        )

        # ── Step 3: Market cap filter via company overview ──
        logger.info(f"Step 3: Checking market cap for {len(step2_passed)} candidates...")

        final_tickers = []
        step3_lock = asyncio.Lock()
        step3_progress = {"done": 0, "passed": 0}

        async def _check_market_cap(item):
            ticker = item["symbol"]
            async with sem:
                try:
                    overview = await av.get_company_overview(ticker)
                    if overview is None:
                        return
                    # AV returns "MarketCapitalization" (full key) in overview
                    market_cap = float(
                        overview.get("market_cap")
                        or overview.get("MarketCapitalization")
                        or overview.get("MarketCap")
                        or 0
                    )
                    if market_cap >= self.min_market_cap:
                        entry = {
                            "ticker": ticker,
                            "name": item.get("name", ""),
                            "exchange": item.get("exchange", ""),
                            "ipoDate": item.get("ipoDate", ""),
                            "market_cap": market_cap,
                            "avg_volume": item.get("_avg_vol", 0),
                            "price": item.get("_price", 0),
                            "sector": overview.get("Sector") or overview.get("sector", ""),
                            "industry": overview.get("Industry") or overview.get("industry", ""),
                        }
                        async with step3_lock:
                            final_tickers.append(entry)
                            step3_progress["passed"] += 1
                except Exception:
                    pass

                async with step3_lock:
                    step3_progress["done"] += 1
                    done = step3_progress["done"]
                    if done % 100 == 0 or done == len(step2_passed):
                        logger.info(
                            f"  Step 3 progress: {done}/{len(step2_passed)} "
                            f"(passed: {step3_progress['passed']})"
                        )

        tasks = [_check_market_cap(item) for item in step2_passed]
        await asyncio.gather(*tasks)

        # Sort by market cap descending for consistent ordering
        final_tickers.sort(key=lambda x: x.get("market_cap", 0), reverse=True)

        elapsed = time.time() - t_start
        logger.info(
            f"Step 3: {len(step2_passed)} → {len(final_tickers)} "
            f"(market_cap>=${self.min_market_cap / 1e6:.0f}M)"
        )
        logger.info(f"Dynamic Universe Refresh complete: {len(final_tickers)} tickers in {elapsed:.0f}s")

        # ── Save to cache ──
        result = {
            "total_screened": len(listings),
            "step1_candidates": len(candidates),
            "step2_passed": len(step2_passed),
            "final_count": len(final_tickers),
            "tickers": final_tickers,
            "filters": {
                "min_market_cap": self.min_market_cap,
                "min_avg_volume": self.min_avg_volume,
                "min_listed_days": self.min_listed_days,
                "min_price": self.min_price,
            },
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 1),
        }

        # Date-stamped copy
        cache_path = os.path.join(_CACHE_DIR, f"universe_{datetime.now().strftime('%Y%m%d')}.json")
        self._save_json(cache_path, result)

        # Latest copy (used by get_current_universe)
        latest_path = os.path.join(_CACHE_DIR, "universe_latest.json")
        self._save_json(latest_path, result)

        # Sector summary
        sectors = {}
        for t in final_tickers:
            s = t.get("sector", "Unknown")
            sectors[s] = sectors.get(s, 0) + 1
        logger.info("Sector breakdown:")
        for s, c in sorted(sectors.items(), key=lambda x: -x[1]):
            logger.info(f"  {s}: {c}")

        return result

    async def get_pit_universe(self, as_of_year: int) -> set:
        """
        Point-in-Time Universe：返回 {as_of_year}-01-02 时真实上市的股票集合。
        专为 Walk-Forward 回测设计，消除 Future-IPO 幸存者偏差。

        只做 Step 1 过滤（交易所 + 上市年限），不做价格/成交量/市值过滤，
        避免对历史日期发起大量 API 调用。

        缓存到 .cache/universe/universe_pit_{YYYY}.json（永久有效，历史数据不变）。

        Args:
            as_of_year: 查询年份（如 2020 → 查询 2020-01-02 的上市状态）

        Returns:
            Set of ticker strings (NYSE + NASDAQ 股票，上市满 min_listed_days 天)
        """
        cache_path = os.path.join(_CACHE_DIR, f"universe_pit_{as_of_year}.json")

        # 历史数据不变，优先读缓存
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tickers = set(data.get("tickers", []))
                logger.info(f"PIT universe {as_of_year}: {len(tickers)} tickers (from cache)")
                return tickers
            except Exception as e:
                logger.warning(f"Failed to load PIT cache {as_of_year}: {e}")

        # 从 AV 拉取
        from app.services.alphavantage_client import get_av_client
        av = get_av_client()

        date_str = f"{as_of_year}-01-02"  # 避开元旦假期
        logger.info(f"Fetching PIT universe for {date_str} from AV LISTING_STATUS...")
        listings = await av.get_listing_status(date=date_str)
        if not listings:
            logger.error(f"PIT universe {as_of_year}: LISTING_STATUS returned empty")
            return set()

        cutoff = (
            datetime(as_of_year, 1, 2) - timedelta(days=self.min_listed_days)
        ).strftime("%Y-%m-%d")

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

        logger.info(f"PIT universe {as_of_year}: {len(tickers)} tickers (fetched from AV)")

        # 永久缓存（历史数据不会改变）
        self._save_json(cache_path, {
            "year": as_of_year,
            "as_of_date": date_str,
            "tickers": tickers,
            "count": len(tickers),
            "timestamp": datetime.now().isoformat(),
        })

        return set(tickers)

    def get_current_universe(self) -> list:
        """
        Return current dynamic universe tickers from cached file.
        Returns list of ticker strings, or empty list if not available.
        """
        latest_path = os.path.join(_CACHE_DIR, "universe_latest.json")
        try:
            if os.path.exists(latest_path):
                age_days = (time.time() - os.path.getmtime(latest_path)) / 86400
                if age_days > 8:
                    logger.warning(f"Universe cache is {age_days:.1f} days old, may be stale")

                with open(latest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tickers = [t["ticker"] for t in data.get("tickers", [])]
                logger.info(f"Dynamic universe loaded: {len(tickers)} tickers (age: {age_days:.1f}d)")
                return tickers
        except Exception as e:
            logger.warning(f"Failed to load dynamic universe: {e}")
        return []

    def get_current_universe_full(self) -> Optional[dict]:
        """
        Return full universe data (with sector/market_cap info).
        Returns the full cached dict, or None if not available.
        """
        latest_path = os.path.join(_CACHE_DIR, "universe_latest.json")
        try:
            if os.path.exists(latest_path):
                with open(latest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load universe data: {e}")
        return None

    def get_universe_items(self) -> list:
        """
        Return universe as list of dicts compatible with rotation_service format.
        Each item has: ticker, name, sector, ipoDate, market_cap, etc.
        Falls back to static watchlist if no dynamic universe available.
        """
        data = self.get_current_universe_full()
        if data and data.get("tickers"):
            items = []
            for t in data["tickers"]:
                items.append({
                    "ticker": t["ticker"],
                    "name": t.get("name", ""),
                    "sector": t.get("sector", "").lower().replace(" ", "_"),
                    "listed_since": t.get("ipoDate", ""),
                    "market_cap": t.get("market_cap", 0),
                })
            return items
        return []

    async def get_historical_universe(self, as_of_date: str) -> list:
        """
        Reconstruct historical universe for backtesting.
        Uses LISTING_STATUS with date parameter.
        Returns list of ticker strings that were listed and active on as_of_date.

        Note: This only does Step 1 filtering (exchange/type/ipo).
        Price/volume/market_cap filtering must be done in the backtest loop
        since we'd need historical data for those.
        """
        from app.services.alphavantage_client import get_av_client
        av = get_av_client()

        listings = await av.get_listing_status(date=as_of_date)
        if not listings:
            return []

        cutoff = (
            datetime.strptime(as_of_date, "%Y-%m-%d")
            - timedelta(days=self.min_listed_days)
        ).strftime("%Y-%m-%d")

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

    @staticmethod
    def _save_json(path: str, data: dict):
        """Save data to JSON file with error handling."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved: {path}")
        except Exception as e:
            logger.warning(f"Failed to save {path}: {e}")
