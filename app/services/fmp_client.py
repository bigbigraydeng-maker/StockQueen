"""
StockQueen - Financial Modeling Prep (FMP) 客户端
用于获取基本面数据（批量，FMP 高级版）。

端点基础: /stable/
覆盖范围:
  - 历史季度财报 EPS（/stable/earnings）
  - 公司概况 profile（/stable/profile）
  - TTM 财务比率（/stable/ratios-ttm）
  - 季度收入表（/stable/income-statement）
  - 季度现金流（/stable/cash-flow-statement）

高级版并发: 50 个并发请求，~300-750 req/min 限额内可覆盖 1578 只动态池
"""

import os
import time
import logging
import asyncio
import aiohttp
from typing import Optional

logger = logging.getLogger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"

# 各类型独立缓存，TTL 可差异化
_EARNINGS_CACHE:  dict = {}   # 12h
_PROFILE_CACHE:   dict = {}   # 7d（基本面变化慢）
_RATIOS_CACHE:    dict = {}   # 7d
_INCOME_CACHE:    dict = {}   # 7d
_CASHFLOW_CACHE:  dict = {}   # 7d

_TTL_SHORT = 43200        # 12h - 财报（可能有新季度）
_TTL_LONG  = 7 * 86400   # 7d  - 概况/比率/报表


def _get_api_key() -> str:
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        raise ValueError("FMP_API_KEY 未设置，请在 .env 文件中配置")
    return key


def _cache_valid(cache: dict, key: str, ttl: int) -> bool:
    entry = cache.get(key)
    if not entry:
        return False
    ts, _ = entry
    return (time.time() - ts) < ttl


def _cache_get(cache: dict, key: str):
    entry = cache.get(key)
    return entry[1] if entry else None


def _cache_set(cache: dict, key: str, value, ttl_unused=None):
    cache[key] = (time.time(), value)


# ============================================================
# 1. 历史季度财报 EPS
# ============================================================

