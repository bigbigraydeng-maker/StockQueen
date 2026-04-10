"""
StockQueen - Massive Market Data Client
统一替换 Alpha Vantage（行情/技术指标）和 FMP（基本面数据）。

数据源: https://api.massive.com (Polygon.io 兼容协议)
认证: Authorization: Bearer {API_KEY}
API Key 配置: MASSIVE_API_KEY 环境变量

端点覆盖:
  行情:       /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
  快照:       /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}
  技术指标:   /v1/indicators/{rsi|macd|ema|sma}/{ticker}
  基本面:     /stocks/financials/v1/{income-statements|cash-flow-statements|ratios|balance-sheets}
  财报EPS:    Alpha Vantage EARNINGS (含 reportedEPS, estimatedEPS, surprisePercentage)
  新闻:       /v2/reference/news
  股票列表:   /v3/reference/tickers
  公司详情:   /v3/reference/tickers/{ticker}
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import httpx
import numpy as np
import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.massive.com"

# -------------------------------------------------------------------
# Disk cache directory (reuses same path structure as old AV client)
# -------------------------------------------------------------------
_DISK_CACHE_DIR = os.environ.get(
    "AV_CACHE_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".cache", "av"
    )
)


# ===================================================================
# MassiveClient — 替换 AlphaVantageClient，保持完全相同的公共接口
# ===================================================================

class MassiveClient:
    """
    Massive.com 市场数据客户端。
    与 AlphaVantageClient 保持完全相同的公共方法签名，
    实现零改动无缝迁移。

    双级缓存: 内存（快）+ 磁盘 JSON（跨重启持久化）
    """

    _DISK_PREFIXES = ("overview:", "earnings:", "cashflow:", "income:", "daily:")
    _DISK_TTL        = 86400 * 3      # 3 天（基本面）
    _DISK_TTL_OHLCV  = 86400 * 180   # 180 天（OHLCV 历史不变）

    def __init__(self):
        # 优先读 settings（兼容 Pydantic 配置），次选环境变量
        # 注：在 Render worker 中，os.environ 可能在进程启动时还没初始化，
        #     所以总是优先用 settings 中的值（通过 .env 或 Render Dashboard 配置）
        _settings_key = getattr(settings, "massive_api_key", None)
        _env_key = os.environ.get("MASSIVE_API_KEY", "")
        self.api_key: str = _settings_key or _env_key or ""
        self._daily_cache:   Dict[str, tuple] = {}
        self._quote_cache:   Dict[str, tuple] = {}
        self._intraday_cache: Dict[str, tuple] = {}
        self._cache_ttl   = 3600    # 1h — OHLCV
        self._quote_ttl   = 300     # 5min — 实时报价
        self._intraday_ttl = 300    # 5min — 盘中数据快速刷新
        self._request_delay = 0.1   # Massive 无严格限速，0.1s 保留余量
        self._last_request_time = 0.0
        self._throttle_lock = asyncio.Lock()
        self._http_client: Optional[httpx.AsyncClient] = None
        # 磁盘缓存扫描可能很慢（大量 json），禁止在 __init__ 同步执行以免卡死整个事件循环
        self._disk_cache_loaded: bool = False
        self._disk_cache_load_lock = asyncio.Lock()

    async def _ensure_disk_cache_loaded(self) -> None:
        """首次需要读盘时在线程池加载，避免阻塞 asyncio（监控页 HTMX 等）。"""
        if self._disk_cache_loaded:
            return
        async with self._disk_cache_load_lock:
            if self._disk_cache_loaded:
                return
            try:
                await asyncio.to_thread(self._load_disk_cache)
            except Exception as e:
                logger.warning(f"Massive disk cache load failed: {e}")
            self._disk_cache_loaded = True

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _throttle(self):
        async with self._throttle_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self._request_delay:
                await asyncio.sleep(self._request_delay - elapsed)
            self._last_request_time = time.time()

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
            )
        return self._http_client

    async def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        """发起一次 GET 请求，返回 JSON dict 或 None。"""
        # 再次检查 api_key（防止单例初始化时的时序问题）
        if not self.api_key:
            _fresh_key = getattr(settings, "massive_api_key", None) or os.environ.get("MASSIVE_API_KEY", "")
            if _fresh_key:
                self.api_key = _fresh_key
                logger.info(f"[INIT] 从 settings 延迟加载 MASSIVE_API_KEY ({len(_fresh_key)} chars)")
            else:
                logger.error("Massive API key 未配置 (MASSIVE_API_KEY)")
                return None

        await self._ensure_disk_cache_loaded()
        await self._throttle()
        url = f"{_BASE_URL}{path}"
        try:
            client = await self._get_http_client()
            resp = await client.get(url, params=params or {}, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "OK") if isinstance(data, dict) else "OK"
            if status not in ("OK", "DELAYED"):
                logger.warning(f"Massive non-OK status={status} path={path}")
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"Massive HTTP error {e.response.status_code} path={path}")
            return None
        except Exception as e:
            logger.error(f"Massive request error path={path}: {e}")
            return None

    def _is_cache_valid(self, entry: Optional[tuple], ttl: Optional[float] = None) -> bool:
        if not entry:
            return False
        ts, _ = entry
        return (time.time() - ts) < (ttl if ttl is not None else self._cache_ttl)

    # ------------------------------------------------------------------
    # 磁盘缓存（与旧 AV 客户端格式兼容）
    # ------------------------------------------------------------------

    def _load_disk_cache(self):
        if not os.path.isdir(_DISK_CACHE_DIR):
            return
        loaded_fund = loaded_ohlcv = 0
        now = time.time()
        for fname in os.listdir(_DISK_CACHE_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(_DISK_CACHE_DIR, fname)
            try:
                if fname.startswith("daily_") and fname.endswith("_full.json"):
                    ticker = fname[6:-10]
                    entry = self._load_ohlcv_from_disk(ticker, skip_ttl=True)
                    if entry:
                        entry = (now, entry[1])
                        self._daily_cache[f"daily:{ticker}:full"] = entry
                        self._daily_cache[f"{ticker}:full"] = entry
                        loaded_ohlcv += 1
                    continue

                with open(fpath, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                ts = raw.get("ts", 0)
                if now - ts > self._DISK_TTL:
                    continue
                ck = raw.get("key", "")
                data = raw.get("data")
                if ck and data is not None:
                    self._daily_cache[ck] = (ts, data)
                    loaded_fund += 1
            except Exception:
                pass
        if loaded_fund or loaded_ohlcv:
            logger.info(f"Massive disk cache: loaded {loaded_fund} fundamental + {loaded_ohlcv} OHLCV")

    def _save_to_disk(self, cache_key: str, data, ts: float):
        if not any(cache_key.startswith(p) for p in self._DISK_PREFIXES):
            return
        try:
            os.makedirs(_DISK_CACHE_DIR, exist_ok=True)
            fname = cache_key.replace(":", "_").replace("/", "_") + ".json"
            fpath = os.path.join(_DISK_CACHE_DIR, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump({"key": cache_key, "ts": ts, "data": data}, f,
                          ensure_ascii=False, default=str)
        except Exception as e:
            logger.debug(f"Disk cache write failed {cache_key}: {e}")

    def _save_ohlcv_to_disk(self, ticker: str, df: pd.DataFrame, ts: float):
        try:
            os.makedirs(_DISK_CACHE_DIR, exist_ok=True)
            fpath = os.path.join(_DISK_CACHE_DIR, f"daily_{ticker}_full.json")
            rows = [
                [str(idx.date()), row["Open"], row["High"], row["Low"],
                 row["Close"], int(row["Volume"])]
                for idx, row in df.iterrows()
            ]
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump({"ticker": ticker, "ts": ts, "rows": rows}, f)
        except Exception as e:
            logger.debug(f"OHLCV disk write failed {ticker}: {e}")

    def _load_ohlcv_from_disk(self, ticker: str, skip_ttl: bool = False) -> Optional[tuple]:
        fpath = os.path.join(_DISK_CACHE_DIR, f"daily_{ticker}_full.json")
        if not os.path.isfile(fpath):
            return None
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            ts = raw.get("ts", 0)
            if not skip_ttl and time.time() - ts > self._DISK_TTL_OHLCV:
                return None
            rows = raw.get("rows", [])
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
            df = df.assign(Date=pd.to_datetime(df["Date"])).set_index("Date").sort_index()
            return (ts, df)
        except Exception as e:
            logger.debug(f"OHLCV disk read failed {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # 公共 API: 日线 OHLCV 历史
    # ------------------------------------------------------------------

    async def get_daily_history(
        self, ticker: str, days: int = 100, outputsize: str = "compact"
    ) -> Optional[pd.DataFrame]:
        """
        获取股票日线 OHLCV 数据。
        返回 DataFrame(Open/High/Low/Close/Volume)，DatetimeIndex 从旧到新。
        """
        await self._ensure_disk_cache_loaded()
        cache_key = f"{ticker}:{outputsize}"
        if self._is_cache_valid(self._daily_cache.get(cache_key)):
            _, df = self._daily_cache[cache_key]
            return df.tail(days).copy() if days < len(df) else df.copy()

        if days > 100 and outputsize == "compact":
            outputsize = "full"
            cache_key = f"{ticker}:full"
            if self._is_cache_valid(self._daily_cache.get(cache_key)):
                _, df = self._daily_cache[cache_key]
                return df.tail(days).copy() if days < len(df) else df.copy()

        disk_key = f"daily:{ticker}:full"
        if outputsize == "full":
            disk_entry = self._daily_cache.get(disk_key)
            if disk_entry:
                ts_disk, df_disk = disk_entry
                if (time.time() - ts_disk) < self._DISK_TTL_OHLCV:
                    self._daily_cache[cache_key] = disk_entry
                    return df_disk.tail(days).copy() if days < len(df_disk) else df_disk.copy()

        # 计算日期范围：full=20年，compact=最近110天
        end_date = datetime.now().strftime("%Y-%m-%d")
        if outputsize == "full":
            start_date = (datetime.now() - timedelta(days=365 * 20)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=110)).strftime("%Y-%m-%d")

        df = await self._fetch_bars(ticker, start_date, end_date)
        if df is None or df.empty:
            return None

        ts_now = time.time()
        self._daily_cache[cache_key] = (ts_now, df)
        if outputsize == "full":
            self._daily_cache[disk_key] = (ts_now, df)
            self._save_ohlcv_to_disk(ticker, df, ts_now)

        return df.tail(days).copy() if days < len(df) else df.copy()

    async def _fetch_bars(
        self, ticker: str, start: str, end: str
    ) -> Optional[pd.DataFrame]:
        """从 Massive /v2/aggs 获取日线 OHLCV，自动翻页。"""
        all_rows = []
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
        }
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
        data = await self._get(path, params)
        if not data:
            return None

        results = data.get("results", [])
        if not results:
            logger.warning(f"Massive bars: no data for {ticker} {start}~{end}")
            return None

        for bar in results:
            # t = Unix ms timestamp（bar 起始）
            dt = datetime.utcfromtimestamp(bar["t"] / 1000)
            all_rows.append({
                "Date":   pd.Timestamp(dt.date()),
                "Open":   float(bar["o"]),
                "High":   float(bar["h"]),
                "Low":    float(bar["l"]),
                "Close":  float(bar["c"]),
                "Volume": int(bar.get("v", 0)),
            })

        # 翻页（next_url 存在时继续）
        next_url = data.get("next_url")
        while next_url and len(all_rows) < 100000:
            try:
                client = await self._get_http_client()
                resp = await client.get(next_url, headers=self._headers())
                resp.raise_for_status()
                page = resp.json()
                for bar in page.get("results", []):
                    dt = datetime.utcfromtimestamp(bar["t"] / 1000)
                    all_rows.append({
                        "Date":   pd.Timestamp(dt.date()),
                        "Open":   float(bar["o"]),
                        "High":   float(bar["h"]),
                        "Low":    float(bar["l"]),
                        "Close":  float(bar["c"]),
                        "Volume": int(bar.get("v", 0)),
                    })
                next_url = page.get("next_url")
            except Exception as e:
                logger.error(f"Massive bars pagination error {ticker}: {e}")
                break

        df = pd.DataFrame(all_rows)
        df.set_index("Date", inplace=True)
        df.sort_index(inplace=True)
        return df

    async def get_daily_history_range(
        self, ticker: str, start: str, end: str
    ) -> Optional[pd.DataFrame]:
        """获取指定日期范围的日线 OHLCV。"""
        df = await self.get_daily_history(ticker, days=3650, outputsize="full")
        if df is None or df.empty:
            return None
        mask = (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))
        filtered = df.loc[mask]
        return filtered if not filtered.empty else None

    # ------------------------------------------------------------------
    # 公共 API: 实时报价快照
    # ------------------------------------------------------------------

    async def get_quote(self, ticker: str) -> Optional[dict]:
        """
        获取单只股票实时快照。
        返回: {ticker, prev_close, open, high, low, latest_price,
               change_percent, volume, avg_volume_30d, market_cap, data_source}
        """
        if self._is_cache_valid(self._quote_cache.get(ticker), ttl=self._quote_ttl):
            _, quote = self._quote_cache[ticker]
            return quote

        data = await self._get(
            f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
        )
        if not data:
            return None

        snap = data.get("ticker", {})
        if not snap:
            return None

        try:
            day = snap.get("day", {}) or {}
            prev = snap.get("prevDay", {}) or {}
            last_trade = snap.get("lastTrade", {}) or {}

            # Priority: lastTrade (latest execution) > day.c (aggregated)
            day_close = float(day.get("c", 0))
            last_trade_price = float(last_trade.get("p", 0))
            latest_price = last_trade_price if last_trade_price > 0 else day_close

            quote = {
                "ticker":         ticker,
                "prev_close":     float(prev.get("c", 0)),
                "open":           float(day.get("o", 0)),
                "high":           float(day.get("h", 0)),
                "low":            float(day.get("l", 0)),
                "latest_price":   latest_price,
                "change_percent": float(snap.get("todaysChangePerc", 0)),
                "volume":         int(day.get("v", 0)),
                "avg_volume_30d": 0,
                "market_cap":     0,
                "data_source":    "massive",
            }
            self._quote_cache[ticker] = (time.time(), quote)
            return quote
        except (ValueError, KeyError) as e:
            logger.error(f"Massive quote parse error {ticker}: {e}")
            return None

    async def batch_get_quotes(self, tickers: List[str]) -> Dict[str, dict]:
        """批量获取多只股票快照，优先命中缓存。"""
        results: Dict[str, dict] = {}
        uncached: List[str] = []

        for t in tickers:
            if self._is_cache_valid(self._quote_cache.get(t), ttl=self._quote_ttl):
                _, q = self._quote_cache[t]
                results[t] = q
            else:
                uncached.append(t)

        if not uncached:
            return results

        # 批量查询（Massive 支持逗号分隔，最多约 250 个）
        chunk_size = 200
        for i in range(0, len(uncached), chunk_size):
            chunk = uncached[i: i + chunk_size]
            tickers_str = ",".join(chunk)
            data = await self._get(
                "/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"tickers": tickers_str}
            )
            if not data:
                continue
            for snap in data.get("tickers", []):
                tkr = snap.get("ticker", "")
                if not tkr:
                    continue
                try:
                    day  = snap.get("day", {}) or {}
                    prev = snap.get("prevDay", {}) or {}
                    last_trade = snap.get("lastTrade", {}) or {}

                    # Priority: lastTrade (latest execution) > day.c (aggregated)
                    day_close = float(day.get("c", 0))
                    last_trade_price = float(last_trade.get("p", 0))
                    latest_price = last_trade_price if last_trade_price > 0 else day_close

                    quote = {
                        "ticker":         tkr,
                        "prev_close":     float(prev.get("c", 0)),
                        "open":           float(day.get("o", 0)),
                        "high":           float(day.get("h", 0)),
                        "low":            float(day.get("l", 0)),
                        "latest_price":   latest_price,
                        "change_percent": float(snap.get("todaysChangePerc", 0)),
                        "volume":         int(day.get("v", 0)),
                        "avg_volume_30d": 0,
                        "market_cap":     0,
                        "data_source":    "massive",
                    }
                    self._quote_cache[tkr] = (time.time(), quote)
                    results[tkr] = quote
                except Exception:
                    pass

        return results

    async def batch_get_daily_history(
        self, tickers: List[str], days: int = 30
    ) -> Dict[str, pd.DataFrame]:
        """批量获取多只股票日线历史（并发 10，避免超限）。"""
        results: Dict[str, pd.DataFrame] = {}
        sem = asyncio.Semaphore(10)

        async def _fetch(t: str):
            async with sem:
                df = await self.get_daily_history(t, days=days)
                if df is not None and not df.empty:
                    results[t] = df

        await asyncio.gather(*[_fetch(t) for t in tickers], return_exceptions=True)
        logger.info(f"Massive batch OHLCV: {len(results)}/{len(tickers)} 成功")
        return results

    # ------------------------------------------------------------------
    # 盘中 Bars（分钟/小时级 OHLCV）
    # ------------------------------------------------------------------

    async def get_intraday_history(
        self, ticker: str, timespan: str = "minute", multiplier: int = 30,
        days_back: int = 1,
    ) -> Optional[pd.DataFrame]:
        """
        获取盘中 OHLCV 数据。
        timespan: "minute" | "hour"
        multiplier: 1/5/30/60
        days_back: 回看天数（1=今天，2=今天+昨天）
        返回 DataFrame(Open/High/Low/Close/Volume)，DatetimeIndex(UTC) 从旧到新。
        不写磁盘缓存（日内数据次日无意义）。
        """
        cache_key = f"intraday:{ticker}:{multiplier}{timespan}:{days_back}d"
        cached = self._intraday_cache.get(cache_key)
        if self._is_cache_valid(cached, ttl=self._intraday_ttl):
            _, df = cached
            return df.copy()

        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days_back)
        # Polygon 兼容端点接受 YYYY-MM-DD 或 Unix ms
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        path = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start_str}/{end_str}"
        params = {"adjusted": "true", "sort": "asc", "limit": 50000}
        data = await self._get(path, params)
        if not data:
            return None

        results = data.get("results", [])
        if not results:
            return None

        rows = []
        for bar in results:
            dt = datetime.utcfromtimestamp(bar["t"] / 1000)
            rows.append({
                "Date":   pd.Timestamp(dt),
                "Open":   float(bar["o"]),
                "High":   float(bar["h"]),
                "Low":    float(bar["l"]),
                "Close":  float(bar["c"]),
                "Volume": float(bar.get("v", 0)),
            })

        df = pd.DataFrame(rows).set_index("Date").sort_index()
        self._intraday_cache[cache_key] = (time.time(), df)
        return df

    async def get_intraday_arrays(
        self, ticker: str, timespan: str = "minute", multiplier: int = 30,
        days_back: int = 1,
    ) -> Optional[dict]:
        """返回盘中 numpy 数组格式，兼容评分引擎接口。"""
        df = await self.get_intraday_history(ticker, timespan, multiplier, days_back)
        if df is None or df.empty or len(df) < 2:
            return None
        return {
            "open":       df["Open"].values,
            "close":      df["Close"].values,
            "high":       df["High"].values,
            "low":        df["Low"].values,
            "volume":     df["Volume"].values,
            "timestamps": df.index.tolist(),
        }

    async def batch_get_intraday_history(
        self, tickers: List[str], timespan: str = "minute",
        multiplier: int = 30, days_back: int = 1,
    ) -> Dict[str, pd.DataFrame]:
        """批量获取盘中 bars（并发 10）。"""
        results: Dict[str, pd.DataFrame] = {}
        sem = asyncio.Semaphore(10)

        async def _fetch(t: str):
            async with sem:
                df = await self.get_intraday_history(t, timespan, multiplier, days_back)
                if df is not None and not df.empty:
                    results[t] = df

        await asyncio.gather(*[_fetch(t) for t in tickers], return_exceptions=True)
        logger.info(f"Massive batch intraday: {len(results)}/{len(tickers)} OK ({multiplier}{timespan})")
        return results

    # ------------------------------------------------------------------
    # 技术指标（Massive 端点 + 本地计算备选）
    # ------------------------------------------------------------------

    async def get_rsi(self, ticker: str, period: int = 14) -> Optional[float]:
        """获取最新 RSI 值。"""
        data = await self._get(
            f"/v1/indicators/rsi/{ticker}",
            params={"timespan": "day", "window": period,
                    "series_type": "close", "order": "desc", "limit": 1}
        )
        if data:
            results = data.get("results", {})
            values = results.get("values", []) if isinstance(results, dict) else []
            if values and "value" in values[0]:
                try:
                    return float(values[0]["value"])
                except (ValueError, TypeError):
                    pass
        # 备选: 从 OHLCV 本地计算
        return await self._rsi_from_ohlcv(ticker, period)

    async def _rsi_from_ohlcv(self, ticker: str, period: int = 14) -> Optional[float]:
        df = await self.get_daily_history(ticker, days=period * 3)
        if df is None or len(df) < period + 1:
            return None
        closes = df["Close"].values
        deltas = np.diff(closes)
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 2)

    async def get_macd(self, ticker: str) -> Optional[dict]:
        """获取最新 MACD 值 {macd, signal, histogram}。"""
        data = await self._get(
            f"/v1/indicators/macd/{ticker}",
            params={"timespan": "day", "series_type": "close",
                    "order": "desc", "limit": 1}
        )
        if data:
            results = data.get("results", {})
            values = results.get("values", []) if isinstance(results, dict) else []
            if values:
                v = values[0]
                try:
                    return {
                        "macd":      float(v.get("value", 0)),
                        "signal":    float(v.get("signal", 0)),
                        "histogram": float(v.get("histogram", 0)),
                    }
                except (ValueError, TypeError):
                    pass
        return await self._macd_from_ohlcv(ticker)

    async def _macd_from_ohlcv(
        self, ticker: str, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Optional[dict]:
        df = await self.get_daily_history(ticker, days=(slow + signal) * 3)
        if df is None or len(df) < slow + signal:
            return None
        closes = pd.Series(df["Close"].values)
        ema_fast   = closes.ewm(span=fast, adjust=False).mean()
        ema_slow   = closes.ewm(span=slow, adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return {
            "macd":      round(float(macd_line.iloc[-1]), 4),
            "signal":    round(float(signal_line.iloc[-1]), 4),
            "histogram": round(float(hist.iloc[-1]), 4),
        }

    async def get_bbands(self, ticker: str, period: int = 20) -> Optional[dict]:
        """获取最新布林带 {upper, middle, lower}，从 OHLCV 本地计算。"""
        df = await self.get_daily_history(ticker, days=period * 3)
        if df is None or len(df) < period:
            return None
        closes = df["Close"]
        middle = float(closes.iloc[-period:].mean())
        std    = float(closes.iloc[-period:].std())
        return {
            "upper":  round(middle + 2 * std, 4),
            "middle": round(middle, 4),
            "lower":  round(middle - 2 * std, 4),
        }

    async def get_obv_trend(self, ticker: str) -> Optional[str]:
        """计算 OBV 趋势：'rising' / 'falling' / 'flat'。"""
        df = await self.get_daily_history(ticker, days=20)
        if df is None or len(df) < 6:
            return None
        closes  = df["Close"].values
        volumes = df["Volume"].values
        obv = 0.0
        obv_series = []
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv += volumes[i]
            elif closes[i] < closes[i - 1]:
                obv -= volumes[i]
            obv_series.append(obv)
        if len(obv_series) < 6:
            return None
        latest  = obv_series[-1]
        avg_5d  = sum(obv_series[-6:-1]) / 5
        if avg_5d == 0:
            return "flat"
        pct = (latest - avg_5d) / abs(avg_5d) * 100
        if pct > 2:
            return "rising"
        elif pct < -2:
            return "falling"
        return "flat"

    async def get_adx(self, ticker: str, period: int = 14) -> Optional[float]:
        """从 OHLCV 本地计算 ADX（趋势强度）。"""
        df = await self.get_daily_history(ticker, days=period * 4)
        if df is None or len(df) < period * 2:
            return None
        high  = df["High"].values
        low   = df["Low"].values
        close = df["Close"].values
        n = len(close)
        tr_arr, pdm_arr, ndm_arr = [], [], []
        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i]  - close[i - 1])
            tr_arr.append(max(hl, hc, lc))
            up   = high[i] - high[i - 1]
            down = low[i - 1] - low[i]
            pdm_arr.append(up   if up > down and up > 0 else 0)
            ndm_arr.append(down if down > up and down > 0 else 0)
        def _ema14(arr):
            result = [sum(arr[:period]) / period]
            for v in arr[period:]:
                result.append(result[-1] - result[-1] / period + v)
            return result
        atr14  = _ema14(tr_arr)
        pdm14  = _ema14(pdm_arr)
        ndm14  = _ema14(ndm_arr)
        dx_arr = []
        for atr, pdm, ndm in zip(atr14, pdm14, ndm14):
            if atr == 0:
                continue
            pdi = 100 * pdm / atr
            ndi = 100 * ndm / atr
            denom = pdi + ndi
            if denom == 0:
                dx_arr.append(0.0)
            else:
                dx_arr.append(100 * abs(pdi - ndi) / denom)
        if not dx_arr:
            return None
        adx = sum(dx_arr[-period:]) / min(period, len(dx_arr))
        return round(adx, 2)

    async def get_technical_snapshot(self, ticker: str) -> Optional[dict]:
        """一次获取全部技术指标 {rsi, macd, bbands, obv_trend, adx}。"""
        rsi, macd, bbands, obv_trend, adx = await asyncio.gather(
            self.get_rsi(ticker),
            self.get_macd(ticker),
            self.get_bbands(ticker),
            self.get_obv_trend(ticker),
            self.get_adx(ticker),
            return_exceptions=True,
        )
        result = {
            "rsi":       rsi       if not isinstance(rsi,       Exception) else None,
            "macd":      macd      if not isinstance(macd,      Exception) else None,
            "bbands":    bbands    if not isinstance(bbands,    Exception) else None,
            "obv_trend": obv_trend if not isinstance(obv_trend, Exception) else None,
            "adx":       adx       if not isinstance(adx,       Exception) else None,
        }
        logger.info(
            f"Technical snapshot {ticker}: RSI={result['rsi']}, "
            f"MACD_hist={result['macd']['histogram'] if result['macd'] else None}, "
            f"OBV={result['obv_trend']}, ADX={result['adx']}"
        )
        return result

    # ------------------------------------------------------------------
    # 基本面共享工具: /vX/reference/financials (200 OK)
    # ------------------------------------------------------------------

    async def _get_vx_financials(
        self, ticker: str, timeframe: str = "quarterly", limit: int = 20
    ) -> list:
        """
        调用 /vX/reference/financials（Polygon 兼容，Massive 计划已授权）。
        返回 results 列表，每项含 start_date, end_date, filing_date,
        fiscal_period, fiscal_year, financials.{income_statement,
        balance_sheet, cash_flow_statement}
        每个字段值为 {"value": ..., "unit": "USD"}。
        """
        data = await self._get(
            "/vX/reference/financials",
            params={"ticker": ticker, "timeframe": timeframe, "limit": limit}
        )
        if not data:
            return []
        return data.get("results", [])

    @staticmethod
    def _fval(d: dict, key: str) -> Optional[float]:
        """从 vX financials 字段中安全提取数值。"""
        v = d.get(key)
        if isinstance(v, dict):
            raw = v.get("value")
        else:
            raw = v
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # 基本面: 公司概况
    # ------------------------------------------------------------------

    async def get_company_overview(self, ticker: str) -> Optional[dict]:
        """
        获取公司基本面概况（市值、PE、ROE 等）。
        数据来源: /vX/reference/financials + /v3/reference/tickers
        缓存 TTL: 24h
        """
        cache_key = f"overview:{ticker}"
        entry = self._daily_cache.get(cache_key)
        if entry and self._is_cache_valid(entry, ttl=86400):
            return entry[1]

        fin_results, ref_data = await asyncio.gather(
            self._get_vx_financials(ticker, limit=1),
            self._get(f"/v3/reference/tickers/{ticker}"),
            return_exceptions=True,
        )

        result: dict = {"ticker": ticker}

        # 从 reference/tickers 获取名称、行业等
        if isinstance(ref_data, dict):
            ref = ref_data.get("results", {}) or {}
            result.update({
                "name":         ref.get("name", ""),
                "sector":       ref.get("sic_description", ""),
                "industry":     ref.get("sic_description", ""),
                "description":  (ref.get("description") or "")[:300],
                "market_cap":   ref.get("market_cap"),
                "beta":         None,
            })

        # 从最新季报计算财务比率
        if isinstance(fin_results, list) and fin_results:
            fins = fin_results[0].get("financials", {})
            inc  = fins.get("income_statement", {})
            bal  = fins.get("balance_sheet", {})
            _fv  = self._fval

            revenue    = _fv(inc, "revenues")
            net_income = _fv(inc, "net_income_loss")
            equity     = _fv(bal, "equity")
            assets     = _fv(bal, "assets")

            profit_margin   = (net_income / revenue) if revenue else None
            roe             = (net_income / equity)  if equity  else None
            roa             = (net_income / assets)  if assets  else None

            result.update({
                "pe_ratio":            None,  # 需要实时价格，暂不计算
                "peg_ratio":           None,
                "book_value":          equity,
                "dividend_yield":      None,
                "profit_margin":       profit_margin,
                "operating_margin":    None,
                "roe":                 roe,
                "roa":                 roa,
                "revenue_per_share":   None,
                "revenue_growth_yoy":  None,
                "earnings_growth_yoy": None,
                "analyst_target_price": None,
                "week52_high":         None,
                "week52_low":          None,
                "ev_to_ebitda":        None,
                "forward_pe":          None,
            })

        ts = time.time()
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        return result

    # ------------------------------------------------------------------
    # 基本面: 财报 EPS 历史（Alpha Vantage EARNINGS 端点）
    # Massive 无 Benzinga 授权，改用 AV 的 EARNINGS 函数获取
    # EPS 预期/惊喜值（AV 付费 key 75次/分钟，SP100 约 2 分钟）
    # ------------------------------------------------------------------

    async def get_earnings(self, ticker: str) -> Optional[dict]:
        """
        获取季度 EPS 历史（通过 Alpha Vantage EARNINGS 端点）。
        返回: {ticker, quarterly: [{date, fiscal_end, reported_eps,
                                     estimated_eps, surprise_pct, is_future}]}
        """
        cache_key = f"earnings:{ticker}"
        entry = self._daily_cache.get(cache_key)
        if entry and self._is_cache_valid(entry, ttl=43200):
            return entry[1]

        result = await _fetch_av_earnings(ticker)
        if not result:
            return None

        ts = time.time()
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        return result

    # ------------------------------------------------------------------
    # 财报日历（AV EARNINGS_CALENDAR — CSV 格式，1 次调用覆盖全市场）
    # ------------------------------------------------------------------

    async def get_earnings_calendar(self, horizon: str = "3month") -> list:
        """
        获取 AV EARNINGS_CALENDAR：返回未来 3/6/12 个月内全市场计划财报日期。
        horizon: "3month" | "6month" | "12month"
        返回 list[dict]: {ticker, name, report_date, fiscal_date_ending, estimate, currency}
        Cache TTL: 12 小时。
        """
        cache_key = f"earnings_calendar:{horizon}"
        entry = self._daily_cache.get(cache_key)
        if entry and self._is_cache_valid(entry, ttl=43200):
            return entry[1]

        av_key = (
            getattr(settings, "alpha_vantage_key", None)
            or os.environ.get("ALPHA_VANTAGE_KEY", "")
        )
        if not av_key:
            logger.warning("[Massive] 无 AV Key，跳过 EARNINGS_CALENDAR")
            return []

        try:
            import io
            import pandas as _pd
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)) as client:
                resp = await client.get(_AV_BASE, params={
                    "function": "EARNINGS_CALENDAR",
                    "horizon": horizon,
                    "apikey": av_key,
                })
            resp.raise_for_status()
            text = resp.text

            if not text or text.strip().startswith("{"):
                logger.warning(f"[Massive] EARNINGS_CALENDAR 异常响应: {text[:120]}")
                return []

            df = _pd.read_csv(io.StringIO(text))
            result = []
            for _, row in df.iterrows():
                ticker = str(row.get("symbol", "") or "").strip()
                if not ticker:
                    continue
                result.append({
                    "ticker": ticker,
                    "name": str(row.get("name", "") or ""),
                    "report_date": str(row.get("reportDate", "") or ""),
                    "fiscal_date_ending": str(row.get("fiscalDateEnding", "") or ""),
                    "estimate": float(row["estimate"]) if _pd.notna(row.get("estimate")) else None,
                    "currency": str(row.get("currency", "USD") or "USD"),
                })

            logger.info(f"[Massive] EARNINGS_CALENDAR ({horizon}): {len(result)} 条")
            ts = time.time()
            self._daily_cache[cache_key] = (ts, result)
            self._save_to_disk(cache_key, result, ts)
            return result

        except Exception as e:
            logger.error(f"[Massive] get_earnings_calendar error: {e}", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # 基本面: 利润表
    # ------------------------------------------------------------------

    async def get_income_statement(self, ticker: str) -> Optional[dict]:
        """
        获取最近 8 个季度利润表。
        返回: {ticker, quarterly: [{date, total_revenue, gross_profit,
                                     operating_income, net_income, ebitda}]}
        数据来源: /vX/reference/financials (200 OK)
        """
        cache_key = f"income:{ticker}"
        entry = self._daily_cache.get(cache_key)
        if entry and self._is_cache_valid(entry, ttl=86400):
            return entry[1]

        items = await self._get_vx_financials(ticker, limit=8)
        if not items:
            return None

        _fv = self._fval
        quarterly = []
        for q in items:
            fins = q.get("financials", {})
            inc  = fins.get("income_statement", {})
            quarterly.append({
                "date":                 q.get("end_date", ""),
                "reported_date":        q.get("filing_date", q.get("end_date", "")),
                "total_revenue":        _fv(inc, "revenues"),
                "gross_profit":         _fv(inc, "gross_profit"),
                "operating_income":     _fv(inc, "operating_income_loss"),
                "net_income":           _fv(inc, "net_income_loss"),
                "ebitda":               None,  # vX 无 EBITDA 字段，需手动计算
                "research_development": _fv(inc, "research_and_development"),
            })

        result = {"ticker": ticker, "quarterly": quarterly[:8]}
        ts = time.time()
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        return result

    # ------------------------------------------------------------------
    # 基本面: 现金流量表
    # ------------------------------------------------------------------

    async def get_cash_flow(self, ticker: str) -> Optional[dict]:
        """
        获取最近 8 个季度现金流。
        返回: {ticker, quarterly: [{date, operating_cashflow, capital_expenditures,
                                     free_cashflow, dividend_payout, net_income}]}
        数据来源: /vX/reference/financials (200 OK)
        """
        cache_key = f"cashflow:{ticker}"
        entry = self._daily_cache.get(cache_key)
        if entry and self._is_cache_valid(entry, ttl=86400):
            return entry[1]

        items = await self._get_vx_financials(ticker, limit=8)
        if not items:
            return None

        _fv = self._fval
        quarterly = []
        for q in items:
            fins  = q.get("financials", {})
            cf    = fins.get("cash_flow_statement", {})
            inc   = fins.get("income_statement", {})
            op_cf   = _fv(cf, "net_cash_flow_from_operating_activities")
            inv_cf  = _fv(cf, "net_cash_flow_from_investing_activities")
            # capex 近似 = investing cash flow 的负值（通常为负数）
            capex   = _fv(cf, "capital_expenditure") or inv_cf
            fcf     = (op_cf + inv_cf) if (op_cf is not None and inv_cf is not None) else None
            quarterly.append({
                "date":                 q.get("end_date", ""),
                "operating_cashflow":   op_cf,
                "capital_expenditures": capex,
                "free_cashflow":        fcf,
                "dividend_payout":      _fv(cf, "net_cash_flow_from_financing_activities"),
                "net_income":           _fv(inc, "net_income_loss"),
            })

        result = {"ticker": ticker, "quarterly": quarterly[:8]}
        ts = time.time()
        self._daily_cache[cache_key] = (ts, result)
        self._save_to_disk(cache_key, result, ts)
        return result

    # ------------------------------------------------------------------
    # 新闻情绪
    # ------------------------------------------------------------------

    async def get_news_sentiment(
        self, tickers: Optional[List[str]] = None, limit: int = 50
    ) -> Optional[List[dict]]:
        """
        获取新闻情绪数据（Massive /v2/reference/news）。
        返回与 AlphaVantageClient.get_news_sentiment 相同的格式。
        """
        params: dict = {"limit": min(limit, 1000), "sort": "published_utc", "order": "desc"}
        if tickers:
            params["ticker"] = ",".join(tickers)

        data = await self._get("/v2/reference/news", params)
        if not data:
            return None

        articles = []
        for item in data.get("results", []):
            article = {
                "title":   item.get("title", ""),
                "url":     item.get("article_url", ""),
                "source":  item.get("publisher", {}).get("name", ""),
                "published": item.get("published_utc", ""),
                "overall_sentiment_score": 0.0,
                "overall_sentiment_label": "",
                "ticker_sentiments": [],
            }
            for ins in item.get("insights", []):
                tkr       = ins.get("ticker", "")
                sentiment = ins.get("sentiment", "neutral")
                score_map = {"positive": 0.5, "negative": -0.5, "neutral": 0.0}
                score = score_map.get(sentiment, 0.0)
                article["ticker_sentiments"].append({
                    "ticker":           tkr,
                    "relevance_score":  1.0 if tkr in (tickers or []) else 0.5,
                    "sentiment_score":  score,
                    "sentiment_label":  sentiment,
                })
            articles.append(article)

        logger.info(f"Massive news: {len(articles)} articles")
        return articles

    # ------------------------------------------------------------------
    # 股票上市列表（替换 LISTING_STATUS）
    # ------------------------------------------------------------------

    async def get_listing_status(
        self, date: Optional[str] = None, state: str = "active"
    ) -> Optional[list]:
        """
        获取美股上市列表，格式与 Alpha Vantage LISTING_STATUS 兼容。
        返回: [{symbol, name, exchange, assetType, ipoDate, delistingDate, status}]

        注: Massive /v3/reference/tickers 不提供历史快照(date参数会被忽略)。
        """
        active = "true" if state == "active" else "false"
        params = {
            "market":  "stocks",
            "locale":  "us",
            "active":  active,
            "limit":   1000,
            "sort":    "ticker",
            "order":   "asc",
        }

        all_results = []
        data = await self._get("/v3/reference/tickers", params)
        if not data:
            return None

        def _map(r: dict) -> dict:
            t = r.get("type", "")
            # Alpha Vantage 兼容：AV 用 "Stock"，Polygon 用 "CS"
            type_map = {"CS": "Stock", "ETF": "ETF", "ADRC": "ADR",
                        "PFD": "Preferred Stock", "UNIT": "Unit", "RIGHT": "Rights"}
            # Polygon primary_exchange → AV exchange 格式
            exch_raw = r.get("primary_exchange", "")
            exch_map = {"XNYS": "NYSE", "XNAS": "NASDAQ", "XASE": "NYSE ARCA",
                        "XNMS": "NASDAQ", "XNGS": "NASDAQ", "XNCM": "NASDAQ"}
            return {
                "symbol":        r.get("ticker", ""),
                "name":          r.get("name", ""),
                "exchange":      exch_map.get(exch_raw, exch_raw),
                "assetType":     type_map.get(t, t),
                "ipoDate":       r.get("list_date", ""),
                "delistingDate": r.get("delisted_utc", ""),
                "status":        "Active" if r.get("active", True) else "Delisted",
            }

        all_results.extend(_map(r) for r in data.get("results", []))

        # 翻页获取全部
        next_url = data.get("next_url")
        while next_url and len(all_results) < 15000:
            try:
                client = await self._get_http_client()
                resp = await client.get(next_url, headers=self._headers())
                resp.raise_for_status()
                page = resp.json()
                all_results.extend(_map(r) for r in page.get("results", []))
                next_url = page.get("next_url")
            except Exception as e:
                logger.error(f"Massive listing pagination error: {e}")
                break

        logger.info(f"Massive listing_status: {len(all_results)} entries (state={state})")
        return all_results

    # ------------------------------------------------------------------
    # rotation_service 兼容格式
    # ------------------------------------------------------------------

    async def get_history_arrays(self, ticker: str, days: int = 100) -> Optional[dict]:
        """返回 numpy 数组格式，兼容 rotation_service。"""
        df = await self.get_daily_history(ticker, days=days)
        if df is None or df.empty or len(df) < 20:
            return None
        return {
            "close":  df["Close"].values,
            "volume": df["Volume"].values,
            "high":   df["High"].values,
            "low":    df["Low"].values,
            "dates":  df.index,
        }

    def clear_cache(self):
        """清空内存缓存。"""
        self._daily_cache.clear()
        self._quote_cache.clear()
        self._intraday_cache.clear()


# ===================================================================
# 模块级单例（替换 get_av_client）
# ===================================================================

_client: Optional[MassiveClient] = None


def get_massive_client() -> MassiveClient:
    """获取/创建 MassiveClient 单例。"""
    global _client
    if _client is None:
        _client = MassiveClient()
    return _client


# 向后兼容别名
get_av_client = get_massive_client


# ===================================================================
# FMP 兼容模块级函数
# 与 fmp_client.py 保持完全相同的函数签名
# ===================================================================

# 各类型独立缓存
_EARNINGS_CACHE: dict = {}
_PROFILE_CACHE:  dict = {}
_RATIOS_CACHE:   dict = {}
_INCOME_CACHE:   dict = {}
_CASHFLOW_CACHE: dict = {}

_TTL_SHORT = 43200       # 12h
_TTL_LONG  = 7 * 86400  # 7d


# ------------------------------------------------------------------
# AV EARNINGS 共享获取函数
# Massive 无 Benzinga 授权，财报 EPS 预期/惊喜值走 Alpha Vantage
# ------------------------------------------------------------------

_AV_BASE = "https://www.alphavantage.co/query"
_AV_EARNINGS_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_av_semaphore() -> asyncio.Semaphore:
    """AV 付费版 75次/分钟 ≈ 1.25次/秒，用信号量控制并发。"""
    global _AV_EARNINGS_SEMAPHORE
    if _AV_EARNINGS_SEMAPHORE is None:
        _AV_EARNINGS_SEMAPHORE = asyncio.Semaphore(5)
    return _AV_EARNINGS_SEMAPHORE


async def _fetch_av_earnings(ticker: str) -> Optional[dict]:
    """
    从 Alpha Vantage EARNINGS 端点获取季度 EPS 数据。
    返回统一格式: {ticker, quarterly: [{date, reported_eps, estimated_eps,
                                         surprise_pct, is_future, ...}]}
    """
    av_key = (
        getattr(settings, "alpha_vantage_key", None)
        or os.environ.get("ALPHA_VANTAGE_KEY", "")
    )
    if not av_key:
        logger.warning("[AV-Earnings] ALPHA_VANTAGE_KEY 未配置")
        return None

    sem = _get_av_semaphore()
    async with sem:
        await asyncio.sleep(0.8)  # 75次/分钟 ≈ 0.8s 间隔
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)) as client:
                resp = await client.get(_AV_BASE, params={
                    "function": "EARNINGS",
                    "symbol": ticker,
                    "apikey": av_key,
                })
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"[AV-Earnings] {ticker} 请求失败: {e}")
            return None

    if "Information" in data or "Note" in data:
        msg = data.get("Information", data.get("Note", ""))
        logger.warning(f"[AV-Earnings] {ticker} API 限制: {msg[:80]}")
        return None

    raw = data.get("quarterlyEarnings", [])
    if not raw:
        return None

    quarterly = []
    for q in raw:
        reported = q.get("reportedEPS")
        estimated = q.get("estimatedEPS")
        surprise = q.get("surprisePercentage")
        quarterly.append({
            "date":              q.get("reportedDate", ""),
            "fiscal_end":        q.get("fiscalDateEnding", ""),
            "reported_eps":      float(reported) if reported not in (None, "", "None") else None,
            "estimated_eps":     float(estimated) if estimated not in (None, "", "None") else None,
            "surprise_pct":      float(surprise) if surprise not in (None, "", "None") else None,
            "revenue_actual":    None,
            "revenue_estimated": None,
            "is_future":         False,
        })

    quarterly.sort(key=lambda x: x["date"], reverse=True)
    return {"ticker": ticker, "quarterly": quarterly}


def _cache_valid(cache: dict, key: str, ttl: int) -> bool:
    entry = cache.get(key)
    if not entry:
        return False
    ts, _ = entry
    return (time.time() - ts) < ttl


def _cache_get(cache: dict, key: str):
    entry = cache.get(key)
    return entry[1] if entry else None


def _cache_set(cache: dict, key: str, value):
    cache[key] = (time.time(), value)


async def get_earnings_history(
    ticker: str,
    session=None,  # 保留参数签名兼容性，不使用
) -> Optional[dict]:
    """
    获取季度 EPS 历史（兼容 fmp_client.get_earnings_history 签名）。
    数据源: Alpha Vantage EARNINGS（含 EPS 预期/惊喜值）。
    """
    if _cache_valid(_EARNINGS_CACHE, ticker, _TTL_SHORT):
        return _cache_get(_EARNINGS_CACHE, ticker)

    result = await _fetch_av_earnings(ticker)
    if not result:
        return None

    _cache_set(_EARNINGS_CACHE, ticker, result)
    return result


async def get_company_profile(
    ticker: str,
    session=None,
) -> Optional[dict]:
    """
    获取公司基础信息（兼容 fmp_client.get_company_profile 签名）。
    数据来源: Massive /v3/reference/tickers + /stocks/financials/v1/ratios
    """
    if _cache_valid(_PROFILE_CACHE, ticker, _TTL_LONG):
        return _cache_get(_PROFILE_CACHE, ticker)

    client = get_massive_client()
    ref_data, ratios_data = await asyncio.gather(
        client._get(f"/v3/reference/tickers/{ticker}"),
        client._get("/stocks/financials/v1/ratios",
                    params={"ticker": ticker, "limit": 1, "sort": "date.desc"}),
        return_exceptions=True,
    )

    result: dict = {"ticker": ticker, "company_name": "", "sector": "",
                    "industry": "", "market_cap": None, "pe_ratio": None,
                    "beta": None, "analyst_target_price": None,
                    "description": "", "exchange": "", "country": ""}

    if isinstance(ref_data, dict):
        ref = ref_data.get("results", {}) or {}
        result.update({
            "company_name": ref.get("name", ""),
            "sector":       ref.get("sic_description", ""),
            "industry":     ref.get("sic_description", ""),
            "description":  (ref.get("description") or "")[:300],
            "exchange":     ref.get("primary_exchange", ""),
            "country":      ref.get("locale", "us").upper(),
        })

    if isinstance(ratios_data, dict):
        items = ratios_data.get("results", [])
        r = items[0] if items else {}
        result["market_cap"] = r.get("market_cap")
        result["pe_ratio"]   = r.get("price_to_earnings")

    _cache_set(_PROFILE_CACHE, ticker, result)
    return result


async def get_ratios_ttm(
    ticker: str,
    session=None,
) -> Optional[dict]:
    """
    获取 TTM 财务比率（兼容 fmp_client.get_ratios_ttm 签名）。
    数据来源: Massive /stocks/financials/v1/ratios
    """
    if _cache_valid(_RATIOS_CACHE, ticker, _TTL_LONG):
        return _cache_get(_RATIOS_CACHE, ticker)

    client = get_massive_client()
    data = await client._get(
        "/stocks/financials/v1/ratios",
        params={"ticker": ticker, "limit": 1, "sort": "date.desc"}
    )
    if not data:
        return None

    items = data.get("results", [])
    r = items[0] if items else {}
    result = {
        "ticker":             ticker,
        "pe_ratio_ttm":       r.get("price_to_earnings"),
        "peg_ratio_ttm":      None,
        "roe_ttm":            r.get("return_on_equity"),
        "profit_margin_ttm":  None,
        "gross_margin_ttm":   None,
        "debt_to_equity_ttm": r.get("debt_to_equity"),
        "current_ratio_ttm":  r.get("current"),
        "roa_ttm":            r.get("return_on_assets"),
    }
    _cache_set(_RATIOS_CACHE, ticker, result)
    return result


async def get_income_statement(
    ticker: str,
    session=None,
    limit: int = 4,
) -> Optional[dict]:
    """
    获取季度利润表（兼容 fmp_client.get_income_statement 签名）。
    """
    if _cache_valid(_INCOME_CACHE, ticker, _TTL_LONG):
        return _cache_get(_INCOME_CACHE, ticker)

    client = get_massive_client()
    data = await client._get(
        "/stocks/financials/v1/income-statements",
        params={"tickers": ticker, "timeframe": "quarterly",
                "limit": limit, "sort": "period_end.desc"}
    )
    if not data:
        return None

    quarterly = []
    for q in data.get("results", []):
        rev = q.get("revenue") or 0
        gp  = q.get("gross_profit") or 0
        eps = q.get("basic_earnings_per_share") or q.get("diluted_earnings_per_share")
        quarterly.append({
            "date":             q.get("period_end", ""),
            "revenue":          rev,
            "gross_profit":     gp,
            "operating_income": q.get("operating_income"),
            "net_income":       q.get("consolidated_net_income_loss"),
            "eps":              float(eps) if eps is not None else None,
            "gross_margin":     round(gp / rev, 4) if rev else None,
        })

    result = {"ticker": ticker, "quarterly": quarterly}
    _cache_set(_INCOME_CACHE, ticker, result)
    return result


async def get_cash_flow_statement(
    ticker: str,
    session=None,
    limit: int = 4,
) -> Optional[dict]:
    """
    获取季度现金流（兼容 fmp_client.get_cash_flow_statement 签名）。
    """
    if _cache_valid(_CASHFLOW_CACHE, ticker, _TTL_LONG):
        return _cache_get(_CASHFLOW_CACHE, ticker)

    client = get_massive_client()
    data = await client._get(
        "/stocks/financials/v1/cash-flow-statements",
        params={"tickers": ticker, "timeframe": "quarterly",
                "limit": limit, "sort": "period_end.desc"}
    )
    if not data:
        return None

    quarterly = []
    for q in data.get("results", []):
        op_cf = q.get("net_cash_from_operating_activities")
        capex = q.get("purchase_of_property_plant_and_equipment")
        fcf   = q.get("free_cash_flow")
        if fcf is None and op_cf is not None and capex is not None:
            fcf = op_cf + capex  # capex 通常为负值
        quarterly.append({
            "date":               q.get("period_end", ""),
            "operating_cashflow": op_cf,
            "capex":              capex,
            "free_cashflow":      fcf,
            "net_change_in_cash": q.get("change_in_cash_and_equivalents"),
        })

    result = {"ticker": ticker, "quarterly": quarterly}
    _cache_set(_CASHFLOW_CACHE, ticker, result)
    return result


# ------------------------------------------------------------------
# 批量获取工具（高并发）
# ------------------------------------------------------------------

async def _batch_fetch(
    tickers: list,
    fetch_fn,
    concurrency: int = 20,
    label: str = "unknown",
) -> dict:
    """通用批量获取，控制并发。"""
    results = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(ticker: str):
        async with semaphore:
            data = await fetch_fn(ticker)
            if data:
                results[ticker] = data

    await asyncio.gather(*[fetch_one(t) for t in tickers], return_exceptions=True)
    logger.info(f"[Massive] batch_{label}: {len(results)}/{len(tickers)} 成功")
    return results


async def batch_get_earnings(tickers: list, concurrency: int = 5) -> dict:
    """
    批量获取季度 EPS 历史（Alpha Vantage EARNINGS）。
    AV 付费版 75次/分钟，concurrency=5 + 0.8s delay ≈ 安全速率。
    """
    return await _batch_fetch(tickers, get_earnings_history, concurrency, "earnings")


async def batch_get_profiles(tickers: list, concurrency: int = 20) -> dict:
    """批量获取公司概况。"""
    return await _batch_fetch(tickers, get_company_profile, concurrency, "profiles")


async def batch_get_ratios(tickers: list, concurrency: int = 20) -> dict:
    """批量获取 TTM 财务比率。"""
    return await _batch_fetch(tickers, get_ratios_ttm, concurrency, "ratios")


async def batch_get_income(tickers: list, concurrency: int = 20) -> dict:
    """批量获取季度利润表。"""
    return await _batch_fetch(tickers, get_income_statement, concurrency, "income")


async def batch_get_cashflow(tickers: list, concurrency: int = 20) -> dict:
    """批量获取季度现金流。"""
    return await _batch_fetch(tickers, get_cash_flow_statement, concurrency, "cashflow")


async def get_earnings_calendar(horizon: str = "3month") -> list:
    """
    顶层函数：获取 AV EARNINGS_CALENDAR（全市场未来计划财报日期）。
    委托给 MassiveDataClient 实例执行，结果磁盘缓存 12 小时。
    horizon: "3month" | "6month" | "12month"
    返回 list[dict]: {ticker, name, report_date, fiscal_date_ending, estimate, currency}
    """
    client = get_massive_client()
    return await client.get_earnings_calendar(horizon=horizon)
