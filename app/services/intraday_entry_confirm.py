"""
铃铛建仓前确认：近 N 根 30min K 阳线比例 + 距近期高点距离，减轻追高与大盘股滞后信号问题。
"""

from __future__ import annotations

import logging
from typing import Any, Tuple

logger = logging.getLogger(__name__)


async def check_entry_confirmation(massive, ticker: str, cfg: Any) -> Tuple[bool, str]:
    """
    Returns:
        (True, "") 通过
        (False, reason) 跳过建仓（reason 写入 execute_entry）
    """
    if not getattr(cfg, "ENTRY_CONFIRM_ENABLED", False):
        return True, ""

    n = int(getattr(cfg, "ENTRY_CONFIRM_LOOKBACK_BARS", 5) or 5)
    min_green = float(getattr(cfg, "ENTRY_CONFIRM_MIN_GREEN_RATIO", 0.6) or 0.0)
    max_dist = float(getattr(cfg, "ENTRY_CONFIRM_MAX_DIST_FROM_HIGH_PCT", 0.005) or 0.0)

    try:
        arrays = await massive.get_intraday_arrays(
            ticker,
            getattr(cfg, "TIMESPAN", "minute"),
            int(getattr(cfg, "MULTIPLIER", 30)),
            int(getattr(cfg, "LOOKBACK_DAYS", 3)),
        )
    except Exception as e:
        logger.warning(f"[ENTRY-CONFIRM] {ticker} fetch failed: {e}")
        return False, "entry_confirm_fetch_error"

    if not arrays:
        return False, "entry_confirm_no_bars"

    opens = arrays.get("open") or []
    closes = arrays.get("close") or []
    highs = arrays.get("high") or []
    if len(closes) < n or len(opens) < n or len(highs) < n:
        return False, "entry_confirm_insufficient_bars"

    o = opens[-n:]
    c = closes[-n:]
    h = highs[-n:]
    greens = sum(1 for i in range(n) if float(c[i]) > float(o[i]))
    ratio = greens / float(n)
    if ratio + 1e-9 < min_green:
        return False, f"entry_confirm_green_ratio_{ratio:.2f}_lt_{min_green}"

    recent_high = max(float(x) for x in h)
    last_close = float(c[-1])
    if recent_high <= 0:
        return False, "entry_confirm_bad_high"

    # 现价不得离近 N 根最高价太远（默认允许最多低于最高价 0.5%）
    floor_px = recent_high * (1.0 - max_dist)
    if last_close < floor_px:
        return False, "entry_confirm_too_far_from_recent_high"

    return True, ""