async def get_earnings_history(
    ticker: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> Optional[dict]:
    """
    获取股票历史季度EPS数据（实际 vs 预期）。

    Returns:
        {
            "ticker": str,
            "quarterly": [
                {
                    "date": "2018-02-01",
                    "reported_eps": 0.97,
                    "estimated_eps": 0.96,
                    "surprise_pct": 1.04,
                    "revenue_actual": 88293000000,
                    "revenue_estimated": 87612077120,
                    "is_future": False,
                }
            ]
        }
    """
    if _cache_valid(_EARNINGS_CACHE, ticker, _TTL_SHORT):
        return _cache_get(_EARNINGS_CACHE, ticker)

    api_key = _get_api_key()
    url = f"{FMP_BASE_URL}/earnings"
    params = {"symbol": ticker, "apikey": api_key}

    try:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning(f"[FMP] {ticker} earnings HTTP {resp.status}")
                return None
            raw = await resp.json(content_type=None)

        if close_session:
            await session.close()

        if not isinstance(raw, list) or len(raw) == 0:
            return None

        quarterly = []
        for q in raw:
            eps_actual = q.get("epsActual")
            eps_est    = q.get("epsEstimated")

            if eps_actual is None:
                quarterly.append({
                    "date":              q.get("date", ""),
                    "reported_eps":      None,
                    "estimated_eps":     eps_est,
                    "surprise_pct":      None,
                    "revenue_actual":    None,
                    "revenue_estimated": q.get("revenueEstimated"),
                    "is_future":         True,
                })
                continue

            surprise_pct = None
            if eps_est and eps_est != 0:
                surprise_pct = round(((eps_actual - eps_est) / abs(eps_est)) * 100, 2)

            quarterly.append({
                "date":               q.get("date", ""),
                "reported_eps":       eps_actual,
                "estimated_eps":      eps_est,
                "surprise_pct":       surprise_pct,
                "revenue_actual":     q.get("revenueActual"),
                "revenue_estimated":  q.get("revenueEstimated"),
                "is_future":          False,
            })

        quarterly.sort(key=lambda x: x["date"], reverse=True)
        result = {"ticker": ticker, "quarterly": quarterly}
        _cache_set(_EARNINGS_CACHE, ticker, result)
        return result

    except asyncio.TimeoutError:
        logger.warning(f"[FMP] {ticker} earnings 请求超时")
        return None
    except Exception as e:
        logger.warning(f"[FMP] {ticker} earnings 异常: {e}")
        return None


# ============================================================
# 2. 公司概况 Profile
# ============================================================

async def get_company_profile(
    ticker: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> Optional[dict]:
    """
    获取公司基础信息：行业、市值、PE、Beta、分析师目标价等。

    Returns:
        {
            "ticker": str,
            "company_name": str,
            "sector": str,
            "industry": str,
            "market_cap": float,
            "pe_ratio": float,
            "beta": float,
            "analyst_target_price": float,
            "description": str,
        }
    """
    if _cache_valid(_PROFILE_CACHE, ticker, _TTL_LONG):
        return _cache_get(_PROFILE_CACHE, ticker)

    api_key = _get_api_key()
    url = f"{FMP_BASE_URL}/profile"
    params = {"symbol": ticker, "apikey": api_key}

    try:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.debug(f"[FMP] {ticker} profile HTTP {resp.status}")
                return None
            raw = await resp.json(content_type=None)

        if close_session:
            await session.close()

        # FMP profile returns a list with one item
        if isinstance(raw, list) and raw:
            p = raw[0]
        elif isinstance(raw, dict):
            p = raw
        else:
            return None

        result = {
            "ticker":               ticker,
            "company_name":         p.get("companyName", ""),
            "sector":               p.get("sector", ""),
            "industry":             p.get("industry", ""),
            "market_cap":           p.get("mktCap") or p.get("marketCap"),
            "pe_ratio":             p.get("pe"),
            "beta":                 p.get("beta"),
            "analyst_target_price": p.get("dcfDiff") or p.get("price"),  # analyst target if available
            "description":          (p.get("description") or "")[:300],
            "exchange":             p.get("exchangeShortName", ""),
            "country":              p.get("country", ""),
        }
        _cache_set(_PROFILE_CACHE, ticker, result)
        return result

    except asyncio.TimeoutError:
        logger.debug(f"[FMP] {ticker} profile 超时")
        return None
    except Exception as e:
        logger.debug(f"[FMP] {ticker} profile 异常: {e}")
        return None


# ============================================================
# 3. TTM 财务比率
# ============================================================

async def get_ratios_ttm(
    ticker: str,
    session: Optional[aiohttp.ClientSession] = None,
) -> Optional[dict]:
    """
    获取 TTM（过去12个月）财务比率：ROE、毛利率、净利率、PEG、负债比等。

    Returns:
        {
            "ticker": str,
            "pe_ratio_ttm": float,
            "peg_ratio_ttm": float,
            "roe_ttm": float,
            "profit_margin_ttm": float,
            "gross_margin_ttm": float,
            "debt_to_equity_ttm": float,
            "current_ratio_ttm": float,
        }
    """
    if _cache_valid(_RATIOS_CACHE, ticker, _TTL_LONG):
        return _cache_get(_RATIOS_CACHE, ticker)

    api_key = _get_api_key()
    url = f"{FMP_BASE_URL}/ratios-ttm"
    params = {"symbol": ticker, "apikey": api_key}

    try:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.debug(f"[FMP] {ticker} ratios-ttm HTTP {resp.status}")
                return None
            raw = await resp.json(content_type=None)

        if close_session:
            await session.close()

        if isinstance(raw, list) and raw:
            r = raw[0]
        elif isinstance(raw, dict):
            r = raw
        else:
            return None

        result = {
            "ticker":             ticker,
            "pe_ratio_ttm":       r.get("peRatioTTM"),
            "peg_ratio_ttm":      r.get("pegRatioTTM"),
            "roe_ttm":            r.get("returnOnEquityTTM"),
            "profit_margin_ttm":  r.get("netProfitMarginTTM"),
            "gross_margin_ttm":   r.get("grossProfitMarginTTM"),
            "debt_to_equity_ttm": r.get("debtEquityRatioTTM"),
            "current_ratio_ttm":  r.get("currentRatioTTM"),
            "roa_ttm":            r.get("returnOnAssetsTTM"),
        }
        _cache_set(_RATIOS_CACHE, ticker, result)
        return result

    except asyncio.TimeoutError:
        logger.debug(f"[FMP] {ticker} ratios-ttm 超时")
        return None
    except Exception as e:
        logger.debug(f"[FMP] {ticker} ratios-ttm 异常: {e}")
        return None


# ============================================================
# 4. 季度收入表
# ============================================================

async def get_income_statement(
    ticker: str,
    session: Optional[aiohttp.ClientSession] = None,
    limit: int = 4,
) -> Optional[dict]:
    """
    获取最近 limit 个季度的收入表数据。

    Returns:
        {
            "ticker": str,
            "quarterly": [
                {
                    "date": "2024-09-30",
                    "revenue": 94930000000,
                    "gross_profit": 43880000000,
                    "operating_income": 29590000000,
                    "net_income": 14736000000,
                    "eps": 0.97,
                    "gross_margin": 0.462,
                }
            ]
        }
    """
    if _cache_valid(_INCOME_CACHE, ticker, _TTL_LONG):
        return _cache_get(_INCOME_CACHE, ticker)

    api_key = _get_api_key()
    url = f"{FMP_BASE_URL}/income-statement"
    params = {"symbol": ticker, "period": "quarter", "limit": limit, "apikey": api_key}

    try:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.debug(f"[FMP] {ticker} income-statement HTTP {resp.status}")
                return None
            raw = await resp.json(content_type=None)

        if close_session:
            await session.close()

        if not isinstance(raw, list) or not raw:
            return None

        quarterly = []
        for q in raw:
            rev = q.get("revenue") or 0
            gp  = q.get("grossProfit") or 0
            quarterly.append({
                "date":             q.get("date", ""),
                "revenue":          rev,
                "gross_profit":     gp,
                "operating_income": q.get("operatingIncome"),
                "net_income":       q.get("netIncome"),
                "eps":              q.get("eps"),
                "gross_margin":     round(gp / rev, 4) if rev else None,
            })

        result = {"ticker": ticker, "quarterly": quarterly}
        _cache_set(_INCOME_CACHE, ticker, result)
        return result

    except asyncio.TimeoutError:
        logger.debug(f"[FMP] {ticker} income-statement 超时")
        return None
    except Exception as e:
        logger.debug(f"[FMP] {ticker} income-statement 异常: {e}")
        return None


# ============================================================
# 5. 季度现金流
# ============================================================

async def get_cash_flow_statement(
    ticker: str,
    session: Optional[aiohttp.ClientSession] = None,
    limit: int = 4,
) -> Optional[dict]:
    """
    获取最近 limit 个季度的现金流数据。

    Returns:
        {
            "ticker": str,
            "quarterly": [
                {
                    "date": "2024-09-30",
                    "operating_cashflow": 26811000000,
                    "capex": -2908000000,
                    "free_cashflow": 23903000000,
                    "net_change_in_cash": 5665000000,
                }
            ]
        }
    """
    if _cache_valid(_CASHFLOW_CACHE, ticker, _TTL_LONG):
        return _cache_get(_CASHFLOW_CACHE, ticker)

    api_key = _get_api_key()
    url = f"{FMP_BASE_URL}/cash-flow-statement"
    params = {"symbol": ticker, "period": "quarter", "limit": limit, "apikey": api_key}

    try:
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.debug(f"[FMP] {ticker} cash-flow-statement HTTP {resp.status}")
                return None
            raw = await resp.json(content_type=None)

        if close_session:
            await session.close()

        if not isinstance(raw, list) or not raw:
            return None

        quarterly = []
        for q in raw:
            op_cf  = q.get("operatingCashFlow") or q.get("netCashProvidedByOperatingActivities")
            capex  = q.get("capitalExpenditure") or q.get("investmentsInPropertyPlantAndEquipment")
            fcf    = q.get("freeCashFlow")
            if fcf is None and op_cf is not None and capex is not None:
                fcf = op_cf + capex  # capex is usually negative
            quarterly.append({
                "date":               q.get("date", ""),
                "operating_cashflow": op_cf,
                "capex":              capex,
                "free_cashflow":      fcf,
                "net_change_in_cash": q.get("netChangeInCash"),
            })

        result = {"ticker": ticker, "quarterly": quarterly}
        _cache_set(_CASHFLOW_CACHE, ticker, result)
        return result

    except asyncio.TimeoutError:
        logger.debug(f"[FMP] {ticker} cash-flow-statement 超时")
        return None
    except Exception as e:
        logger.debug(f"[FMP] {ticker} cash-flow-statement 异常: {e}")
        return None


# ============================================================
# 批量获取工具（高并发，FMP 高级版 300-750 req/min）
# ============================================================

async def _batch_fetch(
    tickers: list[str],
    fetch_fn,
    concurrency: int = 50,
    label: str = "unknown",
) -> dict[str, dict]:
    """通用批量获取，控制并发，忽略失败项。"""
    results = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(ticker: str, session: aiohttp.ClientSession):
        async with semaphore:
            data = await fetch_fn(ticker, session=session)
            if data:
                results[ticker] = data

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_one(t, session) for t in tickers]
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"[FMP] batch_{label}: {len(results)}/{len(tickers)} 成功")
    return results


