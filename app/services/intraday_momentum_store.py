"""
盘中动能持久化：写入 intraday_rounds + intraday_momentum_daily（Supabase）。
与 intraday_scores 明细表互补：前者便于「按轮」与「按票追踪当日动能」。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

from app.database import get_db

logger = logging.getLogger(__name__)
ET = pytz.timezone("US/Eastern")
MAX_RANK_HISTORY = 12


def _session_date_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def persist_round_and_momentum(
    *,
    round_num: int,
    scored_at_iso: str,
    scores: List[Dict[str, Any]],
    rows_persisted: int,
) -> None:
    """
    scores: 已含 rank、total_score、ticker；通常取全市场排序后前 50 与 rounds 摘要用同一批。
    """
    session_date = _session_date_et()
    db = get_db()

    top5_payload: List[Dict[str, Any]] = []
    for s in scores[:5]:
        top5_payload.append({
            "ticker": s.get("ticker"),
            "rank": s.get("rank"),
            "total_score": s.get("total_score"),
        })

    try:
        db.table("intraday_rounds").upsert(
            {
                "session_date": session_date,
                "round_number": round_num,
                "scored_at": scored_at_iso,
                "total_scored": len(scores),
                "rows_persisted": rows_persisted,
                "top5": top5_payload,
            },
            on_conflict="session_date,round_number",
        ).execute()
    except Exception as e:
        logger.warning(f"[INTRADAY-MOM] intraday_rounds upsert skipped/failed: {e}")

    if not scores:
        return

    try:
        prev = (
            db.table("intraday_momentum_daily")
            .select("*")
            .eq("session_date", session_date)
            .execute()
        )
        emap: Dict[str, Dict[str, Any]] = {
            str(r["ticker"]).upper(): r for r in (prev.data or []) if r.get("ticker")
        }
    except Exception as e:
        logger.warning(f"[INTRADAY-MOM] load momentum_daily failed: {e}")
        emap = {}

    upsert_rows: List[Dict[str, Any]] = []
    for s in scores[:50]:
        tkr = str(s.get("ticker", "")).upper().strip()
        if not tkr:
            continue
        rank = int(s.get("rank") or 0)
        score = float(s.get("total_score") or 0.0)
        ex = emap.get(tkr)

        hist: List[Dict[str, Any]] = []
        if ex and ex.get("rank_history"):
            raw = ex["rank_history"]
            if isinstance(raw, list):
                hist = list(raw)
        hist.append({"round": round_num, "rank": rank, "score": score, "at": scored_at_iso})
        hist = hist[-MAX_RANK_HISTORY:]

        best = rank
        worst = rank
        if ex:
            if ex.get("best_rank") is not None:
                best = min(best, int(ex["best_rank"]))
            if ex.get("worst_rank") is not None:
                worst = max(worst, int(ex["worst_rank"]))
        top20 = int(ex.get("rounds_in_top20") or 0) if ex else 0
        if rank <= 20:
            top20 += 1

        upsert_rows.append({
            "session_date": session_date,
            "ticker": tkr,
            "latest_rank": rank,
            "latest_total_score": score,
            "latest_round_number": round_num,
            "latest_scored_at": scored_at_iso,
            "best_rank": best,
            "worst_rank": worst,
            "rounds_in_top20": top20,
            "rank_history": hist,
            "updated_at": scored_at_iso,
        })

    if not upsert_rows:
        return

    try:
        db.table("intraday_momentum_daily").upsert(
            upsert_rows,
            on_conflict="session_date,ticker",
        ).execute()
        logger.info(
            f"[INTRADAY-MOM] momentum_daily upsert {len(upsert_rows)} tickers "
            f"session={session_date} round={round_num}"
        )
    except Exception as e:
        logger.error(f"[INTRADAY-MOM] momentum_daily upsert failed: {e}", exc_info=True)


def fetch_momentum_board(
    session_date: Optional[str] = None,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """当日动能榜（按最新名次排序）。"""
    d = session_date or _session_date_et()
    try:
        db = get_db()
        r = (
            db.table("intraday_momentum_daily")
            .select("*")
            .eq("session_date", d)
            .order("latest_rank")
            .limit(limit)
            .execute()
        )
        return r.data or []
    except Exception as e:
        logger.error(f"[INTRADAY-MOM] fetch_momentum_board: {e}")
        return []
