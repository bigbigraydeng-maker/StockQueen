"""
监控大屏辅助：信号雷达（1m 微结构）、市场门控条、持仓 ATR 距离。

数据说明：
- 「预测分」为启发式：最近 1 分钟收益 ×2 + _bar 内价位失衡 ×5，再限幅，非 ML 预测。
- 买卖盘失衡在无 L2 时用最后一根 1m K 的收在区间位置近似。
- ATR 为 1m 上最后 14 根 TR 的算术均值（快速近似）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

FAST_BAR_TTL_SEC = 45


def _atr_sma14(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Optional[float]:
    if len(close) < 15:
        return None
    h = high.astype(float)
    l = low.astype(float)
    c = close.astype(float)
    prev_c = np.empty_like(c)
    prev_c[0] = c[0]
    prev_c[1:] = c[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    return float(np.mean(tr[-14:]))


async def build_signal_radar_rows(max_rows: int = 12) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """基于最近一轮铃铛评分 Top N，叠加 1m 条计算预测分与上行空间。"""
    from app.services.intraday_service import get_cached_intraday_scores
    from app.services.massive_client import get_massive_client

    cache = get_cached_intraday_scores()
    if not cache or not cache.get("top"):
        return (
            [],
            "暂无盘中评分缓存 — 交易时段每 30 分钟更新，或使用下方「手动触发评分」",
        )

    top = cache["top"][:max_rows]
    client = get_massive_client()
    sem = asyncio.Semaphore(8)

    async def _one(idx: int, row: dict) -> Optional[Dict[str, Any]]:
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            return None
        total = float(row.get("total_score", 0))
        rank = int(row.get("rank", idx + 1))
        async with sem:
            try:
                df = await client.get_intraday_history(
                    ticker,
                    "minute",
                    1,
                    1,
                    cache_ttl_seconds=FAST_BAR_TTL_SEC,
                )
            except Exception as e:
                logger.debug("monitor radar bars %s: %s", ticker, e)
                df = None
        if df is None or df.empty or len(df) < 3:
            return {
                "ticker": ticker,
                "total_score": total,
                "pred_score": total,
                "upside_atr": None,
                "imbalance": None,
                "flash_pred": False,
                "rank": rank,
            }

        h = df["High"].values
        l = df["Low"].values
        c = df["Close"].values
        atr = _atr_sma14(h, l, c)
        price = float(c[-1])
        prev = float(c[-2])
        ret_1m = (price - prev) / prev if prev > 0 else 0.0
        hl = float(h[-1]) - float(l[-1])
        if hl > 1e-9:
            imb = (price - float(l[-1])) / hl * 2.0 - 1.0
        else:
            imb = 0.0
        raw = ret_1m * 2.0 + imb * 5.0
        pred = max(-10.0, min(10.0, raw * 5.0))
        if atr and atr > 0:
            recent_high = float(np.max(h[-5:]))
            upside_atr = max(0.0, (recent_high - price) / atr)
        else:
            upside_atr = None
        flash = pred > total + 1.5
        return {
            "ticker": ticker,
            "total_score": total,
            "pred_score": pred,
            "upside_atr": upside_atr,
            "imbalance": imb,
            "flash_pred": flash,
            "rank": rank,
        }

    gathered = await asyncio.gather(*[_one(i, r) for i, r in enumerate(top)])
    rows = [x for x in gathered if x]
    rows.sort(key=lambda x: x["total_score"], reverse=True)
    for i, r in enumerate(rows):
        r["display_rank"] = i + 1
    return rows, None


async def compute_market_gate() -> Dict[str, Any]:
    """顶部门控：SPY 5×1m 斜率 + ETF 涨跌近似 VIX/宽度（无全市场宽度时的务实替代）。"""
    from app.services.alphavantage_client import get_av_client
    from app.services.massive_client import get_massive_client

    av = get_av_client()
    quotes = await av.batch_get_quotes(["SPY", "VIXY", "IWM", "QQQ"])
    client = get_massive_client()
    spy_slope = 0.0
    try:
        spy_df = await client.get_intraday_history(
            "SPY", "minute", 1, 1, cache_ttl_seconds=FAST_BAR_TTL_SEC
        )
        if spy_df is not None and len(spy_df) >= 6:
            c = spy_df["Close"].values
            base = float(c[-6])
            if base > 0:
                spy_slope = (float(c[-1]) - base) / base
    except Exception as e:
        logger.debug("market gate SPY slope: %s", e)

    def _pct(t: str) -> float:
        q = quotes.get(t) or {}
        try:
            return float(q.get("change_percent") or 0)
        except (TypeError, ValueError):
            return 0.0

    spy_pct = _pct("SPY")
    vixy_pct = _pct("VIXY")
    iwm_pct = _pct("IWM")
    qqq_pct = _pct("QQQ")

    # 简易「宽度」代理：中小盘 + 科技 同向偏多时抬高
    breadth_proxy = 0.45
    if spy_pct > 0 and iwm_pct > 0:
        breadth_proxy = 0.62
    if spy_pct > 0 and iwm_pct > 0 and qqq_pct > 0:
        breadth_proxy = 0.72

    allow_long = spy_slope > 0.001 and vixy_pct < 2.0 and breadth_proxy >= 0.5
    block_spy = spy_pct <= -0.3
    reduce_half = vixy_pct >= 2.0

    if block_spy:
        state = "block"
        emoji = "🔴"
        label = "禁止开新仓"
        detail = f"SPY 当日 {spy_pct:+.2f}% ≤ -0.3% — 暂停新开多"
    elif reduce_half:
        state = "caution"
        emoji = "🟠"
        label = "建议减仓"
        detail = f"VIXY 当日 +{vixy_pct:.2f}% ≥ 2% — 建议减仓约 50%"
    elif allow_long:
        state = "ok"
        emoji = "🟢"
        label = "可开多仓（条件满足）"
        detail = (
            f"SPY 5×1m 斜率 {spy_slope * 100:+.3f}% · VIXY {vixy_pct:+.2f}% · "
            f"宽度代理 {breadth_proxy:.2f}"
        )
    else:
        state = "neutral"
        emoji = "🟡"
        label = "观望"
        detail = (
            f"SPY 斜率 {spy_slope * 100:+.3f}% · VIXY {vixy_pct:+.2f}% · "
            f"宽度代理 {breadth_proxy:.2f}"
        )

    return {
        "state": state,
        "emoji": emoji,
        "label": label,
        "detail": detail,
        "spy_slope_pct": spy_slope * 100,
        "spy_day_pct": spy_pct,
        "vixy_day_pct": vixy_pct,
        "breadth_proxy": breadth_proxy,
        "block_new_long": block_spy,
        "suggest_reduce": reduce_half,
    }


async def atr_and_distances_for_ticker(ticker: str, price: float, tp_price: Optional[float], sl_price: Optional[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """返回 (atr_1m, dist_tp_atr, dist_sl_atr)。"""
    from app.services.massive_client import get_massive_client

    t = str(ticker or "").upper().strip()
    if not t or price <= 0:
        return None, None, None
    try:
        df = await get_massive_client().get_intraday_history(
            t, "minute", 1, 1, cache_ttl_seconds=FAST_BAR_TTL_SEC
        )
    except Exception:
        df = None
    if df is None or len(df) < 15:
        return None, None, None
    h, l, c = df["High"].values, df["Low"].values, df["Close"].values
    atr = _atr_sma14(h, l, c)
    if not atr or atr <= 0:
        return atr, None, None
    d_tp = None
    d_sl = None
    if tp_price and tp_price > price:
        d_tp = (tp_price - price) / atr
    if sl_price and sl_price < price:
        d_sl = (price - sl_price) / atr
    return atr, d_tp, d_sl