async def batch_get_earnings(
    tickers: list[str],
    concurrency: int = 50,
) -> dict[str, dict]:
    """批量获取历史财报 EPS，高并发版本（FMP 高级版）。"""
    return await _batch_fetch(tickers, get_earnings_history, concurrency, "earnings")


async def batch_get_profiles(
    tickers: list[str],
    concurrency: int = 50,
) -> dict[str, dict]:
    """批量获取公司概况（行业、市值、PE、Beta 等）。"""
    return await _batch_fetch(tickers, get_company_profile, concurrency, "profiles")


async def batch_get_ratios(
    tickers: list[str],
    concurrency: int = 50,
) -> dict[str, dict]:
    """批量获取 TTM 财务比率（ROE、毛利率、PEG 等）。"""
    return await _batch_fetch(tickers, get_ratios_ttm, concurrency, "ratios")


async def batch_get_income(
    tickers: list[str],
    concurrency: int = 50,
) -> dict[str, dict]:
    """批量获取季度收入表（收入、毛利、净利润等）。"""
    return await _batch_fetch(tickers, get_income_statement, concurrency, "income")


async def batch_get_cashflow(
    tickers: list[str],
    concurrency: int = 50,
) -> dict[str, dict]:
    """批量获取季度现金流（经营CF、FCF 等）。"""
    return await _batch_fetch(tickers, get_cash_flow_statement, concurrency, "cashflow")
