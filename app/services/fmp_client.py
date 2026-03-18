"""
StockQueen - Financial Modeling Prep (FMP) 客户端
用于获取历史季度财报数据（EPS实际 vs 预期），补充 Alpha Vantage 仅有3年历史的不足。

API端点：/stable/earnings
覆盖范围：1985年至今，免费版250次/天
"""

import os
import time
import logging
import asyncio
import aiohttp
from typing import Optional

logger = logging.getLogger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
_FMP_CACHE: dict = {}  # 内存缓存，key=ticker，value=(timestamp, data)
_CACHE_TTL = 43200  # 12小时


def _get_api_key() -> str:
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        raise ValueError("FMP_API_KEY 未设置，请在 .env 文件中配置")
    return key


def _is_cache_valid(entry) -> bool:
    if not entry:
        return False
    ts, _ = entry
    return (time.time() - ts) < _CACHE_TTL


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
                    "date": "2018-02-01",          # 财报发布日
                    "reported_eps": 0.97,
                    "estimated_eps": 0.96,
                    "surprise_pct": 1.04,           # 超预期百分比
                    "revenue_actual": 88293000000,
                    "revenue_estimated": 87612077120,
                }
            ]
        }
    """
    # 检查缓存
    if _is_cache_valid(_FMP_CACHE.get(ticker)):
        _, data = _FMP_CACHE[ticker]
        return data

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
                logger.warning(f"[FMP] {ticker} HTTP {resp.status}")
                return None
            raw = await resp.json(content_type=None)

        if close_session:
            await session.close()

        if not isinstance(raw, list) or len(raw) == 0:
            logger.debug(f"[FMP] {ticker} 无数据")
            return None

        quarterly = []
        for q in raw:
            eps_actual = q.get("epsActual")
            eps_est    = q.get("epsEstimated")

            if eps_actual is None:
                # 保留未来财报日期（实际值为空），供下次财报日期检测使用
                quarterly.append({
                    "date":              q.get("date", ""),
                    "reported_eps":      None,
                    "estimated_eps":     eps_est,
                    "surprise_pct":      None,
                    "revenue_actual":    None,
                    "revenue_estimated": q.get("revenueEstimated"),
                    "is_future":         True,  # 标记为未来财报
                })
                continue

            # 计算超预期幅度
            if eps_est and eps_est != 0:
                surprise_pct = ((eps_actual - eps_est) / abs(eps_est)) * 100
            else:
                surprise_pct = None

            quarterly.append({
                "date":               q.get("date", ""),
                "reported_eps":       eps_actual,
                "estimated_eps":      eps_est,
                "surprise_pct":       round(surprise_pct, 2) if surprise_pct is not None else None,
                "revenue_actual":     q.get("revenueActual"),
                "revenue_estimated":  q.get("revenueEstimated"),
                "is_future":          False,
            })

        # 按日期降序排列（最新在前）
        quarterly.sort(key=lambda x: x["date"], reverse=True)

        result = {"ticker": ticker, "quarterly": quarterly}

        # 写入缓存
        _FMP_CACHE[ticker] = (time.time(), result)
        logger.debug(f"[FMP] {ticker} 财报数据获取成功，共 {len(quarterly)} 条")
        return result

    except asyncio.TimeoutError:
        logger.warning(f"[FMP] {ticker} 请求超时")
        return None
    except Exception as e:
        logger.warning(f"[FMP] {ticker} 异常: {e}")
        return None


async def batch_get_earnings(
    tickers: list[str],
    concurrency: int = 5,
) -> dict[str, dict]:
    """
    批量获取多只股票的历史财报数据。
    concurrency：并发数（免费版250次/天，控制速率）
    """
    results = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(ticker: str, session: aiohttp.ClientSession):
        async with semaphore:
            data = await get_earnings_history(ticker, session=session)
            if data:
                results[ticker] = data
            await asyncio.sleep(0.1)  # 轻微限速，避免超限

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_one(t, session) for t in tickers]
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"[FMP] 批量获取完成: {len(results)}/{len(tickers)} 只成功")
    return results
