"""
StockQueen V5 - Dynamic Universe Service
Automatically filters the full US stock market to build the rotation candidate pool.
Uses Alpha Vantage LISTING_STATUS + daily history for screening.

Pipeline:
  Step 1: LISTING_STATUS → ~7000 → filter exchange/type/ipo → ~3000
  Step 2: Daily history (compact) → filter price>$5 & vol>500K → ~800
  Step 3: Company overview → filter market_cap>$500M → ~500

Results are persisted to Supabase (universe_snapshots table) so data
survives Render redeploys. Local .cache/ files are kept as L1 cache only.

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

# Local L1 cache (survives within a single Render instance lifetime)
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cache", "universe")
os.makedirs(_CACHE_DIR, exist_ok=True)
_LOCAL_LATEST = os.path.join(_CACHE_DIR, "universe_latest.json")

# In-process L0 cache (avoid re-querying Supabase on every request)
_MEM_CACHE: dict = {}       # {"data": {...}, "fetched_at": float}
_MEM_CACHE_TTL = 300        # 5 minutes


class UniverseService:
    """Dynamic stock universe builder with multi-step filtering."""

    def __init__(self):
        from app.config.rotation_watchlist import RotationConfig as RC
        self.min_market_cap = RC.UNIVERSE_MIN_MARKET_CAP
        self.min_avg_volume = RC.UNIVERSE_MIN_AVG_VOLUME
        self.min_listed_days = RC.UNIVERSE_MIN_LISTED_DAYS
        self.min_price = RC.UNIVERSE_MIN_PRICE

    @staticmethod
    def _normalize_sector(raw: str) -> str:
        from app.config.rotation_watchlist import normalize_sector
        return normalize_sector(raw)

    # ──────────────────────────────────────────────────────────
    # Public: refresh
    # ──────────────────────────────────────────────────────────

    async def refresh_universe(self, concurrency: int = 30) -> dict:
        """
        Full universe refresh with 3-step filtering pipeline.

        Args:
            concurrency: max concurrent Massive API calls for Step 2/3.
                         Default 30 (Massive 无严格限速，原 AV 限制为 5).

        Returns:
            {"total_screened": int, "final_count": int, "tickers": list, ...}
        """
        from app.services.massive_client import get_massive_client
        av = get_massive_client()

        t_start = time.time()
        logger.info("=" * 60)
        logger.info("Dynamic Universe Refresh — Starting")
        logger.info("=" * 60)

        # ── Step 1: LISTING_STATUS → basic filter ──
        # 双源 fallback: Massive (Polygon) → Alpha Vantage
        listings = await av.get_listing_status()
        if not listings:
            logger.warning("Massive LISTING_STATUS failed, falling back to Alpha Vantage...")
            try:
                from app.services.alphavantage_client import AlphaVantageClient
                av_fallback = AlphaVantageClient()
                listings = await av_fallback.get_listing_status()
            except Exception as e:
                logger.error(f"AV fallback also failed: {e}")
        if not listings:
            logger.error("Failed to fetch LISTING_STATUS from both Massive and AV")
            return {"error": "listing_status_failed (both sources)"}

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
                            "sector": self._normalize_sector(overview.get("Sector") or overview.get("sector", "")),
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

        logger.info(
            f"Step 3: {len(step2_passed)} → {len(final_tickers)} "
            f"(market_cap>=${self.min_market_cap / 1e6:.0f}M)"
        )

        # ── Step 4: 基本面质量门控 ──
        # 条件：最近4季中至少2季 EPS > 0，且最近2季中至少1季 OperatingCF > 0
        # 数据来源：Massive /vX/reference/financials（带磁盘缓存，不额外计费）
        step4_passed = final_tickers
        if RC.UNIVERSE_QUALITY_GATE:
            logger.info(f"Step 4: Quality gate for {len(final_tickers)} candidates...")
            step4_result = []
            step4_lock = asyncio.Lock()
            step4_progress = {"done": 0, "passed": 0, "no_data": 0, "failed": 0}

            async def _check_quality(entry):
                ticker = entry["ticker"]
                async with sem:
                    try:
                        earnings_data, cashflow_data = await asyncio.gather(
                            av.get_earnings(ticker),
                            av.get_cash_flow(ticker),
                            return_exceptions=True,
                        )
                        # 无数据 → 排除（保守原则）
                        if (isinstance(earnings_data, Exception) or not earnings_data
                                or isinstance(cashflow_data, Exception) or not cashflow_data):
                            async with step4_lock:
                                step4_progress["no_data"] += 1
                            return

                        # 条件1：最近4季 EPS > 0 的季数
                        e_quarters = earnings_data.get("quarterly", [])
                        eps_pos = sum(
                            1 for q in e_quarters[:4]
                            if q.get("reported_eps") is not None and q["reported_eps"] > 0
                        )
                        if eps_pos < RC.UNIVERSE_QUALITY_EPS_MIN_POSITIVE:
                            async with step4_lock:
                                step4_progress["failed"] += 1
                            return

                        # 条件2：最近2季 OperatingCF > 0 的季数
                        c_quarters = cashflow_data.get("quarterly", [])
                        cf_pos = sum(
                            1 for q in c_quarters[:2]
                            if q.get("operating_cashflow") is not None and q["operating_cashflow"] > 0
                        )
                        if cf_pos < RC.UNIVERSE_QUALITY_CF_MIN_POSITIVE:
                            async with step4_lock:
                                step4_progress["failed"] += 1
                            return

                        async with step4_lock:
                            step4_result.append(entry)
                            step4_progress["passed"] += 1

                    except Exception:
                        async with step4_lock:
                            step4_progress["no_data"] += 1
                    finally:
                        async with step4_lock:
                            step4_progress["done"] += 1
                            done = step4_progress["done"]
                            if done % 100 == 0 or done == len(final_tickers):
                                logger.info(
                                    f"  Step 4 progress: {done}/{len(final_tickers)} "
                                    f"(passed: {step4_progress['passed']}, "
                                    f"no_data: {step4_progress['no_data']}, "
                                    f"failed: {step4_progress['failed']})"
                                )

            await asyncio.gather(*[_check_quality(e) for e in final_tickers])
            step4_passed = step4_result
            step4_passed.sort(key=lambda x: x.get("market_cap", 0), reverse=True)
            logger.info(
                f"Step 4: {len(final_tickers)} → {len(step4_passed)} "
                f"(EPS≥{RC.UNIVERSE_QUALITY_EPS_MIN_POSITIVE}/4季, "
                f"CF≥{RC.UNIVERSE_QUALITY_CF_MIN_POSITIVE}/2季)"
            )

        elapsed = time.time() - t_start
        logger.info(f"Dynamic Universe Refresh complete: {len(step4_passed)} tickers in {elapsed:.0f}s")

        result = {
            "total_screened": len(listings),
            "step1_candidates": len(candidates),
            "step2_passed": len(step2_passed),
            "step3_passed": len(final_tickers),
            "final_count": len(step4_passed),
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

        # ── Persist: Supabase (primary) + local file (L1) ──
        self._save_to_supabase(result)
        self._save_local(result)

        # Sector summary
        sectors = {}
        for t in final_tickers:
            s = t.get("sector", "Unknown")
            sectors[s] = sectors.get(s, 0) + 1
        logger.info("Sector breakdown:")
        for s, c in sorted(sectors.items(), key=lambda x: -x[1]):
            logger.info(f"  {s}: {c}")

        return result

    # ──────────────────────────────────────────────────────────
    # Public: read
    # ──────────────────────────────────────────────────────────

    def get_current_universe_full(self) -> Optional[dict]:
        """
        Return full universe data (with sector/market_cap info).
        Read priority: L0 memory (5 min TTL) → Supabase → local .cache → None
        """
        global _MEM_CACHE
        # L0: in-process memory
        if _MEM_CACHE.get("data") and (time.time() - _MEM_CACHE.get("fetched_at", 0)) < _MEM_CACHE_TTL:
            return _MEM_CACHE["data"]

        # L1: Supabase (survives redeploys)
        data = self._load_from_supabase()
        if data:
            _MEM_CACHE = {"data": data, "fetched_at": time.time()}
            self._save_local(data)   # warm up local cache
            return data

        # L2: local file (only valid within this instance's lifetime)
        data = self._load_local()
        if data:
            _MEM_CACHE = {"data": data, "fetched_at": time.time()}
            return data

        return None

    def get_current_universe(self) -> list:
        """Return current dynamic universe as list of ticker strings."""
        data = self.get_current_universe_full()
        if data:
            tickers = [t["ticker"] for t in data.get("tickers", [])]
            logger.info(f"Dynamic universe loaded: {len(tickers)} tickers")
            return tickers
        logger.warning("Dynamic universe not available — returning empty list")
        return []

    def get_universe_items(self) -> list:
        """
        Return universe as list of dicts compatible with rotation_service format.
        Falls back to empty list if no dynamic universe available.
        """
        data = self.get_current_universe_full()
        if data and data.get("tickers"):
            items = []
            for t in data["tickers"]:
                items.append({
                    "ticker": t["ticker"],
                    "name": t.get("name", ""),
                    "sector": self._normalize_sector(t.get("sector", "")),
                    "listed_since": t.get("ipoDate", ""),
                    "market_cap": t.get("market_cap", 0),
                })
            return items
        return []

    def get_previous_snapshot(self) -> Optional[dict]:
        """Return the second-most-recent snapshot from Supabase (for change tracking)."""
        try:
            from app.database import get_db
            db = get_db()
            result = (
                db.table("universe_snapshots")
                .select("tickers, refreshed_at, final_count")
                .order("snapshot_date", desc=True)
                .limit(2)
                .execute()
            )
            rows = result.data or []
            if len(rows) >= 2:
                row = rows[1]
                tickers = row["tickers"]
                if isinstance(tickers, str):
                    tickers = json.loads(tickers)
                return {"tickers": tickers, "timestamp": row.get("refreshed_at", "")}
        except Exception as e:
            logger.warning(f"get_previous_snapshot failed: {e}")
        return None

    # ──────────────────────────────────────────────────────────
    # Point-in-time (Walk-Forward backtest)
    # ──────────────────────────────────────────────────────────

    async def get_pit_universe(self, as_of_year: int) -> set:
        """
        Point-in-Time Universe：返回 {as_of_year}-01-02 时真实上市的股票集合。
        专为 Walk-Forward 回测设计，消除 Future-IPO 幸存者偏差。
        缓存到本地文件（历史数据不变，永久有效）。
        """
        cache_path = os.path.join(_CACHE_DIR, f"universe_pit_{as_of_year}.json")

        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tickers = set(data.get("tickers", []))
                logger.info(f"PIT universe {as_of_year}: {len(tickers)} tickers (from cache)")
                return tickers
            except Exception as e:
                logger.warning(f"Failed to load PIT cache {as_of_year}: {e}")

        from app.services.alphavantage_client import get_av_client
        av = get_av_client()

        date_str = f"{as_of_year}-01-02"
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

        self._save_json(cache_path, {
            "year": as_of_year,
            "as_of_date": date_str,
            "tickers": tickers,
            "count": len(tickers),
            "timestamp": datetime.now().isoformat(),
        })

        return set(tickers)

    async def get_historical_universe(self, as_of_date: str) -> list:
        """Reconstruct historical universe for backtesting (Step 1 only)."""
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

    # ──────────────────────────────────────────────────────────
    # Private: Supabase persistence
    # ──────────────────────────────────────────────────────────

    def _save_to_supabase(self, result: dict):
        """Upsert latest snapshot into universe_snapshots table."""
        try:
            from app.database import get_db
            db = get_db()

            snapshot_date = result.get("timestamp", datetime.now().isoformat())[:10]

            # Clear old is_latest flag
            db.table("universe_snapshots").update({"is_latest": False}).eq("is_latest", True).execute()

            # Insert new snapshot
            row = {
                "snapshot_date": snapshot_date,
                "is_latest": True,
                "total_screened": result.get("total_screened"),
                "step1_candidates": result.get("step1_candidates"),
                "step2_passed": result.get("step2_passed"),
                "final_count": result.get("final_count", 0),
                "tickers": result.get("tickers", []),      # jsonb — pass native list, not json.dumps
                "filters": result.get("filters", {}),      # jsonb — pass native dict, not json.dumps
                "elapsed_seconds": result.get("elapsed_seconds"),
                "refreshed_at": result.get("timestamp", datetime.now().isoformat()),
            }
            db.table("universe_snapshots").insert(row).execute()
            logger.info(f"Universe snapshot saved to Supabase: {result.get('final_count')} tickers")
        except Exception as e:
            logger.error(f"Failed to save universe snapshot to Supabase: {e}")

    def _load_from_supabase(self) -> Optional[dict]:
        """Load the latest snapshot from Supabase."""
        try:
            from app.database import get_db
            db = get_db()
            result = (
                db.table("universe_snapshots")
                .select("*")
                .eq("is_latest", True)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            if not rows:
                # Fallback: get most recent by date
                result = (
                    db.table("universe_snapshots")
                    .select("*")
                    .order("snapshot_date", desc=True)
                    .limit(1)
                    .execute()
                )
                rows = result.data or []

            if rows:
                row = rows[0]
                tickers = row["tickers"]
                if isinstance(tickers, str):
                    tickers = json.loads(tickers)
                filters = row.get("filters") or {}
                if isinstance(filters, str):
                    filters = json.loads(filters)
                data = {
                    "total_screened": row.get("total_screened"),
                    "step1_candidates": row.get("step1_candidates"),
                    "step2_passed": row.get("step2_passed"),
                    "final_count": row.get("final_count", len(tickers)),
                    "tickers": tickers,
                    "filters": filters,
                    "elapsed_seconds": row.get("elapsed_seconds"),
                    "timestamp": (row.get("refreshed_at") or row.get("snapshot_date") or "")[:19],
                }
                logger.info(f"Universe loaded from Supabase: {data['final_count']} tickers")
                return data
        except Exception as e:
            logger.warning(f"Failed to load universe from Supabase: {e}")
        return None

    # ──────────────────────────────────────────────────────────
    # Private: local file cache
    # ──────────────────────────────────────────────────────────

    def _save_local(self, result: dict):
        """Save to local .cache/ (within-instance cache + dated archive)."""
        ts = result.get("timestamp", datetime.now().isoformat())[:10].replace("-", "")
        dated_path = os.path.join(_CACHE_DIR, f"universe_{ts}.json")
        self._save_json(dated_path, result)
        self._save_json(_LOCAL_LATEST, result)

    def _load_local(self) -> Optional[dict]:
        """Load from local .cache/universe_latest.json."""
        try:
            if os.path.exists(_LOCAL_LATEST):
                age_days = (time.time() - os.path.getmtime(_LOCAL_LATEST)) / 86400
                if age_days > 8:
                    logger.warning(f"Local universe cache is {age_days:.1f} days old, may be stale")
                with open(_LOCAL_LATEST, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"Universe loaded from local cache: {data.get('final_count')} tickers")
                return data
        except Exception as e:
            logger.warning(f"Failed to load local universe cache: {e}")
        return None

    @staticmethod
    def _save_json(path: str, data: dict):
        """Save data to JSON file with error handling."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved: {path}")
        except Exception as e:
            logger.warning(f"Failed to save {path}: {e}")
