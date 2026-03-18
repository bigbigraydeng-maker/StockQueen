"""
StockQueen V2.3 - Alpha Vantage Market Data Client
Centralized replacement for yfinance.

API Endpoints used:
  - TIME_SERIES_DAILY (up to 20y of daily OHLCV)
  - GLOBAL_QUOTE     (real-time snapshot)

Rate limit: 25 requests/day on free tier, 75/min on premium.
Built-in in-memory cache to minimize API calls within a session.
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional, Dict, List

import httpx
import pandas as pd
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient:
    """
    Centralized Alpha Vantage data client.
    Provides the same data shapes that yfinance used to return.
    Two-tier cache: in-memory (fast) + disk JSON (survives restarts).
    """

    # Disk cache directory — can be overridden via AV_CACHE_DIR env var
    # On Render: set AV_CACHE_DIR=/var/cache/av (persistent disk mounted at /var/cache)
    # Locally: defaults to <project_root>/.cache/av
    _DISK_CACHE_DIR = os.environ.get(
        "AV_CACHE_DIR",
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            ".cache", "av"
        )
    )
    # Prefixes that should be persisted to disk (slow-changing data)
    _DISK_PREFIXES = ("overview:", "earnings:", "cashflow:", "income:", "daily:")
    _DISK_TTL = 86400 * 3      # 3 days for fundamental data on disk
    _DISK_TTL_OHLCV = 86400 * 7  # 7 days for OHLCV full history (historical dates don't change)

    def __init__(self):
        self.api_key = getattr(settings, "alpha_vantage_key", None) or ""
        # In-memory cache: ticker -> (timestamp, DataFrame/dict)
        self._daily_cache: Dict[str, tuple] = {}
        self._quote_cache: Dict[str, tuple] = {}
        self._cache_ttl = 3600  # 1 hour — OHLCV history data changes slowly
        self._quote_ttl = 300   # 5 minutes — real-time quotes for intraday use
        self._request_delay = 0.8  # seconds between requests (75 req/min safe)
        self._last_request_time = 0.0
        self._throttle_lock = asyncio.Lock()
        self._http_client: Optional[httpx.AsyncClient] = None

        # Warm up from disk cache on startup
        self._load_disk_cache()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _throttle(self):
        """Ensure minimum delay between API requests (lock-protected for concurrency)."""
        async with self._throttle_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._request_delay:
                await asyncio.sleep(self._request_delay - elapsed)
            self._last_request_time = time.time()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create a shared httpx client for connection pooling."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def _api_call(self, params: dict) -> Optional[dict]:
        """Make a single API request with throttle and error handling."""
        if not self.api_key:
            logger.error("Alpha Vantage API key not configured")
            return None

        params["apikey"] = self.api_key
        await self._throttle()

        try:
            client = await self._get_http_client()
            resp = await client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            # Check for API error messages
            if "Error Message" in data:
                logger.error(f"Alpha Vantage error: {data['Error Message']}")
                return None
            if "Note" in data:
                logger.warning(f"Alpha Vantage rate limit: {data['Note']}")
                return None
            if "Information" in data:
                logger.warning(f"Alpha Vantage info: {data['Information']}")
                return None

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"Alpha Vantage HTTP error: {e}")
            return None
        except Exception as e:
            logger.error(f"Alpha Vantage request error: {e}")
            return None

    def _is_cache_valid(self, cache_entry: Optional[tuple], ttl: Optional[float] = None) -> bool:
        """Check if a cache entry is still valid."""
        if not cache_entry:
            return False
        timestamp, _ = cache_entry
        return (time.time() - timestamp) < (ttl if ttl is not None else self._cache_ttl)

    # ------------------------------------------------------------------
    # Disk cache for fundamental data (survives server restarts)
    # ------------------------------------------------------------------

    def _load_disk_cache(self):
        """Load persisted fundamental + OHLCV data from disk into memory cache."""
        if not os.path.isdir(self._DISK_CACHE_DIR):
            return
        loaded_fund = 0
        loaded_ohlcv = 0
        now = time.time()
        for fname in os.listdir(self._DISK_CACHE_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(self._DISK_CACHE_DIR, fname)
            try:
                # OHLCV 文件：daily_TICKER_full.json
                if fname.startswith("daily_") and fname.endswith("_full.json"):
                    ticker = fname[6:-10]  # strip "daily_" and "_full.json"
                    entry = self._load_ohlcv_from_disk(ticker)
                    if entry:
                        disk_key = f"daily:{ticker}:full"
                        mem_key = f"{ticker}:full"
                        self._daily_cache[disk_key] = entry
                        self._daily_cache[mem_key] = entry
                        loaded_ohlcv += 1
                    continue

                # 基本面数据文件（原有逻辑）
                with open(fpath, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                ts = entry.get("ts", 0)
                if now - ts > self._DISK_TTL:
                    continue
                cache_key = entry.get("key", "")
                data = entry.get("data")
                if cache_key and data is not None:
                    self._daily_cache[cache_key] = (ts, data)
                    loaded_fund += 1
            except Exception:
                pass
        if loaded_fund or loaded_ohlcv:
            logger.info(f"AV disk cache: loaded {loaded_fund} fundamental + {loaded_ohlcv} OHLCV entries")

    def _save_to_disk(self, cache_key: str, data, ts: float):
        """Persist a cache entry to disk if it's a fundamental data type."""
        if not any(cache_key.startswith(p) for p in self._DISK_PREFIXES):
            return
        try:
            os.makedirs(self._DISK_CACHE_DIR, exist_ok=True)
            safe_name = cache_key.replace(":", "_").replace("/", "_") + ".json"
            fpath = os.path.join(self._DISK_CACHE_DIR, safe_name)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump({"key": cache_key, "ts": ts, "data": data}, f,
                          ensure_ascii=False, default=str)
        except Exception as e:
            logger.debug(f"Failed to save disk cache for {cache_key}: {e}")

    def _save_ohlcv_to_disk(self, ticker: str, df: "pd.DataFrame", ts: float):
        """
        将 OHLCV DataFrame 持久化到磁盘。
        格式：{ts, rows: [[date_str, open, high, low, close, volume], ...]}
        文件名：daily_AAPL_full.json
        """
        try:
            os.makedirs(self._DISK_CACHE_DIR, exist_ok=True)
            fpath = os.path.join(self._DISK_CACHE_DIR, f"daily_{ticker}_full.json")
            rows = [
                [str(idx.date()), row["Open"], row["High"], row["Low"], row["Close"], int(row["Volume"])]
                for idx, row in df.iterrows()
            ]
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump({"ticker": ticker, "ts": ts, "rows": rows}, f)
            logger.debug(f"OHLCV disk cache saved: {ticker} ({len(rows)} rows)")
        except Exception as e:
            logger.debug(f"Failed to save OHLCV disk cache for {ticker}: {e}")

    def _load_ohlcv_from_disk(self, ticker: str) -> Optional[tuple]:
        """
        从磁盘加载 OHLCV 缓存，返回 (timestamp, DataFrame) 或 None。
        """
        fpath = os.path.join(self._DISK_CACHE_DIR, f"daily_{ticker}_full.json")
        if not os.path.isfile(fpath):
            return None
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                entry = json.load(f)
            ts = entry.get("ts", 0)
            if time.time() - ts > self._DISK_TTL_OHLCV:
                return None  # 过期（7天）
            rows = entry.get("rows", [])
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
            df["Date"] = pd.to_datetime(df["Date"])
            df.set_index("Date", inplace=True)
            df.sort_index(inplace=True)
            return (ts, df)
        except Exception as e:
            logger.debug(f"Failed to load OHLCV disk cache for {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # Public API: Daily OHLCV History
    # ------------------------------------------------------------------

    async def get_daily_history(
        self, ticker: str, days: int = 100, outputsize: str = "compact"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch daily OHLCV data for a ticker.

        Args:
            ticker: Stock ticker symbol (e.g. "AAPL")
            days: Number of trading days to return (max ~100 for compact, ~5000 for full)
            outputsize: "compact" (last 100 days) or "full" (up to 20 years)

        Returns:
            DataFrame with columns: Open, High, Low, Close, Volume
            Index: DatetimeIndex
            Sorted oldest → newest (same as yfinance convention).
            None on failure.
        """
        # Check cache
        cache_key = f"{ticker}:{outputsize}"
        if self._is_cache_valid(self._daily_cache.get(cache_key)):
            _, df = self._daily_cache[cache_key]
            return df.tail(days).copy() if days < len(df) else df.copy()

        # If we need more than 100 days, switch to full
        if days > 100 and outputsize == "compact":
            outputsize = "full"
            cache_key = f"{ticker}:full"
            if self._is_cache_valid(self._daily_cache.get(cache_key)):
                _, df = self._daily_cache[cache_key]
                return df.tail(days).copy() if days < len(df) else df.copy()

        # --- 磁盘缓存检查（仅 full 模式，覆盖多年历史） ---
        disk_key = f"daily:{ticker}:full"
        if outputsize == "full":
            disk_entry = self._daily_cache.get(disk_key)
            if disk_entry:
                ts_disk, df_disk = disk_entry
                if (time.time() - ts_disk) < self._DISK_TTL_OHLCV:
                    self._daily_cache[cache_key] = disk_entry  # 同步到内存key
                    return df_disk.tail(days).copy() if days < len(df_disk) else df_disk.copy()

        data = await self._api_call({
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker,
            "outputsize": outputsize,
        })

        if not data:
            return None

        ts_key = "Time Series (Daily)"
        if ts_key not in data:
            logger.warning(f"No daily data for {ticker}: keys={list(data.keys())}")
            return None

        ts = data[ts_key]
        if not ts:
            return None

        # Parse into DataFrame
        rows = []
        for date_str, values in ts.items():
            rows.append({
                "Date": pd.Timestamp(date_str),
                "Open": float(values["1. open"]),
                "High": float(values["2. high"]),
                "Low": float(values["3. low"]),
                "Close": float(values["4. close"]),
                "Volume": int(float(values["5. volume"])),
            })

        df = pd.DataFrame(rows)
        df.set_index("Date", inplace=True)
        df.sort_index(inplace=True)  # oldest first

        # 写入内存缓存
        ts_now = time.time()
        self._daily_cache[cache_key] = (ts_now, df)

        # full 模式额外持久化到磁盘（覆盖历史数据，下次启动无需 API 调用）
        if outputsize == "full":
            self._daily_cache[disk_key] = (ts_now, df)
            self._save_ohlcv_to_disk(ticker, df, ts_now)

        return df.tail(days).copy() if days < len(df) else df.copy()

    async def get_daily_history_range(
        self, ticker: str, start: str, end: str
    ) -> Optional[pd.DataFrame]:
        """
        Fetch daily OHLCV data for a date range.

        Args:
            ticker: Stock ticker symbol
            start: Start date "YYYY-MM-DD"
            end: End date "YYYY-MM-DD"

        Returns:
            DataFrame with OHLCV, filtered to the date range.
        """
        # Always use full output to cover arbitrary date ranges
        df = await self.get_daily_history(ticker, days=5000, outputsize="full")
        if df is None or df.empty:
            return None

        mask = (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))
        filtered = df.loc[mask]
        return filtered if not filtered.empty else None

    # ------------------------------------------------------------------
    # Public API: Real-Time Quote
    # ------------------------------------------------------------------

    async def get_quote(self, ticker: str) -> Optional[dict]:
        """
        Get real-time quote snapshot for a ticker.

        Returns dict with keys:
            ticker, prev_close, open, high, low, latest_price,
            change_percent, volume, data_source
        """
        # Check cache (5-min TTL for real-time quotes)
        if self._is_cache_valid(self._quote_cache.get(ticker), ttl=self._quote_ttl):
            _, quote = self._quote_cache[ticker]
            return quote

        data = await self._api_call({
            "function": "GLOBAL_QUOTE",
            "symbol": ticker,
        })

        if not data or "Global Quote" not in data:
            return None

        gq = data["Global Quote"]
        if not gq or "05. price" not in gq:
            return None

        try:
            latest_price = float(gq.get("05. price", 0))
            prev_close = float(gq.get("08. previous close", 0))
            change_pct_str = gq.get("10. change percent", "0%").replace("%", "")
            change_pct = float(change_pct_str) if change_pct_str else 0.0

            quote = {
                "ticker": ticker,
                "prev_close": prev_close,
                "open": float(gq.get("02. open", 0)),
                "high": float(gq.get("03. high", 0)),
                "low": float(gq.get("04. low", 0)),
                "latest_price": latest_price,
                "change_percent": change_pct,
                "volume": int(float(gq.get("06. volume", 0))),
                "avg_volume_30d": 0,  # Not available in GLOBAL_QUOTE
                "market_cap": 0,      # Not available in GLOBAL_QUOTE
                "data_source": "alpha_vantage",
            }

            self._quote_cache[ticker] = (time.time(), quote)
            return quote

        except (ValueError, KeyError) as e:
            logger.error(f"Error parsing Alpha Vantage quote for {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # Public API: Batch Operations
    # ------------------------------------------------------------------

    async def _get_quote_no_throttle(self, ticker: str, _retry: int = 0) -> Optional[dict]:
        """Get quote without throttle — for use in small concurrent batches.
        Retries once after a short delay if rate-limited by AV."""
        if self._is_cache_valid(self._quote_cache.get(ticker), ttl=self._quote_ttl):
            _, quote = self._quote_cache[ticker]
            return quote

        if not self.api_key:
            return None

        try:
            client = await self._get_http_client()
            resp = await client.get(_BASE_URL, params={
                "function": "GLOBAL_QUOTE",
                "symbol": ticker,
                "apikey": self.api_key,
            })
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Alpha Vantage request error for {ticker}: {e}")
            return None

        if "Error Message" in data or "Note" in data or "Information" in data:
            # Rate-limited — retry once after backoff
            if _retry < 1:
                await asyncio.sleep(3.0)
                return await self._get_quote_no_throttle(ticker, _retry=_retry + 1)
            logger.warning(f"AV rate-limited for {ticker} after retry")
            return None
        if not data or "Global Quote" not in data:
            return None

        gq = data["Global Quote"]
        if not gq or "05. price" not in gq:
            return None

        try:
            quote = {
                "ticker": ticker,
                "prev_close": float(gq.get("08. previous close", 0)),
                "open": float(gq.get("02. open", 0)),
                "high": float(gq.get("03. high", 0)),
                "low": float(gq.get("04. low", 0)),
                "latest_price": float(gq.get("05. price", 0)),
                "change_percent": float(gq.get("10. change percent", "0%").replace("%", "") or 0),
                "volume": int(float(gq.get("06. volume", 0))),
                "avg_volume_30d": 0,
                "market_cap": 0,
                "data_source": "alpha_vantage",
            }
            self._quote_cache[ticker] = (time.time(), quote)
            return quote
        except (ValueError, KeyError) as e:
            logger.error(f"Error parsing quote for {ticker}: {e}")
            return None

    async def batch_get_quotes(self, tickers: List[str]) -> Dict[str, dict]:
        """
        Get quotes for multiple tickers.
        Cached quotes return instantly; uncached ones are fetched
        concurrently (no per-request throttle for small batches).
        """
        # Separate cached vs uncached
        results = {}
        uncached = []
        for ticker in tickers:
            if self._is_cache_valid(self._quote_cache.get(ticker), ttl=self._quote_ttl):
                _, quote = self._quote_cache[ticker]
                results[ticker] = quote
            else:
                uncached.append(ticker)

        if not uncached:
            return results

        # Stagger requests to avoid AV burst rate-limiting.
        # Process in mini-batches of 5 with 0.3s gap between batches.
        if len(uncached) <= 50:
            batch_sz = 5
            for i in range(0, len(uncached), batch_sz):
                chunk = uncached[i:i + batch_sz]
                tasks = [self._get_quote_no_throttle(t) for t in chunk]
                chunk_results = await asyncio.gather(*tasks)
                for ticker, quote in zip(chunk, chunk_results):
                    if quote:
                        results[ticker] = quote
                if i + batch_sz < len(uncached):
                    await asyncio.sleep(0.3)
        else:
            # Large batch (>50): use no-throttle with semaphore to stay under AV rate limit
            # 10 concurrent × ~0.3s/req ≈ 33 req/s peak, well under 75/min with backoff
            sem = asyncio.Semaphore(10)
            async def _fetch(t: str):
                async with sem:
                    q = await self._get_quote_no_throttle(t)
                    return t, q
            # Process in chunks of 50 with small gaps to avoid burst rate-limiting
            for i in range(0, len(uncached), 50):
                chunk = uncached[i:i + 50]
                batch_results = await asyncio.gather(*[_fetch(t) for t in chunk])
                for ticker, quote in batch_results:
                    if quote:
                        results[ticker] = quote
                if i + 50 < len(uncached):
                    await asyncio.sleep(1.0)  # 1s gap between 50-ticker chunks
        return results

    async def batch_get_daily_history(
        self, tickers: List[str], days: int = 30
    ) -> Dict[str, pd.DataFrame]:
        """
        Get daily history for multiple tickers.
        Sequential calls with throttling.
        """
        results = {}
        for i, ticker in enumerate(tickers):
            try:
                df = await self.get_daily_history(ticker, days=days)
                if df is not None and not df.empty:
                    results[ticker] = df

                if (i + 1) % 10 == 0:
                    logger.info(
                        f"Alpha Vantage batch progress: {i + 1}/{len(tickers)} "
                        f"({len(results)} successful)"
                    )
            except Exception as e:
                logger.error(f"Alpha Vantage batch error for {ticker}: {e}")

        logger.info(
            f"Alpha Vantage batch total: {len(results)}/{len(tickers)} tickers successful"
        )
        return results

    # ------------------------------------------------------------------
    # Technical Indicators
    # ------------------------------------------------------------------

    async def get_rsi(self, ticker: str, period: int = 14) -> Optional[float]:
        """Fetch latest RSI value."""
        data = await self._api_call({
            "function": "RSI",
            "symbol": ticker,
            "interval": "daily",
            "time_period": period,
            "series_type": "close",
        })
        if not data:
            return None
        ta = data.get("Technical Analysis: RSI", {})
        if not ta:
            return None
        latest = next(iter(ta.values()), {})
        try:
            return float(latest.get("RSI", 0))
        except (ValueError, TypeError):
            return None

    async def get_macd(self, ticker: str) -> Optional[dict]:
        """Fetch latest MACD values. Returns {macd, signal, histogram}."""
        data = await self._api_call({
            "function": "MACD",
            "symbol": ticker,
            "interval": "daily",
            "series_type": "close",
        })
        if not data:
            return None
        ta = data.get("Technical Analysis: MACD", {})
        if not ta:
            return None
        latest = next(iter(ta.values()), {})
        try:
            return {
                "macd": float(latest.get("MACD", 0)),
                "signal": float(latest.get("MACD_Signal", 0)),
                "histogram": float(latest.get("MACD_Hist", 0)),
            }
        except (ValueError, TypeError):
            return None

    async def get_bbands(self, ticker: str, period: int = 20) -> Optional[dict]:
        """Fetch latest Bollinger Bands. Returns {upper, middle, lower}."""
        data = await self._api_call({
            "function": "BBANDS",
            "symbol": ticker,
            "interval": "daily",
            "time_period": period,
            "series_type": "close",
        })
        if not data:
            return None
        ta = data.get("Technical Analysis: BBANDS", {})
        if not ta:
            return None
        latest = next(iter(ta.values()), {})
        try:
            return {
                "upper": float(latest.get("Real Upper Band", 0)),
                "middle": float(latest.get("Real Middle Band", 0)),
                "lower": float(latest.get("Real Lower Band", 0)),
            }
        except (ValueError, TypeError):
            return None

    async def get_obv_trend(self, ticker: str) -> Optional[str]:
        """
        Fetch OBV and determine trend: 'rising', 'falling', or 'flat'.
        Compares latest OBV to 5-day average.
        """
        data = await self._api_call({
            "function": "OBV",
            "symbol": ticker,
            "interval": "daily",
        })
        if not data:
            return None
        ta = data.get("Technical Analysis: OBV", {})
        if not ta or len(ta) < 6:
            return None
        try:
            values = [float(v["OBV"]) for v in list(ta.values())[:6]]
            latest = values[0]
            avg_5d = sum(values[1:6]) / 5
            if avg_5d == 0:
                return "flat"
            pct_diff = (latest - avg_5d) / abs(avg_5d) * 100
            if pct_diff > 2:
                return "rising"
            elif pct_diff < -2:
                return "falling"
            return "flat"
        except (ValueError, TypeError, IndexError):
            return None

    async def get_adx(self, ticker: str, period: int = 14) -> Optional[float]:
        """Fetch latest ADX value (trend strength)."""
        data = await self._api_call({
            "function": "ADX",
            "symbol": ticker,
            "interval": "daily",
            "time_period": period,
        })
        if not data:
            return None
        ta = data.get("Technical Analysis: ADX", {})
        if not ta:
            return None
        latest = next(iter(ta.values()), {})
        try:
            return float(latest.get("ADX", 0))
        except (ValueError, TypeError):
            return None

    async def get_technical_snapshot(self, ticker: str) -> Optional[dict]:
        """
        Fetch all technical indicators for a ticker in one go.
        Returns dict with rsi, macd, bbands, obv_trend, adx.
        Costs 5 API calls per ticker.
        """
        rsi, macd, bbands, obv_trend, adx = await asyncio.gather(
            self.get_rsi(ticker),
            self.get_macd(ticker),
            self.get_bbands(ticker),
            self.get_obv_trend(ticker),
            self.get_adx(ticker),
            return_exceptions=True,
        )
        # Handle exceptions from gather
        result = {
            "rsi": rsi if not isinstance(rsi, Exception) else None,
            "macd": macd if not isinstance(macd, Exception) else None,
            "bbands": bbands if not isinstance(bbands, Exception) else None,
            "obv_trend": obv_trend if not isinstance(obv_trend, Exception) else None,
            "adx": adx if not isinstance(adx, Exception) else None,
        }
        logger.info(
            f"Technical snapshot for {ticker}: "
            f"RSI={result['rsi']}, "
            f"MACD_hist={result['macd']['histogram'] if result['macd'] else None}, "
            f"OBV={result['obv_trend']}, ADX={result['adx']}"
        )
        return result

    # ------------------------------------------------------------------
    # Fundamental Data APIs (Premium)
    # ------------------------------------------------------------------

    async def get_company_overview(self, ticker: str) -> Optional[dict]:
        """
        Fetch company overview with key financial ratios.
        Returns: MarketCap, PERatio, PEGRatio, ProfitMargin, ROE,
                 RevenueGrowthYOY, EarningsGrowthYOY, AnalystTargetPrice,
                 52WeekHigh/Low, Beta, etc.
        Cache TTL: 24 hours (fundamentals change slowly).
        """
        cache_key = f"overview:{ticker}"
        if self._is_cache_valid(self._daily_cache.get(cache_key)):
            _, cached = self._daily_cache[cache_key]
            return cached

        data = await self._api_call({
            "function": "OVERVIEW",
            "symbol": ticker,
        })
        if not data or "Symbol" not in data:
            return None

        def _safe_float(val):
            try:
                return float(val) if val and val != "None" and val != "-" else None
            except (ValueError, TypeError):
                return None

        result = {
            "ticker": data.get("Symbol", ticker),
            "name": data.get("Name", ""),
            "sector": data.get("Sector", ""),
            "industry": data.get("Industry", ""),
            "market_cap": _safe_float(data.get("MarketCapitalization")),
            "pe_ratio": _safe_float(data.get("PERatio")),
            "peg_ratio": _safe_float(data.get("PEGRatio")),
            "book_value": _safe_float(data.get("BookValue")),
            "dividend_yield": _safe_float(data.get("DividendYield")),
            "profit_margin": _safe_float(data.get("ProfitMargin")),
            "operating_margin": _safe_float(data.get("OperatingMarginTTM")),
            "roe": _safe_float(data.get("ReturnOnEquityTTM")),
            "roa": _safe_float(data.get("ReturnOnAssetsTTM")),
            "revenue_per_share": _safe_float(data.get("RevenuePerShareTTM")),
            "revenue_growth_yoy": _safe_float(data.get("QuarterlyRevenueGrowthYOY")),
            "earnings_growth_yoy": _safe_float(data.get("QuarterlyEarningsGrowthYOY")),
            "analyst_target_price": _safe_float(data.get("AnalystTargetPrice")),
            "week52_high": _safe_float(data.get("52WeekHigh")),
            "week52_low": _safe_float(data.get("52WeekLow")),
            "beta": _safe_float(data.get("Beta")),
            "ev_to_ebitda": _safe_float(data.get("EVToEBITDA")),
            "forward_pe": _safe_float(data.get("ForwardPE")),
        }

        # Cache for 24 hours (memory + disk)
        ts = time.time() + 86400 - self._cache_ttl
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        logger.info(f"Overview for {ticker}: PE={result['pe_ratio']} PEG={result['peg_ratio']} ROE={result['roe']}")
        return result

    async def get_earnings(self, ticker: str) -> Optional[dict]:
        """
        Fetch earnings history (quarterly and annual EPS data).
        Returns dict with 'quarterly' list of {date, reportedEPS, estimatedEPS, surprise%}.
        Cache TTL: 12 hours.
        """
        cache_key = f"earnings:{ticker}"
        if self._is_cache_valid(self._daily_cache.get(cache_key)):
            _, cached = self._daily_cache[cache_key]
            return cached

        data = await self._api_call({
            "function": "EARNINGS",
            "symbol": ticker,
        })
        if not data or "quarterlyEarnings" not in data:
            return None

        quarterly = []
        for q in data.get("quarterlyEarnings", []):
            try:
                quarterly.append({
                    "date": q.get("reportedDate", ""),
                    "fiscal_end": q.get("fiscalDateEnding", ""),
                    "reported_eps": float(q["reportedEPS"]) if q.get("reportedEPS") and q["reportedEPS"] != "None" else None,
                    "estimated_eps": float(q["estimatedEPS"]) if q.get("estimatedEPS") and q["estimatedEPS"] != "None" else None,
                    "surprise_pct": float(q["surprisePercentage"]) if q.get("surprisePercentage") and q["surprisePercentage"] != "None" else None,
                })
            except (ValueError, KeyError):
                continue

        result = {
            "ticker": ticker,
            "quarterly": quarterly,  # full history (AV returns 20+ years)
        }

        # Cache for 12 hours (memory + disk)
        ts = time.time() + 43200 - self._cache_ttl
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        if quarterly:
            latest = quarterly[0]
            logger.info(f"Earnings {ticker}: latest EPS={latest.get('reported_eps')} "
                        f"vs est={latest.get('estimated_eps')} surprise={latest.get('surprise_pct')}%")
        return result

    async def get_income_statement(self, ticker: str) -> Optional[dict]:
        """
        Fetch quarterly income statements.
        Returns dict with 'quarterly' list of {date, revenue, grossProfit, netIncome, ...}.
        Cache TTL: 24 hours.
        """
        cache_key = f"income:{ticker}"
        if self._is_cache_valid(self._daily_cache.get(cache_key)):
            _, cached = self._daily_cache[cache_key]
            return cached

        data = await self._api_call({
            "function": "INCOME_STATEMENT",
            "symbol": ticker,
        })
        if not data or "quarterlyReports" not in data:
            return None

        def _safe_int(val):
            try:
                return int(val) if val and val != "None" else None
            except (ValueError, TypeError):
                return None

        quarterly = []
        for q in data.get("quarterlyReports", []):
            quarterly.append({
                "date": q.get("fiscalDateEnding", ""),
                "reported_date": q.get("reportedDate", q.get("fiscalDateEnding", "")),
                "total_revenue": _safe_int(q.get("totalRevenue")),
                "gross_profit": _safe_int(q.get("grossProfit")),
                "operating_income": _safe_int(q.get("operatingIncome")),
                "net_income": _safe_int(q.get("netIncome")),
                "ebitda": _safe_int(q.get("ebitda")),
                "research_development": _safe_int(q.get("researchAndDevelopment")),
            })

        result = {
            "ticker": ticker,
            "quarterly": quarterly[:8],  # last 2 years
        }

        ts = time.time() + 86400 - self._cache_ttl
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        if quarterly:
            q0 = quarterly[0]
            logger.info(f"Income {ticker}: Q revenue=${q0.get('total_revenue',0):,} "
                        f"netIncome=${q0.get('net_income',0):,}")
        return result

    async def get_cash_flow(self, ticker: str) -> Optional[dict]:
        """
        Fetch quarterly cash flow statements.
        Returns dict with 'quarterly' list of {date, operatingCF, capex, freeCF, ...}.
        Cache TTL: 24 hours.
        """
        cache_key = f"cashflow:{ticker}"
        if self._is_cache_valid(self._daily_cache.get(cache_key)):
            _, cached = self._daily_cache[cache_key]
            return cached

        data = await self._api_call({
            "function": "CASH_FLOW",
            "symbol": ticker,
        })
        if not data or "quarterlyReports" not in data:
            return None

        def _safe_int(val):
            try:
                return int(val) if val and val != "None" else None
            except (ValueError, TypeError):
                return None

        quarterly = []
        for q in data.get("quarterlyReports", []):
            op_cf = _safe_int(q.get("operatingCashflow"))
            capex = _safe_int(q.get("capitalExpenditures"))
            free_cf = None
            if op_cf is not None and capex is not None:
                free_cf = op_cf - abs(capex)  # capex is negative in some reports

            quarterly.append({
                "date": q.get("fiscalDateEnding", ""),
                "operating_cashflow": op_cf,
                "capital_expenditures": capex,
                "free_cashflow": free_cf,
                "dividend_payout": _safe_int(q.get("dividendPayout")),
                "net_income": _safe_int(q.get("netIncome")),
            })

        result = {
            "ticker": ticker,
            "quarterly": quarterly[:8],
        }

        ts = time.time() + 86400 - self._cache_ttl
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        if quarterly:
            q0 = quarterly[0]
            logger.info(f"CashFlow {ticker}: opCF=${q0.get('operating_cashflow',0):,} "
                        f"FCF=${q0.get('free_cashflow',0):,}")
        return result

    # ------------------------------------------------------------------
    # News Sentiment API
    # ------------------------------------------------------------------

    async def get_news_sentiment(
        self, tickers: Optional[List[str]] = None, limit: int = 50
    ) -> Optional[List[dict]]:
        """
        Fetch news sentiment from Alpha Vantage NEWS_SENTIMENT endpoint.
        Returns list of articles with sentiment scores per ticker.
        Premium feature.
        """
        params = {
            "function": "NEWS_SENTIMENT",
            "limit": limit,
            "sort": "LATEST",
        }
        if tickers:
            params["tickers"] = ",".join(tickers)

        data = await self._api_call(params)
        if not data or "feed" not in data:
            return None

        articles = []
        for item in data["feed"]:
            article = {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": item.get("source", ""),
                "published": item.get("time_published", ""),
                "overall_sentiment_score": float(
                    item.get("overall_sentiment_score", 0)
                ),
                "overall_sentiment_label": item.get(
                    "overall_sentiment_label", ""
                ),
                "ticker_sentiments": [],
            }

            for ts in item.get("ticker_sentiment", []):
                article["ticker_sentiments"].append({
                    "ticker": ts.get("ticker", ""),
                    "relevance_score": float(
                        ts.get("relevance_score", 0)
                    ),
                    "sentiment_score": float(
                        ts.get("ticker_sentiment_score", 0)
                    ),
                    "sentiment_label": ts.get(
                        "ticker_sentiment_label", ""
                    ),
                })

            articles.append(article)

        logger.info(
            f"Alpha Vantage news sentiment: {len(articles)} articles"
        )
        return articles

    # ------------------------------------------------------------------
    # Convenience: rotation_service compatible format
    # ------------------------------------------------------------------

    async def get_history_arrays(
        self, ticker: str, days: int = 100
    ) -> Optional[dict]:
        """
        Fetch history and return numpy arrays compatible with rotation_service.

        Returns dict with:
            close, volume, high, low: numpy arrays
            dates: DatetimeIndex
        """
        df = await self.get_daily_history(ticker, days=days)
        if df is None or df.empty or len(df) < 20:
            return None

        return {
            "close": df["Close"].values,
            "volume": df["Volume"].values,
            "high": df["High"].values,
            "low": df["Low"].values,
            "dates": df.index,
        }

    def clear_cache(self):
        """Clear all cached data."""
        self._daily_cache.clear()
        self._quote_cache.clear()


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_client: Optional[AlphaVantageClient] = None


def get_av_client() -> AlphaVantageClient:
    """Get or create the singleton Alpha Vantage client."""
    global _client
    if _client is None:
        _client = AlphaVantageClient()
    return _client
