"""
铃铛策略日状态（watchlist / 建仓重试 / 部分止盈标记）— 存 Supabase cache_store
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

import pytz

from app.database import get_db

logger = logging.getLogger(__name__)

CACHE_KEY = "intraday_strategy_state"
ET = pytz.timezone("US/Eastern")


def load_state() -> Dict[str, Any]:
    try:
        r = get_db().table("cache_store").select("value").eq("key", CACHE_KEY).limit(1).execute()
        if r.data and r.data[0].get("value"):
            v = r.data[0]["value"]
            if isinstance(v, dict):
                return v
    except Exception as e:
        logger.warning(f"[intraday_state] load failed: {e}")
    return {}


def save_state(state: Dict[str, Any]) -> None:
    try:
        get_db().table("cache_store").upsert(
            {"key": CACHE_KEY, "value": state},
        ).execute()
    except Exception as e:
        logger.error(f"[intraday_state] save failed: {e}")


def et_today_str() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def ensure_fresh_trading_day(state: Dict[str, Any]) -> Dict[str, Any]:
    """新交易日清空当日临时字段（保留结构）。"""
    d = et_today_str()
    if state.get("et_date") == d:
        return state
    return {
        "et_date": d,
        "watchlist": [],
        "retry": [],
        "partial_tickers": {},
        "entry_scores": {},
        "entry_times_et": {},
    }
