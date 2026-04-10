"""
StockQueen - Intraday Scoring Service
每 30 分钟运行一轮盘中评分，写入 Supabase，缓存到内存。

调度流程:
  1. 检查是否在交易时段（美东 10:00-16:00）
  2. 批量拉取 Universe 的 30min bars
  3. 拉取 SPY bars（relative_flow 基准）
  4. 对每只 ticker 调用 compute_intraday_score()
  5. 排序取前 WATCHLIST_SIZE（默认20）→ 写入 Supabase → 缓存
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, List

import pytz

from app.config.intraday_config import IntradayConfig
from app.services.intraday_scorer import compute_intraday_score
from app.services.massive_client import get_massive_client

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")

# Module-level cache
_scores_cache: Optional[dict] = None


def _is_market_open() -> bool:
    """检查当前是否在美东交易时段内。"""
    now_et = datetime.now(ET)
    # 周末不交易
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    from datetime import time as dt_time
    return dt_time(9, 30) <= t <= dt_time(16, 0)


def _current_round_number() -> int:
    """计算当前是第几轮评分（10:00=1, 10:30=2, ... 16:00=13）。"""
    now_et = datetime.now(ET)
    minutes_since_open = (now_et.hour - 10) * 60 + now_et.minute
    return max(1, minutes_since_open // 30 + 1)


async def run_intraday_scoring_round() -> dict:
    """
    执行一轮盘中评分。
    Returns: {"status": "ok"|"skipped", "top": [...], "round": int, "scored": int}
    """
    global _scores_cache

    if not _is_market_open():
        logger.info("[INTRADAY] Market closed, skipping scoring round")
        return {"status": "skipped", "reason": "market_closed"}

    round_num = _current_round_number()
    logger.info(f"[INTRADAY] Starting scoring round #{round_num}")

    client = get_massive_client()
    cfg = IntradayConfig

    # 1. 批量获取 Universe 的 30min bars
    all_bars = {}
    sem = asyncio.Semaphore(10)

    async def _fetch(ticker: str):
        async with sem:
            try:
                arrays = await client.get_intraday_arrays(
                    ticker, cfg.TIMESPAN, cfg.MULTIPLIER, cfg.LOOKBACK_DAYS
                )
                if arrays is not None:
                    all_bars[ticker] = arrays
            except Exception as e:
                logger.warning(f"[INTRADAY] Failed to fetch {ticker}: {e}")

    results = await asyncio.gather(
        *[_fetch(t) for t in cfg.UNIVERSE],
        return_exceptions=True,
    )

    # Log any exceptions from gather itself
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        logger.warning(f"[INTRADAY] {len(errors)} fetch tasks failed with exceptions")

    if not all_bars:
        logger.warning("[INTRADAY] No intraday data fetched, aborting round")
        return {"status": "error", "reason": "no_data"}

    # 2. SPY bars for relative_flow
    spy_bars = all_bars.get("SPY")
    if spy_bars is None:
        try:
            spy_bars = await client.get_intraday_arrays("SPY", cfg.TIMESPAN, cfg.MULTIPLIER, cfg.LOOKBACK_DAYS)
            if spy_bars is None:
                logger.warning("[INTRADAY] SPY bars fetch returned None, relative_flow factor will be disabled")
        except Exception as e:
            logger.warning(f"[INTRADAY] Failed to fetch SPY bars: {e}, relative_flow factor disabled")

    # 3. Score each ticker
    scores: List[dict] = []
    for ticker, bars in all_bars.items():
        if ticker == "SPY":
            continue  # SPY is benchmark, not scored
        try:
            result = compute_intraday_score(bars, spy_bars)
            scores.append({
                "ticker": ticker,
                "total_score": result["total_score"],
                "factors": result["factors"],
                "weights_used": result["weights_used"],
                "latest_price": float(bars["close"][-1]) if len(bars["close"]) > 0 else 0,
                "vwap": result["factors"].get("vwap_deviation", {}).get("vwap", 0),
            })
        except Exception as e:
            logger.warning(f"[INTRADAY] Score error {ticker}: {e}")

    # 4. Sort and pick watchlist slice（默认前 20）
    scores.sort(key=lambda x: x["total_score"], reverse=True)
    top_n = scores[: cfg.WATCHLIST_SIZE]

    # Assign rank
    for i, s in enumerate(scores):
        s["rank"] = i + 1

    # 5. Write to Supabase
    now_iso = datetime.now(pytz.utc).isoformat()
    try:
        from app.database import get_db
        db = get_db()
        rows_to_insert = []
        for s in scores[:50]:  # Store top 50
            rows_to_insert.append({
                "ticker": s["ticker"],
                "scored_at": now_iso,
                "round_number": round_num,
                "total_score": s["total_score"],
                "factor_momentum": s["factors"].get("intraday_momentum", {}).get("score", 0),
                "factor_vwap": s["factors"].get("vwap_deviation", {}).get("score", 0),
                "factor_volume": s["factors"].get("volume_profile", {}).get("score", 0),
                "factor_rsi": s["factors"].get("micro_rsi", {}).get("score", 0),
                "factor_spread": s["factors"].get("spread_quality", {}).get("score", 0),
                "factor_relative": s["factors"].get("relative_flow", {}).get("score", 0),
                "rank": s["rank"],
                "latest_price": s["latest_price"],
                "vwap": s["vwap"],
            })
        if rows_to_insert:
            db.table("intraday_scores").insert(rows_to_insert).execute()
            logger.info(f"[INTRADAY] Wrote {len(rows_to_insert)} scores to DB (round #{round_num})")
            try:
                from app.services.intraday_momentum_store import persist_round_and_momentum

                persist_round_and_momentum(
                    round_num=round_num,
                    scored_at_iso=now_iso,
                    scores=scores,
                    rows_persisted=len(rows_to_insert),
                )
            except Exception as me:
                logger.warning(f"[INTRADAY] momentum tables persist failed (non-fatal): {me}")
    except Exception as e:
        logger.error(f"[INTRADAY] DB write failed: {e}")

    # 6. Update memory cache
    _scores_cache = {
        "scored_at": now_iso,
        "round": round_num,
        "total_scored": len(scores),
        "top": top_n,
        "all_scores": scores[:50],
    }

    logger.info(
        f"[INTRADAY] Round #{round_num} complete: "
        f"{len(scores)} scored, TOP={[s['ticker'] for s in top_n]}"
    )

    return {
        "status": "ok",
        "round": round_num,
        "total_scored": len(scores),
        "top": top_n,
        "all_scores": scores,
    }


def get_cached_intraday_scores() -> Optional[dict]:
    """获取最近一轮盘中评分缓存。"""
    return _scores_cache


async def get_intraday_signal_history(ticker: str, days: int = 5) -> list:
    """查询某只 ticker 的历史盘中评分。"""
    try:
        from app.database import get_db
        db = get_db()
        result = db.table("intraday_scores") \
            .select("*") \
            .eq("ticker", ticker) \
            .order("scored_at", desc=True) \
            .limit(days * 13) \
            .execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"[INTRADAY] History query failed for {ticker}: {e}")
        return []


# ============================================================
# 自动交易集成（可选开启）
# ============================================================

async def run_intraday_exits_only(enable_auto_execute: bool = False) -> dict:
    """
    仅执行铃铛减仓/止损/ATR（Pass A/B/C），不依赖本轮评分数据。

    用于：评分拉取失败（no_data）时仍尝试退出；以及 5min 调度，避免等 30min 才检查 +0.5% 减半。
    """
    if not enable_auto_execute:
        return {"status": "skipped", "reason": "auto_execute_disabled"}
    if not _is_market_open():
        return {"status": "skipped", "reason": "market_closed"}

    from app.services.intraday_trader import execute_intraday_trades

    dummy = {
        "status": "ok",
        "round": 0,
        "all_scores": [],
        "top": [],
        "total_scored": 0,
    }
    trade_result = await execute_intraday_trades(dummy, auto_execute=True)
    return {"status": "ok", "exit_only": True, "trading": trade_result}


async def run_intraday_trading_round(
    enable_auto_execute: bool = False
) -> dict:
    """
    完整的盘中评分 + 自动交易一体化流程
    
    Args:
        enable_auto_execute: 是否启用自动下单 (默认关闭，仅信号)
    
    Returns:
        {status, round, scores, trades}
    """
    # 第一步：运行评分
    score_result = await run_intraday_scoring_round()

    if score_result.get("status") == "ok":
        if enable_auto_execute:
            from app.services.intraday_trader import execute_intraday_trades
            trade_result = await execute_intraday_trades(
                score_result,
                auto_execute=True
            )
            return {
                **score_result,
                "trading": trade_result,
            }
        return score_result

    # 评分失败（如 no_data）时：盘中仍应检查止盈止损，否则减仓逻辑整轮不跑
    if (
        enable_auto_execute
        and score_result.get("status") == "error"
        and _is_market_open()
    ):
        from app.services.intraday_trader import execute_intraday_trades

        dummy = {
            "status": "ok",
            "round": 0,
            "all_scores": [],
            "top": [],
            "total_scored": 0,
        }
        trade_result = await execute_intraday_trades(dummy, auto_execute=True)
        return {
            **score_result,
            "trading": trade_result,
            "exit_only_fallback": True,
        }

    return score_result
