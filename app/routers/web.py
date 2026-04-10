"""
StockQueen V2.2 - Web Dashboard Router
Server-rendered pages using Jinja2 + TailwindCSS + HTMX.
Calls service layer directly (no HTTP round-trip to API).
"""

import json
import logging
import hashlib
import time
import asyncio
from datetime import date, datetime
from typing import Optional, Dict, Any, Tuple
from fastapi import APIRouter, BackgroundTasks, Request, Query, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings
from app.middleware.auth import require_admin

_limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


def _tpl(template_name: str, context: dict):
    """Render template with auto-injected is_guest flag from request.state."""
    request = context.get("request")
    if request and "is_guest" not in context:
        context["is_guest"] = getattr(request.state, "is_guest", False)
    # Starlette 1.0.0+ requires request as first positional argument
    return templates.TemplateResponse(request, template_name, context)


def _bao_dian_next_rebalance_info() -> Dict[str, Any]:
    """距下次宝典周调仓（RotationConfig.REBALANCE_DAY，按美东日历）。"""
    import pytz
    from datetime import datetime, timedelta
    from app.config.rotation_watchlist import RotationConfig as RC

    ET = pytz.timezone("US/Eastern")
    now = datetime.now(ET)
    d = now.date()
    wd = d.weekday()
    key = str(getattr(RC, "REBALANCE_DAY", "mon") or "mon").lower()[:3]
    target_wd = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}.get(key, 0)
    days_ahead = (target_wd - wd) % 7
    next_d = d + timedelta(days=days_ahead)
    if days_ahead == 0:
        label_short = "今日为调仓日"
    elif days_ahead == 1:
        label_short = "明日调仓"
    else:
        label_short = f"距下次调仓 {days_ahead} 天"
    return {
        "next_date_iso": next_d.isoformat(),
        "days_until": int(days_ahead),
        "label_short": label_short,
    }


def _intraday_leverage_row_extras(
    cost: float,
    price: float,
    entry_time_iso: Optional[str],
) -> Dict[str, Any]:
    """铃铛持仓：括号止盈参考价、软止损空间、按 30min bar 估算已持根数。"""
    from datetime import datetime
    import pytz
    from app.config.intraday_config import IntradayConfig as IC

    ET = pytz.timezone("US/Eastern")
    mult = int(getattr(IC, "MULTIPLIER", 30) or 30)
    max_bars = int(getattr(IC, "MAX_HOLD_BARS", 13) or 13)
    out: Dict[str, Any] = {
        "bracket_tp": None,
        "dist_tp_pct": None,
        "soft_stop": None,
        "dist_stop_pct": None,
        "bars_held": None,
        "max_bars": max_bars,
        "bar_minutes": mult,
    }
    if cost <= 0 or price <= 0:
        return out
    if getattr(IC, "USE_ENTRY_BRACKET_TAKE_PROFIT", False):
        bp = float(getattr(IC, "ENTRY_BRACKET_TAKE_PROFIT_PCT", 0.005) or 0)
        tp = cost * (1 + bp)
        out["bracket_tp"] = tp
        out["dist_tp_pct"] = (tp - price) / price * 100
    sl_pct = float(getattr(IC, "FULL_STOP_LOSS_PCT", -0.003) or -0.003)
    s_px = cost * (1 + sl_pct)
    out["soft_stop"] = s_px
    out["dist_stop_pct"] = (price - s_px) / price * 100
    if entry_time_iso:
        try:
            raw = entry_time_iso.replace("Z", "+00:00")
            ent = datetime.fromisoformat(raw)
            if ent.tzinfo is None:
                ent = ET.localize(ent)
            else:
                ent = ent.astimezone(ET)
            mins = (datetime.now(ET) - ent).total_seconds() / 60.0
            out["bars_held"] = max(0, int(mins // mult))
        except Exception:
            out["bars_held"] = None
    return out


import re
_MOBILE_RE = re.compile(r"Mobile|Android|iPhone|iPad|iPod|webOS|BlackBerry|Opera Mini|IEMobile", re.I)


def _is_mobile(request: Request) -> bool:
    """Detect mobile browser via User-Agent header."""
    ua = request.headers.get("user-agent", "")
    return bool(_MOBILE_RE.search(ua))

# 每日励志语录（基于日期哈希轮转）
_QUOTES = [
    "纪律是交易者最大的资本，远胜于金钱",
    "止损不是认输，而是保留再战的实力",
    "市场永远在，不要急于一时",
    "风险管理第一，盈利自然水到渠成",
    "不要与趋势为敌，顺势而为",
    "耐心等待属于你的机会，不要频繁交易",
    "控制好仓位，活着比赚钱更重要",
    "每一次亏损都是学费，关键是别交重复的学费",
    "计划你的交易，交易你的计划",
    "贪婪和恐惧是最大的敌人，纪律是最好的武器",
    "永远不要把所有鸡蛋放在一个篮子里",
    "复利是世界第八大奇迹，让时间成为你的朋友",
    "不懂的股票不要碰，能力圈外的钱不要赚",
    "牛市赚钱不算本事，熊市不亏才是真功夫",
    "做好研究，减少噪音，专注系统",
    "大钱不是靠频繁交易赚来的，而是靠耐心持有",
    "先求不败，再求胜",
    "盈亏同源，接受合理的回撤",
    "情绪化交易是亏损的根源",
    "百万目标，一步一步稳扎稳打",
    "每天进步一点点，复利效应终将显现",
    "空仓也是一种策略，等待也是一种能力",
    "投资是认知的变现，不断学习才能持续盈利",
    "不要因为一次暴利而改变策略，也不要因为一次亏损而放弃系统",
    "专注过程，结果自然来",
    "顶级交易者的秘密：严格执行，从不例外",
    "最好的交易是不交易，直到信号出现",
    "成功的投资需要独立思考，不随波逐流",
    "保护本金永远是第一优先级",
    "距离百万目标每天都在接近，坚持就是胜利",
    "慢慢来，比较快",
]


# ==================== CACHE ====================
# Two-tier cache: in-memory TTL + file persistence for expensive results
_cache: Dict[str, Tuple[float, Any]] = {}  # key -> (expire_ts, data)

_BACKTEST_TTL = 3600 * 24 * 7  # 7 days — pre-computed weekly by scheduler
_ROTATION_TTL = 3600 * 4     # 4 hours — scores update weekly, cache aggressively

import os as _os
_CACHE_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), ".cache")
_os.makedirs(_CACHE_DIR, exist_ok=True)

# Keys that should be persisted to disk (survive server restart)
_PERSISTENT_PREFIXES = ("adaptive_v1:", "bt_v2:", "bt_fund:", "opt:", "rotation_scores", "strategy_matrix:")


def _disk_cache_path(key: str) -> str:
    """Get file path for a disk-cached key."""
    safe_key = key.replace(":", "_").replace("/", "_").replace(" ", "_")
    return _os.path.join(_CACHE_DIR, f"{safe_key}.json")


_cache_get_counter = 0

def _cache_get(key: str) -> Any:
    """Return cached value: three-tier lookup — memory → disk → Supabase cache_store."""
    global _cache_get_counter
    _cache_get_counter += 1
    # Periodic purge of expired entries every 100 lookups
    if _cache_get_counter % 100 == 0:
        _now = time.time()
        _expired = [k for k, (exp, _) in _cache.items() if exp < _now]
        for k in _expired:
            del _cache[k]

    # L1: Memory cache
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    if entry:
        del _cache[key]

    # L2: Disk cache fallback for persistent keys
    if any(key.startswith(p) for p in _PERSISTENT_PREFIXES):
        path = _disk_cache_path(key)
        if _os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Restore to memory cache
                _cache[key] = (time.time() + _BACKTEST_TTL, data)
                logger.info(f"Disk cache hit: {key}")
                return data
            except Exception as e:
                logger.warning(f"Disk cache read error for {key}: {e}")

    # L3: Supabase cache_store (survives Render deploys)
    if any(key.startswith(p) for p in _PERSISTENT_PREFIXES):
        try:
            from app.database import get_db
            from datetime import datetime, timezone
            db = get_db()
            result = db.table("cache_store").select("value, updated_at").eq("key", key).execute()
            if result.data:
                row = result.data[0]
                updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
                if age_hours < 24 * 7:  # 7-day TTL for DB cache (refreshed weekly)
                    data = row["value"]
                    _cache[key] = (time.time() + _ROTATION_TTL, data)
                    logger.info(f"DB cache hit: {key} (age={age_hours:.1f}h)")
                    return data
                else:
                    logger.info(f"DB cache expired: {key} (age={age_hours:.1f}h)")
        except Exception as e:
            logger.warning(f"DB cache read error for {key}: {e}")
    return None


def _cache_exists(key: str) -> bool:
    """Lightweight existence check: memory → disk → Supabase (SELECT key only, no value)."""
    # L1: Memory cache
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return True
    if entry:
        del _cache[key]

    # L2: Disk cache
    if any(key.startswith(p) for p in _PERSISTENT_PREFIXES):
        path = _disk_cache_path(key)
        if _os.path.exists(path):
            return True

    # L3: Supabase — only check key + updated_at, skip the heavy JSONB value
    if any(key.startswith(p) for p in _PERSISTENT_PREFIXES):
        try:
            from app.database import get_db
            from datetime import datetime, timezone
            db = get_db()
            result = db.table("cache_store").select("updated_at").eq("key", key).execute()
            if result.data:
                row = result.data[0]
                updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
                if age_hours < 24 * 7:
                    return True
        except Exception as e:
            logger.warning(f"DB cache exists check error for {key}: {e}")
    return False


def _cache_get_batch(keys: list) -> Dict[str, Any]:
    """Batch fetch multiple cache keys. Memory → disk → single Supabase query."""
    results = {}
    missing_keys = []

    for key in keys:
        # L1: Memory
        entry = _cache.get(key)
        if entry and entry[0] > time.time():
            results[key] = entry[1]
            continue
        if entry:
            del _cache[key]

        # L2: Disk
        path = _disk_cache_path(key)
        if _os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _cache[key] = (time.time() + _BACKTEST_TTL, data)
                results[key] = data
                continue
            except Exception:
                pass

        missing_keys.append(key)

    # L3: Single Supabase query for all missing keys
    if missing_keys:
        try:
            from app.database import get_db
            from datetime import datetime, timezone
            db = get_db()
            result = db.table("cache_store").select("key, value, updated_at").in_("key", missing_keys).execute()
            if result.data:
                now = datetime.now(timezone.utc)
                for row in result.data:
                    updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
                    age_hours = (now - updated_at).total_seconds() / 3600
                    if age_hours < 24 * 7:
                        data = row["value"]
                        _cache[row["key"]] = (time.time() + _ROTATION_TTL, data)
                        results[row["key"]] = data
            logger.info(f"DB batch cache: {len(missing_keys)} queried, {len([k for k in missing_keys if k in results])} hit")
        except Exception as e:
            logger.warning(f"DB batch cache error: {e}")

    return results


def _make_json_safe(obj):
    """Recursively convert numpy/pandas types to JSON-serializable Python types."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif hasattr(obj, 'isoformat'):  # datetime/Timestamp
        return obj.isoformat()
    return obj


def _cache_set(key: str, value: Any, ttl: int) -> None:
    """Store value in cache with TTL. Persist to disk + Supabase for important keys."""
    _cache[key] = (time.time() + ttl, value)

    # Also persist to disk for expensive computations
    if any(key.startswith(p) for p in _PERSISTENT_PREFIXES):
        try:
            safe_value = _make_json_safe(value)
            path = _disk_cache_path(key)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(safe_value, f, ensure_ascii=False)
            size_kb = _os.path.getsize(path) / 1024
            logger.info(f"Disk cache saved: {key} ({size_kb:.0f}KB)")
        except Exception as e:
            logger.warning(f"Disk cache write error for {key}: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        # L3: Persist to Supabase cache_store (survives Render deploys)
        try:
            from app.database import get_db
            db = get_db()
            db.table("cache_store").upsert({
                "key": key,
                "value": safe_value,
            }).execute()
            logger.info(f"DB cache saved: {key}")
        except Exception as e:
            logger.warning(f"DB cache write error for {key}: {e}")


# ==================== BACKGROUND TASKS ====================
def _get_daily_quote() -> str:
    """基于日期确定性选取每日语录"""
    day_hash = int(hashlib.md5(date.today().isoformat().encode()).hexdigest(), 16)
    return _QUOTES[day_hash % len(_QUOTES)]


async def _get_total_profit() -> float:
    """从持仓记录计算总已实现盈亏"""
    try:
        from app.services.rotation_service import get_current_positions
        positions = await get_current_positions() or []
        total = 0.0
        for p in positions:
            pnl = 0.0
            if isinstance(p, dict):
                pnl = float(p.get("realized_pnl", 0) or 0) + float(p.get("unrealized_pnl", 0) or 0)
            elif hasattr(p, "realized_pnl"):
                pnl = float(getattr(p, "realized_pnl", 0) or 0) + float(getattr(p, "unrealized_pnl", 0) or 0)
            total += pnl
        return total
    except Exception as e:
        logger.error(f"Profit calc error: {e}")
        return 0.0


# ==================== FULL PAGE ROUTES ====================

@router.get("/rotation", response_class=HTMLResponse)
async def rotation_page(request: Request):
    """轮动策略页面 — 先渲染空壳(秒开)，数据通过HTMX异步加载"""
    return _tpl("rotation.html", {
        "request": request,
        "regime": "loading",
        "scores": [],
        "top3": [],
        "active_positions": [],
        "pending_positions": [],
        "sectors": [],
        "history": [],
        "has_scores": False,
    })


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request):
    """交易监控大屏：宝典周轮动摘要 + 铃铛日内（复用 HTMX 数据端点）"""
    quote = _get_daily_quote()
    pt = float(settings.intraday_daily_profit_target_usd)
    from app.config.rotation_watchlist import RotationConfig as _RC
    _q = (request.query_params.get("kiosk") or "").lower()
    kiosk_mode = _q in ("1", "true", "yes", "on")
    return _tpl("monitor.html", {
        "request": request,
        "quote": quote,
        "intraday_profit_target_label": f"${pt:,.0f}",
        "rotation_top_n": _RC.TOP_N,
        "kiosk_mode": kiosk_mode,
    })


@router.get("/htmx/rotation-data", response_class=HTMLResponse)
async def htmx_rotation_data(request: Request):
    """HTMX endpoint: 异步加载全部rotation数据，避免阻塞页面首屏"""
    import concurrent.futures
    loop = asyncio.get_event_loop()

    def _sync_load_all():
        """在线程池中执行所有同步Supabase调用，不阻塞event loop"""
        from app.database import get_db

        # 1. Read pre-computed scores from DB (unified: cache_store → rotation_snapshots)
        from app.services.rotation_service import read_cached_scores
        scores_result = read_cached_scores(limit=50)
        scores = scores_result.get("scores", [])
        regime = scores_result.get("regime", "unknown")
        has_scores = len(scores) > 0
        logger.info(f"rotation-data: {len(scores)} scores loaded, regime={regime}")

        # 2. DB queries (sync but in thread pool)
        from app.database import get_db
        db = get_db()

        # Positions
        try:
            pos_r = db.table("rotation_positions").select("*").neq("status", "closed").order("created_at", desc=True).execute()
            all_positions = pos_r.data if pos_r.data else []
        except Exception:
            all_positions = []

        # History
        try:
            hist_r = db.table("rotation_snapshots").select(
                "snapshot_date, regime, selected_tickers, previous_tickers, changes, created_at, trigger_source"
            ).order("snapshot_date", desc=True).order("created_at", desc=True).limit(26).execute()
            history = hist_r.data if hist_r.data else []
        except Exception:
            history = []

        # Regime fallback
        if not regime or regime == "unknown":
            try:
                reg_r = db.table("rotation_snapshots").select("regime").order("created_at", desc=True).limit(1).execute()
                if reg_r.data:
                    regime = reg_r.data[0].get("regime", "unknown")
            except Exception:
                pass

        return scores, regime, has_scores, all_positions, history

    # Run all sync DB calls in thread pool (non-blocking)
    scores, regime, has_scores, all_positions, history = await loop.run_in_executor(
        None, _sync_load_all
    )

    active = [p for p in all_positions if p.get("status") == "active"]
    pending = [p for p in all_positions if p.get("status") == "pending_entry"]
    top3 = scores[:3] if scores else []

    # Sector aggregation (pure computation from scores)
    sector_map: dict = {}
    for s in scores:
        sec = s.get("sector", "other") or "other"
        if sec not in sector_map:
            sector_map[sec] = {"count": 0, "total_score": 0, "total_ret_1w": 0}
        sector_map[sec]["count"] += 1
        sector_map[sec]["total_score"] += s.get("score", 0)
        sector_map[sec]["total_ret_1w"] += s.get("return_1w", 0)
    sectors = []
    for sec, data in sector_map.items():
        n = data["count"]
        sectors.append({
            "name": sec,
            "count": n,
            "avg_score": round(data["total_score"] / n, 2) if n > 0 else 0,
            "avg_ret_1w": round(data["total_ret_1w"] / n * 100, 1) if n > 0 else 0,
        })
    sectors.sort(key=lambda x: x["avg_score"], reverse=True)

    # Fallback: if sectors incomplete (cache miss or partial data e.g. bear regime),
    # read from sector_snapshots table which has full historical sector data
    if len(sectors) < 5:
        logger.warning(f"rotation-data: only {len(sectors)} sectors from scores, falling back to sector_snapshots table")
        try:
            def _fetch_sector_snapshots():
                from app.database import get_db
                db_sec = get_db()
                # Fetch recent snapshots (up to 200 rows covering ~10 dates * 20 sectors)
                # and find the most recent date with comprehensive data (>= 5 sectors)
                r = db_sec.table("sector_snapshots").select(
                    "snapshot_date, sector, avg_score, avg_ret_1w, stock_count"
                ).order("snapshot_date", desc=True).limit(200).execute()
                return r.data if r.data else []

            # 必须放入线程池：同步 Supabase HTTP 调用若在事件循环直接执行会堵塞所有请求
            snap_rows = await asyncio.to_thread(_fetch_sector_snapshots)
            if snap_rows:
                by_date: dict[str, list] = {}
                for row in snap_rows:
                    d = row["snapshot_date"]
                    by_date.setdefault(d, []).append(row)
                best_rows = None
                for d in sorted(by_date.keys(), reverse=True):
                    if len(by_date[d]) >= 5:
                        best_rows = by_date[d]
                        logger.info(f"rotation-data: found full sector data on {d} ({len(by_date[d])} sectors)")
                        break
                if best_rows is None:
                    best_rows = by_date[sorted(by_date.keys(), reverse=True)[0]]

                if best_rows:
                    db_sectors = {
                        row.get("sector", "unknown"): {
                            "name": row.get("sector", "unknown"),
                            "count": row.get("stock_count", 0),
                            "avg_score": round(row.get("avg_score", 0), 2),
                            "avg_ret_1w": round(row.get("avg_ret_1w", 0), 1),
                        }
                        for row in best_rows
                    }
                    for sec in sectors:
                        db_sectors[sec["name"]] = sec
                    sectors = sorted(db_sectors.values(), key=lambda x: x["avg_score"], reverse=True)
                    logger.info(f"rotation-data: merged to {len(sectors)} sectors total")
        except Exception as e:
            logger.warning(f"rotation-data: sector_snapshots fallback failed: {e}")

    return _tpl("partials/_rotation_full.html", {
        "request": request,
        "regime": regime,
        "scores": scores,
        "top3": top3,
        "active_positions": active,
        "pending_positions": pending,
        "sectors": sectors,
        "history": history,
        "has_scores": has_scores,
    })


@router.get("/htmx/monitor-rotation-compact", response_class=HTMLResponse)
async def htmx_monitor_rotation_compact(request: Request):
    """大屏专用：宝典 Regime + Top N 候选 + 持仓状态（无全量图）"""
    def _sync_load():
        from app.services.rotation_service import read_cached_scores
        from app.database import get_db

        scores_result = read_cached_scores(limit=50)
        scores = scores_result.get("scores", [])
        regime = scores_result.get("regime", "unknown")
        db = get_db()
        try:
            pos_r = (
                db.table("rotation_positions")
                .select("*")
                .neq("status", "closed")
                .order("created_at", desc=True)
                .execute()
            )
            all_positions = pos_r.data if pos_r.data else []
        except Exception:
            all_positions = []
        if not regime or regime == "unknown":
            try:
                reg_r = db.table("rotation_snapshots").select("regime").order("created_at", desc=True).limit(1).execute()
                if reg_r.data:
                    regime = reg_r.data[0].get("regime", "unknown")
            except Exception:
                pass
        return scores, regime, all_positions

    try:
        scores, regime, all_positions = await asyncio.to_thread(_sync_load)
    except Exception as e:
        logger.error(f"monitor-rotation-compact: {e}")
        return HTMLResponse('<div class="text-red-400 text-sm p-4">宝典数据加载失败</div>')

    from app.config.rotation_watchlist import INVERSE_ETF_INDEX_MAP, RotationConfig as RC

    topn = scores[: RC.TOP_N] if scores else []
    hedge_keys = {k.upper() for k in INVERSE_ETF_INDEX_MAP.keys()}

    def _is_hedge_row(p: dict) -> bool:
        if (p.get("position_type") or "").lower() == "hedge":
            return True
        tk = (p.get("ticker") or "").upper().strip()
        return tk in hedge_keys

    active = [p for p in all_positions if p.get("status") == "active"]
    pending = [p for p in all_positions if p.get("status") == "pending_entry"]
    pending_exit = [p for p in all_positions if p.get("status") == "pending_exit"]
    active_hedge = [p for p in active if _is_hedge_row(p)]
    active_alpha = [p for p in active if not _is_hedge_row(p)]
    hedge_target_pct = float(RC.HEDGE_ALLOC_BY_REGIME.get(regime, 0.0) or 0.0) * 100.0

    return _tpl("partials/_monitor_rotation_compact.html", {
        "request": request,
        "regime": regime,
        "topn": topn,
        "scores_count": len(scores),
        "active_positions": active_alpha,
        "pending_positions": pending,
        "pending_exit": pending_exit,
        "active_hedge_positions": active_hedge,
        "has_scores": len(scores) > 0,
        "top_n": RC.TOP_N,
        "next_rebalance": _bao_dian_next_rebalance_info(),
        "hedge_target_pct": hedge_target_pct,
        "hedge_overlay_enabled": bool(getattr(RC, "HEDGE_OVERLAY_ENABLED", False)),
    })


@router.get("/sectors", response_class=HTMLResponse)
async def sectors_page(request: Request):
    """板块热力图页面"""
    return _tpl("sectors.html", {"request": request})


@router.get("/htmx/sector-heatmap", response_class=HTMLResponse)
async def htmx_sector_heatmap(request: Request):
    """HTMX: 返回板块热力图网格"""
    loop = asyncio.get_event_loop()

    def _fetch_sectors():
        from app.database import get_db
        from app.config.rotation_watchlist import normalize_sector

        sectors = []
        cached = _cache_get("rotation_scores")
        if cached:
            raw = cached.get("scores", []) if isinstance(cached, dict) else cached
            sector_map: dict = {}
            for s in raw:
                if hasattr(s, "model_dump"):
                    s = s.model_dump()
                sec = normalize_sector(s.get("sector") or "")
                sector_map.setdefault(sec, {"count": 0, "total_score": 0.0, "total_ret_1w": 0.0})
                sector_map[sec]["count"] += 1
                sector_map[sec]["total_score"] += s.get("score", 0)
                sector_map[sec]["total_ret_1w"] += s.get("return_1w", 0)
            for sec, d in sector_map.items():
                n = d["count"]
                sectors.append({
                    "name": sec,
                    "count": n,
                    "avg_score": round(d["total_score"] / n, 2),
                    "avg_ret_1w": round(d["total_ret_1w"] / n * 100, 1),
                })
            sectors.sort(key=lambda x: x["avg_score"], reverse=True)

        if len(sectors) < 5:
            try:
                db = get_db()
                snaps = db.table("sector_snapshots").select(
                    "snapshot_date, sector, avg_score, avg_ret_1w, stock_count"
                ).order("snapshot_date", desc=True).limit(200).execute()
                if snaps.data:
                    by_date: dict = {}
                    for row in snaps.data:
                        by_date.setdefault(row["snapshot_date"], []).append(row)
                    best = None
                    for d in sorted(by_date.keys(), reverse=True):
                        if len(by_date[d]) >= 5:
                            best = by_date[d]
                            break
                    if best is None and by_date:
                        best = by_date[sorted(by_date.keys(), reverse=True)[0]]
                    if best:
                        db_map = {
                            row["sector"]: {
                                "name": row["sector"],
                                "count": row.get("stock_count", 0),
                                "avg_score": round(row.get("avg_score", 0), 2),
                                "avg_ret_1w": round(row.get("avg_ret_1w", 0), 1),
                            }
                            for row in best
                        }
                        for s in sectors:
                            db_map[s["name"]] = s
                        sectors = sorted(db_map.values(), key=lambda x: x["avg_score"], reverse=True)
            except Exception as e:
                logger.warning(f"sector-heatmap fallback: {e}")

        return sectors

    try:
        sectors = await loop.run_in_executor(None, _fetch_sectors)
        return _tpl("partials/_sector_heatmap.html", {"request": request, "sectors": sectors})
    except Exception as e:
        logger.error(f"sector-heatmap error: {e}")
        return _tpl("partials/_sector_heatmap.html", {"request": request, "sectors": []})


@router.get("/htmx/strategy-xray", response_class=HTMLResponse)
async def htmx_strategy_xray(request: Request):
    """HTMX: 策略X光诊断 — Alpha/Beta + Regime Sharpe 最新结果"""
    def _fetch():
        from app.database import get_db
        db = get_db()

        # 最新一次 alpha_beta full 行
        ab = db.table("alpha_beta_results").select("*") \
            .eq("scope", "full") \
            .order("created_at", desc=True).limit(1).execute()
        ab_row = ab.data[0] if ab.data else None

        # 最新一次 regime_sharpe v4 三个 regime
        rs = db.table("regime_sharpe_results").select("*") \
            .eq("strategy", "v4") \
            .order("created_at", desc=True).limit(10).execute()
        rs_rows = rs.data or []

        # 取同一个 run_id 的最新三行
        rs_map = {}
        if rs_rows:
            latest_run = rs_rows[0]["run_id"]
            for r in rs_rows:
                if r["run_id"] == latest_run:
                    rs_map[r["regime"]] = r

        return ab_row, rs_map

    try:
        ab_row, rs_map = await asyncio.to_thread(_fetch)
        return _tpl("partials/_strategy_xray.html", {
            "request": request,
            "ab": ab_row,
            "rs": rs_map,
        })
    except Exception as e:
        logger.error(f"strategy-xray error: {e}")
        return HTMLResponse('<p class="text-gray-500 text-xs p-4 text-center">暂无数据（等待 GHA 首次运行完成）</p>')


@router.get("/htmx/sector-selection-log", response_class=HTMLResponse)
async def htmx_sector_selection_log(request: Request):
    """HTMX: 行业集中度历史记录（来自 selection_sector_log 表）"""
    def _fetch():
        from app.database import get_db
        db = get_db()
        rows = db.table("selection_sector_log").select(
            "snapshot_date, regime, selected_tickers, sector_breakdown, dominant_sector, dominant_pct"
        ).order("snapshot_date", desc=True).limit(20).execute()
        return rows.data or []

    try:
        logs = await asyncio.to_thread(_fetch)
        return _tpl("partials/_sector_selection_log.html", {"request": request, "logs": logs})
    except Exception as e:
        logger.error(f"sector-selection-log error: {e}")
        return HTMLResponse('<p class="text-gray-500 text-xs p-4 text-center">暂无数据</p>')


@router.get("/rotation/sector/{sector_name}", response_class=HTMLResponse)
async def rotation_sector_detail(request: Request, sector_name: str):
    """板块详情页 — 趋势图 + 个股列表，优先 sector_snapshots，回退到 cache_store"""
    sector_key = sector_name.lower()
    try:
        def _fetch_sector_data():
            from app.database import get_db
            db = get_db()

            trend_result = db.table("sector_snapshots").select(
                "snapshot_date, avg_score, avg_ret_1w, stock_count, regime"
            ).eq("sector", sector_key).order("snapshot_date", desc=True).limit(30).execute()
            trend_data = list(reversed(trend_result.data)) if trend_result.data else []

            latest_result = db.table("sector_snapshots").select(
                "snapshot_date, avg_score, avg_ret_1w, stock_count, top_tickers, regime"
            ).eq("sector", sector_key).order("snapshot_date", desc=True).limit(1).execute()
            latest = latest_result.data[0] if latest_result.data else None
            stocks = latest.get("top_tickers", []) if latest else []

            if not stocks:
                try:
                    cache_result = db.table("cache_store").select("value").eq(
                        "key", "rotation_scores"
                    ).limit(1).execute()
                    if cache_result.data:
                        cached = cache_result.data[0].get("value", {})
                        all_scores = cached.get("scores", [])
                        regime = cached.get("regime", "unknown")
                        from app.config.rotation_watchlist import normalize_sector as _ns
                        sector_scores = [
                            s for s in all_scores
                            if _ns(s.get("sector") or "") == sector_key
                        ]
                        if sector_scores:
                            sector_scores.sort(key=lambda x: x.get("score", 0), reverse=True)
                            stocks = [{
                                "ticker": s.get("ticker", ""),
                                "name": s.get("name", ""),
                                "score": round(s.get("score", 0), 2),
                                "return_1w": round(s.get("return_1w", 0) * 100, 2),
                                "current_price": s.get("current_price", 0),
                            } for s in sector_scores]
                            n = len(sector_scores)
                            latest = {
                                "snapshot_date": "cache",
                                "avg_score": round(sum(s.get("score", 0) for s in sector_scores) / n, 4),
                                "avg_ret_1w": round(sum(s.get("return_1w", 0) for s in sector_scores) / n, 4),
                                "stock_count": n,
                                "top_tickers": stocks,
                                "regime": regime,
                            }
                except Exception as fallback_err:
                    logger.warning(f"Sector detail cache fallback failed: {fallback_err}")

            return trend_data, stocks, latest

        trend_data, stocks, latest = await asyncio.to_thread(_fetch_sector_data)

        return _tpl("sector_detail.html", {
            "request": request,
            "sector_name": sector_name,
            "trend_data": trend_data,
            "stocks": stocks,
            "latest": latest,
        })
    except Exception as e:
        logger.error(f"Sector detail error for {sector_name}: {e}", exc_info=True)
        return _tpl("sector_detail.html", {
            "request": request,
            "sector_name": sector_name,
            "trend_data": [],
            "stocks": [],
            "latest": None,
        })


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """仪表盘 — 页面先渲染，数据通过 HTMX 异步加载（避免 yfinance 阻塞）"""
    DASHBOARD_FETCH_TIMEOUT = 8.0

    async def _safe_wait(coro, fallback, label: str):
        """Fail fast on slow dependencies so /dashboard never hangs."""
        try:
            return await asyncio.wait_for(coro, timeout=DASHBOARD_FETCH_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"Dashboard {label} timeout after {DASHBOARD_FETCH_TIMEOUT:.0f}s; using fallback")
            return fallback
        except Exception as e:
            logger.error(f"Dashboard {label} failed: {e}")
            return fallback

    # --- Parallel fetch: positions, signals, risk, profit ---
    async def _fetch_positions():
        try:
            from app.services.order_service import get_active_positions
            return await get_active_positions()
        except Exception as e:
            logger.error(f"Dashboard positions error: {e}")
            return []

    async def _fetch_signals():
        try:
            from app.services.db_service import SignalService
            signals = await SignalService.get_observe_signals()
            result = []
            for sig in (signals or []):
                if hasattr(sig, "model_dump"):
                    result.append(sig.model_dump())
                elif hasattr(sig, "dict"):
                    result.append(sig.dict())
                elif isinstance(sig, dict):
                    result.append(sig)
            return result
        except Exception as e:
            logger.error(f"Dashboard signals error: {e}")
            return []

    async def _fetch_risk():
        try:
            from app.services.risk_service import RiskEngine
            return await RiskEngine().get_current_risk_summary()
        except Exception as e:
            logger.error(f"Dashboard risk error: {e}")
            return {"status": "normal", "max_drawdown_pct": 0}

    positions, signal_dicts, risk, total_profit = await asyncio.gather(
        _safe_wait(_fetch_positions(), [], "positions"),
        _safe_wait(_fetch_signals(), [], "signals"),
        _safe_wait(_fetch_risk(), {"status": "normal", "max_drawdown_pct": 0}, "risk"),
        _safe_wait(_get_total_profit(), 0.0, "profit"),
    )

    # 每日语录 + 盈利目标
    quote = _get_daily_quote()
    profit_pct = (total_profit / 1_000_000) * 100

    # Pre-load cached rotation scores (skip API call, just check cache)
    cached_scores = _cache_get("rotation_scores")
    pre_scores = []
    if cached_scores is not None:
        raw = cached_scores.get("scores", []) if isinstance(cached_scores, dict) else cached_scores
        for s in raw:
            if hasattr(s, "model_dump"):
                pre_scores.append(s.model_dump())
            elif hasattr(s, "dict"):
                pre_scores.append(s.dict())
            elif isinstance(s, dict):
                pre_scores.append(s)
        pre_scores.sort(key=lambda x: x.get("score", 0), reverse=True)

    tpl_name = "dashboard_mobile.html" if _is_mobile(request) else "dashboard.html"
    return _tpl(tpl_name, {
        "request": request,
        "scores": pre_scores,
        "positions": positions,
        "signals": signal_dicts,
        "risk": risk,
        "regime": None,
        "quote": quote,
        "total_profit": total_profit,
        "profit_pct": profit_pct,
    })


@router.get("/lab", response_class=HTMLResponse)
async def lab_page(request: Request):
    """🌊 破浪实验室 — 所有进行中功能的测试预览页，不影响生产环境"""
    from app.services.portfolio_manager import get_cached_daily_signals, get_strategy_allocations

    regime = "unknown"
    cached_scores = _cache_get("rotation_scores")
    if cached_scores and isinstance(cached_scores, dict):
        regime = cached_scores.get("regime", "unknown")

    daily = get_cached_daily_signals()
    alloc = get_strategy_allocations(regime)

    return _tpl("lab.html", {
        "request":       request,
        "regime":        regime,
        "alloc":         alloc,
        "mr_candidates": (daily or {}).get("mr_candidates", []),
        "ed_candidates": (daily or {}).get("ed_candidates", []),
        "scan_date":     (daily or {}).get("date", None),
        "mr_active":     alloc.get("mean_reversion", 0) > 0,
        "ed_active":     alloc.get("event_driven", 0) > 0,
    })


@router.get("/api/lab/intraday-runtime")
async def api_lab_intraday_runtime_get(_auth: dict = Depends(require_admin)):
    """铃铛策略层总敞口上限（倍）。后续可由宏观四屏/风控面板联动写入 intraday_runtime.json。"""
    from app.config.intraday_runtime import (
        get_max_total_exposure,
        load_intraday_runtime,
    )

    return JSONResponse(
        {
            "max_total_exposure": get_max_total_exposure(),
            "raw": load_intraday_runtime(),
            "clamp_min": 1.0,
            "clamp_max": 2.0,
        }
    )


@router.post("/api/lab/intraday-runtime")
async def api_lab_intraday_runtime_post(
    request: Request,
    _auth: dict = Depends(require_admin),
):
    """更新铃铛 max_total_exposure（1.0–2.0），需管理员登录或 API Key。"""
    from app.config.intraday_runtime import get_max_total_exposure, save_intraday_runtime

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if "max_total_exposure" not in body:
        return JSONResponse({"ok": False, "error": "missing max_total_exposure"}, status_code=400)
    try:
        v = float(body["max_total_exposure"])
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "max_total_exposure must be numeric"}, status_code=400)
    saved = save_intraday_runtime({"max_total_exposure": v})
    return JSONResponse(
        {
            "ok": True,
            "max_total_effective": get_max_total_exposure(),
            "saved": saved,
        }
    )


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    """知识投喂 — 投喂表单 + 搜索 + 最近条目"""
    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()

        recent = await ks.get_recent(limit=20)
        stats = await ks.get_stats()
        stats_dict = stats.dict() if hasattr(stats, "dict") else stats.model_dump()

        return _tpl("knowledge.html", {
            "request": request,
            "entries": recent or [],
            "stats": stats_dict,
        })

    except Exception as e:
        logger.error(f"Knowledge page error: {e}")
        return _tpl("knowledge.html", {
            "request": request,
            "entries": [],
            "stats": {"total_entries": 0, "by_source_type": {}, "by_category": {}},
        })


# ==================== HTMX PARTIAL ROUTES ====================


@router.get("/htmx/regime-map", response_class=HTMLResponse)
async def htmx_regime_map(request: Request):
    """HTMX endpoint: Regime Transition Map — 信号诊断+状态机可视化"""
    try:
        from app.services.rotation_service import detect_regime_details
        details = await detect_regime_details()
    except Exception as e:
        logger.error(f"regime-map error: {e}")
        details = {"regime": "unknown", "score": 0, "signals": [], "transitions": {}, "error": str(e)}

    return _tpl("partials/_regime_map.html", {
        "request": request,
        **details,
    })


@router.get("/htmx/regime-history", response_class=HTMLResponse)
async def htmx_regime_history(request: Request):
    """HTMX endpoint: Regime History Timeline from regime_history table"""
    try:
        def _fetch():
            from app.database import get_db
            db = get_db()
            rows = (
                db.table("regime_history")
                .select("date, regime, score, spy_price, signals, changed_from")
                .order("date", desc=True)
                .limit(60)
                .execute()
            )
            return rows.data if rows.data else []
        history = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.error(f"regime-history error: {e}")
        history = []

    return _tpl("partials/_regime_history.html", {
        "request": request,
        "regime_history": history,
    })


@router.get("/htmx/rotation-full", response_class=HTMLResponse)
async def htmx_rotation_full(request: Request):
    """HTMX lazy load: 读取预计算评分 → 重定向到整页刷新"""
    try:
        from app.services.rotation_service import read_cached_scores

        # Read pre-computed scores, warm up in-memory cache
        scores_result = read_cached_scores()
        _cache_set("rotation_scores", scores_result, _ROTATION_TTL)

        return HTMLResponse(
            content="",
            headers={"HX-Redirect": "/rotation"},
        )
    except Exception as e:
        logger.error(f"Rotation full load error: {e}")
        return HTMLResponse(
            '<div class="text-center py-8">'
            '<p class="text-sq-red mb-2">评分数据加载失败</p>'
            f'<p class="text-gray-500 text-xs">{str(e)[:100]}</p>'
            '<button hx-get="/htmx/rotation-full" hx-target="#rotation-content-wrapper" '
            'class="mt-4 px-4 py-2 bg-sq-border rounded text-sm hover:bg-gray-600">重试</button>'
            '</div>'
        )


@router.get("/htmx/rotation-table", response_class=HTMLResponse)
async def htmx_rotation_table(
    request: Request,
    sort: str = Query("score"),
    order: str = Query("desc"),
):
    """可排序轮动评分表（HTMX局部），读取调度器预计算的评分，TOP 50"""
    try:
        from app.services.rotation_service import read_cached_scores

        # Read pre-computed scores from DB (no live computation)
        scores_result = read_cached_scores(limit=50)
        score_dicts = scores_result.get("scores", [])

        # Sort
        reverse = (order == "desc")
        score_dicts.sort(
            key=lambda x: x.get(sort, 0) if isinstance(x.get(sort, 0), (int, float)) else str(x.get(sort, "")),
            reverse=reverse,
        )

        return _tpl("partials/_rotation_table.html", {
            "request": request,
            "scores": score_dicts,
        })

    except Exception as e:
        logger.error(f"Rotation table error: {e}")
        return HTMLResponse('<tr><td colspan="10" class="px-3 py-4 text-center text-sq-red">加载失败</td></tr>')


@router.get("/htmx/market-overview", response_class=HTMLResponse)
async def htmx_market_overview(request: Request):
    """大盘行情卡片 SPY/QQQ/TLT/GLD — 优先读后台 scan 缓存"""
    try:
        benchmarks = ["SPY", "QQQ", "TLT", "GLD"]
        scan_map = {}

        # 从 rotation_scores 缓存获取价格（零 API 调用）
        try:
            cached = _cache_get("rotation_scores")
            if cached is not None:
                raw = cached.get("scores", []) if isinstance(cached, dict) else cached
                for s in raw:
                    d = s.model_dump() if hasattr(s, "model_dump") else (s.dict() if hasattr(s, "dict") else s)
                    if d.get("ticker") in benchmarks:
                        scan_map[d["ticker"]] = d
        except Exception:
            pass

        # Fallback: 缺失的 benchmark 通过 API 获取
        missing = [t for t in benchmarks if t not in scan_map]
        quotes_raw = {}
        if missing:
            try:
                from app.services.alphavantage_client import get_av_client
                av = get_av_client()
                quotes_raw = await av.batch_get_quotes(missing)
            except Exception as _av_err:
                logger.warning(f"Market overview AV fallback failed: {_av_err}")

        cards = []
        for ticker in benchmarks:
            score = scan_map.get(ticker)
            quote = quotes_raw.get(ticker)
            if quote:
                cards.append({
                    "ticker": ticker,
                    "price": quote.get("latest_price", 0),
                    "change": quote.get("latest_price", 0) - quote.get("prev_close", 0),
                    "change_pct": quote.get("change_percent", 0),
                })
            elif score:
                price = float(score.get("current_price") or 0)
                change_pct = float(score.get("return_1w") or 0)
                cards.append({
                    "ticker": ticker,
                    "price": price,
                    "change": 0,
                    "change_pct": change_pct,
                })
            else:
                cards.append({"ticker": ticker, "price": 0, "change": 0, "change_pct": 0})

        html_parts = ['<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">']
        for c in cards:
            color = "text-sq-green" if c["change"] >= 0 else "text-sq-red"
            sign = "+" if c["change"] >= 0 else ""
            html_parts.append(f'''
        <div class="bg-sq-card rounded-xl border border-sq-border p-4">
            <div class="text-xs text-gray-500 mb-1">{c["ticker"]}</div>
            <div class="text-lg font-bold font-mono text-white">${c["price"]:.2f}</div>
            <div class="text-sm font-mono {color}">{sign}{c["change"]:.2f} ({sign}{c["change_pct"]:.2f}%)</div>
        </div>''')
        html_parts.append('</div>')
        return HTMLResponse("".join(html_parts))
    except Exception as e:
        logger.error(f"Market overview error: {e}", exc_info=True)
        placeholder = "".join(
            f'<div class="bg-sq-card rounded-xl border border-sq-border p-4">'
            f'<div class="text-xs text-gray-500 mb-1">{t}</div>'
            f'<div class="text-lg font-bold font-mono text-gray-600">--</div>'
            f'<div class="text-sm text-gray-600">暂不可用</div></div>'
            for t in ["SPY", "QQQ", "TLT", "GLD"]
        )
        return HTMLResponse(f'<div class="grid grid-cols-2 lg:grid-cols-4 gap-4">{placeholder}</div>')


@router.get("/htmx/market-board", response_class=HTMLResponse)
async def htmx_market_board(request: Request):
    """整体大盘：分组宏观/风格/商品行情（Massive 批量快照）。"""
    from app.config.market_board import CORE_WATCH_CHEATSHEET, SECTIONS, all_board_tickers

    tickers = all_board_tickers()
    quotes_raw: Dict[str, Any] = {}
    try:
        from app.services.alphavantage_client import get_av_client

        av = get_av_client()
        quotes_raw = await av.batch_get_quotes(tickers)
    except Exception as e:
        logger.warning(f"Market board quotes failed: {e}")

    sections_out = []
    for sec in SECTIONS:
        # 键名不能用 items：Jinja 里 dict.items 会与内置 .items() 冲突，导致模板渲染失败、HTMX 一直停在「加载」
        cards = []
        for row in sec.rows:
            t = row.ticker.upper()
            q = quotes_raw.get(t) or {}
            price = float(q.get("latest_price") or 0)
            pct = float(q.get("change_percent") or 0)
            sign = "+" if pct >= 0 else ""
            pct_str = f"{sign}{pct:.2f}%"
            pct_class = "text-sq-green" if pct >= 0 else "text-sq-red"
            cards.append({
                "ticker": t,
                "label": row.label,
                "note": row.note,
                "price": price if price > 0 else None,
                "pct": pct,
                "pct_str": pct_str,
                "pct_class": pct_class,
            })
        sections_out.append({
            "title": sec.title,
            "subtitle": sec.subtitle,
            "cards": cards,
        })

    footnote = (
        f"开盘前可优先对照：{CORE_WATCH_CHEATSHEET}。"
        " 数值为美股常规交易时段快照，约 60s 刷新。"
    )
    try:
        return _tpl("partials/_market_board.html", {
            "request": request,
            "sections": sections_out,
            "footnote": footnote,
        })
    except Exception as e:
        logger.error(f"Market board template error: {e}", exc_info=True)
        return HTMLResponse(
            '<div class="text-sq-red text-sm p-3">整体大盘渲染失败，请稍后重试或联系管理员。</div>',
            status_code=200,
        )


@router.get("/htmx/ticker-quote/{ticker}", response_class=HTMLResponse)
async def htmx_ticker_quote(request: Request, ticker: str):
    """Ticker 实时报价弹窗"""
    from app.services.alphavantage_client import get_av_client

    av = get_av_client()
    quote_data = {}
    score_data = {}
    error = None

    try:
        q = await av.get_quote(ticker)
        if q:
            quote_data = {
                "ticker": ticker,
                "latest_price": q.get("latest_price", 0),
                "prev_close": q.get("prev_close", 0),
                "open": q.get("open", 0),
                "high": q.get("high", 0),
                "low": q.get("low", 0),
                "volume": q.get("volume", 0),
                "change_percent": q.get("change_percent", 0),
            }
        else:
            error = f"无法获取 {ticker} 报价"
    except Exception as e:
        error = str(e)

    # Get score data from cache
    try:
        cached = _cache_get("rotation_scores")
        if cached is not None:
            raw = cached.get("scores", []) if isinstance(cached, dict) else cached
            for s in raw:
                d = s.model_dump() if hasattr(s, "model_dump") else (s.dict() if hasattr(s, "dict") else s)
                if d.get("ticker") == ticker:
                    score_data = d
                    break
    except Exception:
        pass

    # Convert to namespace for template
    class Obj:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)

    return _tpl("partials/_ticker_quote.html", {
        "request": request,
        "quote": Obj(quote_data) if quote_data else Obj({
            "ticker": ticker, "latest_price": 0, "prev_close": 0,
            "open": 0, "high": 0, "low": 0, "volume": 0, "change_percent": 0,
        }),
        "score_data": Obj(score_data) if score_data else None,
        "error": error,
    })


_tiger_price_cache: dict = {}   # ticker -> price
_tiger_cache_time: float = 0.0  # last update timestamp

def _tiger_positions_to_display(tiger_positions: list) -> list:
    """Convert Tiger API positions to display-compatible dicts when DB has no records."""
    result = []
    for tp in tiger_positions:
        qty = tp.get("quantity", 0)
        if qty <= 0:
            continue
        avg_cost = tp.get("average_cost", 0)
        latest = tp.get("latest_price", 0)
        pnl_pct = (latest - avg_cost) / avg_cost if avg_cost > 0 and latest > 0 else 0
        result.append({
            "id": None,
            "ticker": tp.get("ticker", ""),
            "status": "active",
            "quantity": qty,
            "entry_price": avg_cost,
            "current_price": latest,
            "unrealized_pnl_pct": pnl_pct,
            "stop_loss": None,
            "take_profit": None,
            "tiger_order_status": "filled",
        })
    return result


@router.get("/htmx/positions", response_class=HTMLResponse)
async def htmx_positions(request: Request):
    """持仓列表（HTMX局部）— active + pending_exit, Tiger (10s timeout + cache) > DB fallback"""
    global _tiger_price_cache, _tiger_cache_time
    try:
        import asyncio as _aio, time as _time
        from app.services.rotation_service import get_current_positions
        from app.services.order_service import get_tiger_trade_client

        # Support account parameter for account switching
        account = request.query_params.get("account", "primary")

        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") in ("active", "pending_exit")]

        # Always fetch Tiger positions for live prices (and fallback if DB is empty)
        tiger_prices = {}   # ticker -> {price, cost, qty}
        tiger_raw = []
        cache_age = _time.time() - _tiger_cache_time if _tiger_cache_time else float('inf')
        cache_valid = cache_age < 60  # Cache expires after 60 seconds

        try:
            tiger_client = get_tiger_trade_client(account)
            tiger_raw = await _aio.wait_for(tiger_client.get_positions(), timeout=10.0)
            for tp in tiger_raw:
                tk = tp.get("ticker", "")
                price = tp.get("latest_price", 0)
                if tk and price > 0:
                    tiger_prices[tk] = {
                        "price": price,
                        "cost": float(tp.get("average_cost", 0) or 0),
                        "qty": int(tp.get("quantity", 0) or 0),
                    }
            if tiger_prices:
                _tiger_price_cache = tiger_prices
                _tiger_cache_time = _time.time()
                logger.info(f"[POSITIONS] Tiger prices (live): {tiger_prices}")
        except _aio.TimeoutError:
            logger.warning(f"[POSITIONS] Tiger API timeout (10s), using cache (age: {cache_age:.1f}s)")
            tiger_prices = _tiger_price_cache if cache_valid else {}
        except Exception as e:
            logger.warning(f"[POSITIONS] Tiger unavailable: {e}, using cache (age: {cache_age:.1f}s)")
            tiger_prices = _tiger_price_cache if cache_valid else {}

        if active:
            # Apply Tiger live data to DB positions (price, cost, quantity)
            for p in active:
                tk = p.get("ticker")
                if tk and tk in tiger_prices:
                    td = tiger_prices[tk]
                    p["current_price"] = td["price"]
                    # Use Tiger's actual fill cost as entry_price
                    if td["cost"] > 0:
                        p["entry_price"] = td["cost"]
                    # Use Tiger's actual quantity
                    if td["qty"] > 0:
                        p["quantity"] = td["qty"]
                    entry = p.get("entry_price") or 0
                    if entry > 0:
                        p["unrealized_pnl_pct"] = (p["current_price"] - entry) / entry
                else:
                    entry = p.get("entry_price") or 0
                    if entry > 0:
                        p["current_price"] = entry
                        p["unrealized_pnl_pct"] = 0
        elif tiger_raw:
            # DB has no active positions — fall back to Tiger API positions
            active = _tiger_positions_to_display(tiger_raw)
            logger.info(f"[POSITIONS] DB empty, using Tiger positions: {len(active)} items")

        return _tpl("partials/_positions.html", {
            "request": request,
            "positions": active,
        })
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


@router.get("/htmx/positions-mobile", response_class=HTMLResponse)
async def htmx_positions_mobile(request: Request):
    """持仓列表 mobile 版 — 复用 htmx_positions 逻辑，渲染移动端模板"""
    global _tiger_price_cache, _tiger_cache_time
    try:
        import asyncio as _aio, time as _time
        from app.services.rotation_service import get_current_positions
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") in ("active", "pending_exit")]

        tiger_prices = {}   # ticker -> {price, cost, qty}
        tiger_raw = []
        cache_age = _time.time() - _tiger_cache_time if _tiger_cache_time else float('inf')
        cache_valid = cache_age < 60

        try:
            from app.services.order_service import get_tiger_trade_client
            tiger_client = get_tiger_trade_client()
            tiger_raw = await _aio.wait_for(tiger_client.get_positions(), timeout=10.0)
            for tp in tiger_raw:
                tk = tp.get("ticker", "")
                price = tp.get("latest_price", 0)
                if tk and price > 0:
                    tiger_prices[tk] = {
                        "price": price,
                        "cost": float(tp.get("average_cost", 0) or 0),
                        "qty": int(tp.get("quantity", 0) or 0),
                    }
            if tiger_prices:
                _tiger_price_cache = tiger_prices
                _tiger_cache_time = _time.time()
        except (_aio.TimeoutError, Exception):
            tiger_prices = _tiger_price_cache if cache_valid else {}

        if active:
            for p in active:
                tk = p.get("ticker")
                if tk and tk in tiger_prices:
                    td = tiger_prices[tk]
                    p["current_price"] = td["price"]
                    if td["cost"] > 0:
                        p["entry_price"] = td["cost"]
                    if td["qty"] > 0:
                        p["quantity"] = td["qty"]
                    entry = p.get("entry_price") or 0
                    if entry > 0:
                        p["unrealized_pnl_pct"] = (p["current_price"] - entry) / entry
                else:
                    entry = p.get("entry_price") or 0
                    if entry > 0:
                        p["current_price"] = entry
                        p["unrealized_pnl_pct"] = 0
        elif tiger_raw:
            active = _tiger_positions_to_display(tiger_raw)
            logger.info(f"[POSITIONS-MOBILE] DB empty, using Tiger positions: {len(active)} items")

        return _tpl("partials/_positions_mobile.html", {
            "request": request,
            "positions": active,
        })
    except Exception as e:
        logger.error(f"Positions mobile error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4 text-xs">加载失败</div>')


@router.get("/htmx/pending-entries", response_class=HTMLResponse)
async def htmx_pending_entries(request: Request):
    """待进场列表（HTMX局部）— pending_entry 状态，实时计算 MA5 / 成交量条件"""
    try:
        from app.services.rotation_service import (
            get_current_positions, RC, _fetch_history, _compute_ma,
        )
        import numpy as np

        all_positions = await get_current_positions() or []
        pending = [p for p in all_positions if p.get("status") == "pending_entry"]

        # Enrich pending positions with real-time entry conditions (concurrent)
        import asyncio as _aio
        tasks = [_fetch_history(p["ticker"], days=30) for p in pending]
        results = await _aio.gather(*tasks, return_exceptions=True) if tasks else []
        for p, data in zip(pending, results):
            try:
                if isinstance(data, Exception) or not data:
                    continue
                closes = data["close"]
                volumes = data["volume"]
                ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
                current_price = float(closes[-1])
                current_vol = float(volumes[-1])
                avg_vol = float(np.mean(volumes[-RC.ENTRY_VOL_PERIOD:])) if len(volumes) >= RC.ENTRY_VOL_PERIOD else 0

                p["current_price"] = current_price
                p["above_ma5"] = current_price > ma5
                p["ma5_value"] = round(ma5, 2)
                p["vol_confirmed"] = current_vol > avg_vol if avg_vol > 0 else False
                p["vol_ratio"] = round(current_vol / avg_vol, 2) if avg_vol > 0 else 0
            except Exception as e:
                logger.warning(f"[PENDING] Failed to enrich {p.get('ticker')}: {e}")

        return _tpl("partials/_pending_entries.html", {
            "request": request,
            "pending": pending,
        })
    except Exception as e:
        logger.error(f"Pending entries error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


@router.get("/htmx/pending-count", response_class=HTMLResponse)
async def htmx_pending_count(request: Request):
    """待进场数量（HTMX局部 — 用于顶部统计卡片）"""
    try:
        from app.services.rotation_service import get_current_positions
        all_positions = await get_current_positions() or []
        count = len([p for p in all_positions if p.get("status") == "pending_entry"])
        return HTMLResponse(str(count))
    except Exception:
        return HTMLResponse("--")


@router.get("/api/debug/tiger-open-orders")
async def debug_tiger_open_orders():
    """临时诊断端点：查看Tiger open orders返回数据"""
    from app.services.order_service import get_tiger_trade_client
    tiger = get_tiger_trade_client()
    try:
        open_orders = await tiger.get_open_orders()
        return {"count": len(open_orders), "orders": open_orders}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/debug/tiger-filled-orders")
async def debug_tiger_filled_orders(start: str = None, end: str = None):
    """查询 Tiger 已成交订单（供盘后复盘脚本调用）
    ?start=2026-03-24&end=2026-03-25
    """
    from app.services.order_service import get_tiger_trade_client
    tiger = get_tiger_trade_client()
    try:
        filled = await tiger.get_filled_orders(start_date=start, end_date=end)
        return {"count": len(filled), "orders": filled}
    except Exception as e:
        return {"error": str(e)}


@router.get("/htmx/sub-strategies", response_class=HTMLResponse)
async def htmx_sub_strategies(request: Request):
    """子策略信号面板（HTMX局部）— 展示 MR/ED 最新候选信号与资金分配"""
    try:
        from app.services.portfolio_manager import get_cached_daily_signals, get_strategy_allocations

        # 从 rotation_scores 缓存中获取当前体制
        regime = "unknown"
        cached_scores = _cache_get("rotation_scores")
        if cached_scores and isinstance(cached_scores, dict):
            regime = cached_scores.get("regime", "unknown")

        # 获取上次盘后扫描的缓存结果（调度器每日09:50 NZT写入）
        daily = get_cached_daily_signals()
        mr_candidates = (daily or {}).get("mr_candidates", [])
        ed_candidates = (daily or {}).get("ed_candidates", [])
        scan_date     = (daily or {}).get("date", None)

        # 当前体制资金分配
        alloc = get_strategy_allocations(regime)

        return _tpl("partials/_sub_strategies.html", {
            "request":       request,
            "regime":        regime,
            "alloc":         alloc,
            "mr_candidates": mr_candidates,
            "ed_candidates": ed_candidates,
            "scan_date":     scan_date,
            "mr_active":     alloc.get("mean_reversion", 0) > 0,
            "ed_active":     alloc.get("event_driven", 0) > 0,
        })
    except Exception as e:
        logger.error(f"Sub-strategies error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4 text-sm">子策略信号加载失败</div>')


@router.get("/htmx/event-signals", response_class=HTMLResponse)
async def htmx_event_signals(request: Request):
    """盘后 AI 事件信号面板（HTMX 局部）— 最近 7 天 event_signals 表"""
    import datetime as _dt
    from app.database import get_db
    LOOKBACK_DAYS = 7
    try:
        db = get_db()
        cutoff = (_dt.date.today() - _dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
        result = (
            db.table("event_signals")
            .select("date,ticker,event_type,direction,headline,signal_strength,source")
            .gte("date", cutoff)
            .order("date", desc=True)
            .order("signal_strength", desc=False)
            .limit(50)
            .execute()
        )
        events = result.data or []

        # 最新扫描时间（取最新一条的 date）
        last_scan = events[0]["date"] if events else None

        return _tpl("partials/_event_signals.html", {
            "request": request,
            "events": events,
            "lookback_days": LOOKBACK_DAYS,
            "last_scan": last_scan,
        })
    except Exception as e:
        logger.error(f"Event signals error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4 text-sm">事件信号加载失败</div>')


@router.get("/htmx/universe-status", response_class=HTMLResponse)
async def htmx_universe_status(request: Request):
    """选股池状态面板（HTMX局部）— 展示动态 Universe 当前规模、刷新时间、新增/移除变动"""
    import datetime as _dt

    ctx: dict = {
        "request": request,
        "available": False,
        "count": 0,
        "timestamp": None,
        "age_days": None,
        "added": [],
        "removed": [],
        "sector_breakdown": [],
    }

    try:
        from app.services.universe_service import UniverseService
        svc = UniverseService()
        latest = svc.get_current_universe_full()

        if not latest or not latest.get("tickers"):
            return _tpl("partials/_universe_status.html", ctx)

        tickers_now = {t["ticker"] for t in latest["tickers"]}
        ctx["count"] = len(tickers_now)
        ctx["timestamp"] = latest.get("timestamp", "")
        ctx["available"] = True

        # Age (days since refresh timestamp)
        ts = latest.get("timestamp", "")
        if ts:
            try:
                ctx["age_days"] = round(
                    (_dt.date.today() - _dt.date.fromisoformat(ts[:10])).days, 1
                )
            except Exception:
                pass

        # Sector breakdown (top 6)
        sectors: dict = {}
        for t in latest["tickers"]:
            s = t.get("sector") or "Unknown"
            sectors[s] = sectors.get(s, 0) + 1
        ctx["sector_breakdown"] = sorted(sectors.items(), key=lambda x: -x[1])[:6]

        # Change tracking vs previous Supabase snapshot
        prev = svc.get_previous_snapshot()
        if prev and prev.get("tickers"):
            tickers_prev = {t["ticker"] for t in prev["tickers"]}
            ctx["added"] = sorted(tickers_now - tickers_prev)[:20]
            ctx["removed"] = sorted(tickers_prev - tickers_now)[:20]

    except Exception as e:
        logger.warning(f"Universe status error: {e}")

    return _tpl("partials/_universe_status.html", ctx)


@router.get("/htmx/account-summary", response_class=HTMLResponse)
async def htmx_account_summary(request: Request):
    """Tiger 账户资金概览（HTMX局部）— 支持 ?account=primary|leverage|combined"""
    try:
        account = request.query_params.get("account", "primary")
        from app.services.order_service import get_tiger_trade_client

        if account == "combined":
            # Combined: sum both accounts
            from app.services.order_service import get_all_accounts_assets
            all_assets = await get_all_accounts_assets()
            primary = all_assets.get("primary") or {}
            leverage = all_assets.get("leverage") or {}
            assets = {
                "net_liquidation": (primary.get("net_liquidation", 0) or 0) + (leverage.get("net_liquidation", 0) or 0),
                "available_funds": (primary.get("available_funds", 0) or 0) + (leverage.get("available_funds", 0) or 0),
                "buying_power": (primary.get("buying_power", 0) or 0) + (leverage.get("buying_power", 0) or 0),
                "cash": (primary.get("cash", 0) or 0) + (leverage.get("cash", 0) or 0),
                "unrealized_pnl": (primary.get("unrealized_pnl", 0) or 0) + (leverage.get("unrealized_pnl", 0) or 0),
            }
        else:
            tiger = get_tiger_trade_client(account)
            assets = await tiger.get_account_assets()

        if not assets:
            return HTMLResponse(
                '<div class="text-4xl font-bold text-gray-600 font-mono tracking-tight">--</div>'
                '<div class="text-xs text-gray-500 mt-1">Tiger 未连接</div>'
            )

        # Paper trading account starts with "214" prefix
        if account == "leverage":
            acct_str = str(settings.tiger_account_2 or "")
            mode_label = "杠杆"
            accent_color = "cyan"
        elif account == "combined":
            acct_str = ""
            mode_label = "合并"
            accent_color = "purple"
        else:
            acct_str = str(settings.tiger_account or "")
            mode_label = "宝典"
            accent_color = "amber"
        is_paper = acct_str.startswith("214")
        mode = f"{mode_label} · {'模拟盘' if is_paper else '实盘'}"
        nlv = assets.get("net_liquidation", 0)
        avail = assets.get("available_funds", 0)
        cash = assets.get("cash", 0)
        buying_power = assets.get("buying_power", 0)

        # Tiger is source of truth — use Tiger's available_funds/cash/buying_power directly.
        # No manual deductions; MKT orders fill immediately so pending state is minimal.

        # Initial capital for paper trading is typically 1,000,000
        initial_capital = 1_000_000 if is_paper else nlv
        total_pnl = nlv - initial_capital
        pnl_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0
        pnl_color = "text-sq-green" if total_pnl >= 0 else "text-sq-red"
        pnl_sign = "+" if total_pnl >= 0 else ""

        # Get Tiger positions for the selected account
        if account == "combined":
            from app.services.order_service import get_all_accounts_positions
            all_pos = await get_all_accounts_positions()
            positions = all_pos.get("primary", []) + all_pos.get("leverage", [])
        elif account == "leverage":
            positions = await tiger.get_positions()
        else:
            positions = await tiger.get_positions()
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
        ur_color = "text-sq-green" if total_unrealized >= 0 else "text-sq-red"
        ur_sign = "+" if total_unrealized >= 0 else ""

        # Calculate total market value from Tiger positions
        total_market_value = sum(p.get("market_value", 0) for p in positions)

        # Tiger-style hero card: big NLV number + sub-metrics
        # This HTML replaces the #hero-nlv container AND populates #hero-metrics and #tiger-pos-summary
        html = f"""
        <!-- Big NLV number -->
        <div class="text-4xl lg:text-5xl font-bold text-white font-mono tracking-tight">
            {nlv:,.2f}
            <span class="text-xs font-normal px-2 py-0.5 rounded ml-2 bg-{accent_color}-900/60 text-{accent_color}-300">
                {mode}
            </span>
        </div>
        <div class="flex items-center gap-4 mt-1">
            <span class="text-sm font-mono font-semibold {pnl_color}">{pnl_sign}{total_pnl:,.2f}</span>
            <span class="text-xs {pnl_color}">({pnl_sign}{pnl_pct:.2f}%)</span>
        </div>

        <!-- Sub-metrics (inject into sibling via hx-swap-oob) -->
        <div id="hero-metrics" hx-swap-oob="innerHTML">
            <div>
                <div class="text-xs text-gray-500 mb-0.5">证券总价值</div>
                <div class="text-base font-mono text-white">{total_market_value:,.2f}</div>
            </div>
            <div>
                <div class="text-xs text-gray-500 mb-0.5">未实现盈亏</div>
                <div class="text-base font-mono {ur_color}">{ur_sign}{total_unrealized:,.2f}</div>
            </div>
            <div>
                <div class="text-xs text-gray-500 mb-0.5">预估现金</div>
                <div class="text-base font-mono text-white">{cash:,.2f}</div>
            </div>
            <div>
                <div class="text-xs text-gray-500 mb-0.5">购买力</div>
                <div class="text-base font-mono text-white">{buying_power:,.2f}</div>
            </div>
        </div>

        <!-- Today PnL (inject into hero card top-right) -->
        <div id="hero-today-pnl" hx-swap-oob="innerHTML">
            <div class="text-xs text-gray-500">今日盈亏</div>
            <div class="text-lg font-mono font-bold {ur_color}">{ur_sign}{total_unrealized:,.2f}</div>
            <div class="text-xs {ur_color}">({ur_sign}{(total_unrealized / nlv * 100) if nlv > 0 else 0:.2f}%)</div>
        </div>

        <!-- Tiger positions summary row (inject into positions section) -->
        <div id="tiger-pos-summary" hx-swap-oob="innerHTML">
            <div class="flex items-center gap-2">
                <span class="text-sm text-gray-400">美股市值(USD)</span>
                <span class="text-sm font-mono text-white font-semibold">{total_market_value:,.2f}</span>
            </div>
            <div class="text-sm font-mono font-semibold {ur_color}">{ur_sign}{total_unrealized:,.2f}</div>
        </div>
        <!-- v=20260324-tiger-style -->
        """
        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Account summary error: {e}")
        err = str(e)[:120]
        return HTMLResponse(
            f'<div class="text-4xl font-bold text-gray-600 font-mono tracking-tight">--</div>'
            f'<div class="text-xs text-gray-500 mt-1">Tiger 未连接 '
            f'<span class="text-red-400 text-[10px]">{err}</span></div>'
        )


@router.get("/htmx/tiger-diagnostics", response_class=HTMLResponse)
async def htmx_tiger_diagnostics(request: Request):
    """Tiger SDK 连接诊断 — 逐步检查凭证、初始化、API 调用"""
    from app.services.order_service import get_tiger_trade_client

    steps = []

    def ok(label, detail=""):
        steps.append(("ok", label, detail))

    def fail(label, detail=""):
        steps.append(("fail", label, detail))

    def warn(label, detail=""):
        steps.append(("warn", label, detail))

    # Step 1: credentials
    tid = settings.tiger_id or ""
    acct = settings.tiger_account or ""
    pk = settings.tiger_private_key or ""

    ok("TIGER_ID", tid) if tid else fail("TIGER_ID", "not set")
    ok("TIGER_ACCOUNT", acct) if acct else fail("TIGER_ACCOUNT", "not set")
    if not pk:
        fail("TIGER_PRIVATE_KEY", "not set")
    elif "\\n" in pk and "\n" not in pk:
        fail("TIGER_PRIVATE_KEY", "literal \\\\n detected — env var not parsed correctly")
    elif pk.strip().startswith("-----BEGIN"):
        lines = pk.strip().splitlines()
        ok("TIGER_PRIVATE_KEY", f"PEM format, {len(lines)} lines")
    else:
        # Raw base64 — valid, will be wrapped with headers automatically
        preview = pk.strip()[:24]
        ok("TIGER_PRIVATE_KEY", f"raw base64 (will auto-wrap PEM headers), starts: {preview!r}")

    sandbox = settings.tiger_sandbox
    warn("TIGER_SANDBOX", "True (paper trading)") if sandbox else ok("TIGER_SANDBOX", "False (live)")

    # Step 2: SDK init
    try:
        tiger = get_tiger_trade_client()
        # Force re-init by calling internal method
        client = await tiger._run_sync(tiger._get_trade_client)
        if client:
            ok("SDK init", "TradeClient created")
        else:
            fail("SDK init", "returned None — check logs for details")
    except Exception as e:
        fail("SDK init", str(e)[:200])

    # Step 3: API call
    try:
        assets = await tiger.get_account_assets()
        if assets:
            nlv = assets.get("net_liquidation", 0)
            ok("get_account_assets()", f"net_liquidation=${nlv:,.0f}")
        else:
            fail("get_account_assets()", "returned empty")
    except Exception as e:
        fail("get_account_assets()", str(e)[:200])

    # Build HTML
    rows = ""
    for status, label, detail in steps:
        if status == "ok":
            icon, color = "✓", "text-sq-green"
        elif status == "fail":
            icon, color = "✗", "text-sq-red"
        else:
            icon, color = "⚠", "text-yellow-400"
        rows += (
            f'<div class="flex gap-2 py-1 text-xs border-b border-gray-800 last:border-0">'
            f'<span class="{color} font-bold w-4">{icon}</span>'
            f'<span class="text-gray-300 w-40 shrink-0">{label}</span>'
            f'<span class="text-gray-500 font-mono break-all">{detail}</span>'
            f'</div>'
        )

    return HTMLResponse(
        f'<div class="bg-sq-card rounded-xl border border-sq-border p-4">'
        f'<div class="text-sm font-bold text-white mb-3">Tiger 诊断</div>'
        f'<div class="space-y-0">{rows}</div>'
        f'</div>'
    )


@router.post("/api/tiger/place-orders", response_class=HTMLResponse)
async def api_tiger_place_orders(request: Request):
    """
    Step 2 of 2-step entry flow: place MKT buy orders for all pending_submit positions.
    - Only processes pending_submit (conditions already verified in activate-positions)
    - On Tiger success: status → active, records tiger_order_id
    - On Tiger failure: keeps pending_submit, records error in tiger_order_status (retryable)
    """
    from app.services.order_service import get_tiger_trade_client, calculate_position_size
    from app.database import get_db

    results = []
    tiger = get_tiger_trade_client()

    # Test Tiger connection
    try:
        assets = await tiger.get_account_assets()
        if not assets:
            return HTMLResponse(
                '<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
                '<span class="text-sq-red font-bold">Tiger connection failed</span>'
                '<p class="text-gray-400 mt-1">Cannot reach Tiger API — check credentials</p></div>'
            )
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">Tiger connection error</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    db = get_db()

    # Only process pending_submit — conditions already verified
    try:
        pos_result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, stop_loss, take_profit, status, tiger_order_id, quantity, position_type, entry_condition_met")
            .eq("status", "pending_submit")
            .execute()
        )
        positions = pos_result.data if pos_result.data else []
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">DB query failed</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    if not positions:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
            'No pending_submit positions — run "Check Conditions" first</div>'
        )

    # Alpha score sort: rank by score if multiple positions
    if len(positions) > 1:
        try:
            snap_result = (
                db.table("rotation_snapshots")
                .select("scores")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            snap_scores = (snap_result.data or [{}])[0].get("scores") or []
            score_map = {s["ticker"]: s.get("score", 0.0) for s in snap_scores if "ticker" in s}
            positions.sort(key=lambda p: score_map.get(p["ticker"], -999), reverse=True)
            logger.info(f"[PLACE-ORDER] Alpha sort: {[p['ticker'] for p in positions]}")
        except Exception as e:
            logger.warning(f"[PLACE-ORDER] Alpha sort failed, keeping original order: {e}")

    # Enforce slot limit: only fill up to (TOP_N - current alpha active) slots
    try:
        from app.config.rotation_watchlist import INVERSE_ETF_INDEX_MAP, RotationConfig as RC
        hedge_tickers = set(INVERSE_ETF_INDEX_MAP.keys())
        active_result = db.table("rotation_positions").select("ticker").eq("status", "active").execute()
        alpha_active_count = sum(1 for r in (active_result.data or []) if r["ticker"] not in hedge_tickers)
        available_slots = max(0, RC.TOP_N - alpha_active_count)
        alpha_positions = [p for p in positions if p.get("position_type", "alpha") != "hedge"]
        hedge_positions = [p for p in positions if p.get("position_type", "alpha") == "hedge"]
        if len(alpha_positions) > available_slots:
            logger.info(f"[PLACE-ORDER] {len(alpha_positions)} alpha pending_submit > {available_slots} slots, "
                        f"capping: {[p['ticker'] for p in alpha_positions[:available_slots]]}")
            alpha_positions = alpha_positions[:available_slots]
        positions = alpha_positions + hedge_positions
    except Exception as e:
        logger.warning(f"[PLACE-ORDER] Slot limit check failed, processing all: {e}")

    # Get Tiger current positions (for sync detection — manual buys)
    tiger_held = {}
    try:
        tiger_positions = await tiger.get_positions()
        for tp in tiger_positions:
            tk = tp.get("ticker", "")
            if tk:
                tiger_held[tk] = {
                    "quantity": tp.get("quantity", 0),
                    "avg_cost": tp.get("average_cost", 0),
                    "latest_price": tp.get("latest_price", 0),
                }
        logger.info(f"[PLACE-ORDER] Tiger already holds: {list(tiger_held.keys())}")
    except Exception as e:
        logger.warning(f"[PLACE-ORDER] Failed to get Tiger positions: {type(e).__name__}: {e}")

    for pos in positions:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")
        entry_price = pos.get("entry_price", 0)
        stop_loss = pos.get("stop_loss")
        take_profit = pos.get("take_profit")
        existing_order = pos.get("tiger_order_id")

        # Skip if already submitted
        if existing_order:
            results.append({
                "ticker": ticker, "success": True, "skipped": True,
                "msg": f"Already has order ID: {existing_order[:8]}..."
            })
            continue

        # Sync check: Tiger already holds this stock (manual buy before system order)
        if ticker in tiger_held:
            held = tiger_held[ticker]
            held_qty = held.get("quantity", 0)
            held_cost = held.get("avg_cost", 0)
            held_price = held.get("latest_price", 0)
            if held_qty > 0 and held_cost > 0:
                if not stop_loss or not take_profit:
                    atr = held_cost * 0.03
                    stop_loss = round(held_cost - 2 * atr, 2)
                    take_profit = round(held_cost + 3 * atr, 2)
                db.table("rotation_positions").update({
                    "entry_price": round(held_cost, 4),
                    "entry_date": date.today().isoformat(),
                    "current_price": round(held_price, 4) if held_price > 0 else round(held_cost, 4),
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "quantity": held_qty,
                    "actual_fill_price": round(held_cost, 4),
                    "actual_fill_qty": held_qty,
                    "status": "active",
                    "tiger_order_status": "filled",
                }).eq("id", pos_id).execute()
                pnl = round((held_price - held_cost) / held_cost * 100, 1) if held_cost > 0 and held_price > 0 else 0
                results.append({
                    "ticker": ticker, "success": True,
                    "msg": f"Synced Tiger position: {held_qty} shares @ ${held_cost:.2f} (now ${held_price:.2f}, {'+' if pnl >= 0 else ''}{pnl}%)"
                })
                logger.info(f"[PLACE-ORDER] {ticker} synced from Tiger: {held_qty} @ ${held_cost:.2f}")
                continue

        if not entry_price or entry_price <= 0:
            results.append({"ticker": ticker, "success": False,
                            "msg": "entry_price missing — re-run condition check"})
            continue

        # Set stop_loss / take_profit if missing
        if not stop_loss or not take_profit:
            atr = entry_price * 0.03
            stop_loss = round(entry_price - 2 * atr, 2)
            take_profit = round(entry_price + 3 * atr, 2)
            db.table("rotation_positions").update({
                "stop_loss": stop_loss, "take_profit": take_profit,
            }).eq("id", pos_id).execute()

        # Calculate position size (hedge-aware)
        try:
            from app.config.rotation_watchlist import RotationConfig as RC
            from app.services.rotation_service import _detect_regime
            pos_type = pos.get("position_type", "alpha")
            if pos_type == "hedge":
                _equity_frac = RC.HEDGE_ALLOC_BY_REGIME.get(await _detect_regime(), 0.0)
            else:
                _regime = await _detect_regime()
                _hedge_frac = RC.HEDGE_ALLOC_BY_REGIME.get(_regime, 0.0)
                _equity_frac = 1.0 - _hedge_frac
                logger.info(f"[PLACE-ORDER] regime={_regime} hedge={_hedge_frac:.0%} alpha={_equity_frac:.0%}")
            qty = await calculate_position_size(tiger, entry_price, max_positions=RC.TOP_N, equity_fraction=_equity_frac)
            if qty <= 0:
                results.append({"ticker": ticker, "success": False, "msg": "Position size = 0"})
                continue
        except Exception as e:
            results.append({"ticker": ticker, "success": False, "msg": f"Position size calc failed: {e}"})
            continue

        # Place MKT buy order
        try:
            result = await tiger.place_buy_order(
                ticker=ticker,
                quantity=qty,
                order_type="MKT",
            )
            if result:
                order_id = str(result.get("id") or result.get("order_id", ""))
                db.table("rotation_positions").update({
                    "quantity": qty,
                    "entry_date": date.today().isoformat(),
                    "tiger_order_id": order_id,
                    "tiger_order_status": "submitted",
                    "status": "active",
                }).eq("id", pos_id).execute()
                results.append({
                    "ticker": ticker, "success": True,
                    "msg": f"MKT buy {qty} shares | Order: {order_id[:8]}..."
                })
                logger.info(f"[PLACE-ORDER] {ticker} → active, qty={qty}, order={order_id}")
            else:
                # Empty result — keep pending_submit for retry
                db.table("rotation_positions").update({
                    "tiger_order_status": "failed_empty_result",
                }).eq("id", pos_id).execute()
                results.append({"ticker": ticker, "success": False,
                                "msg": "Tiger returned empty result (kept pending_submit, retryable)"})
                logger.error(f"[PLACE-ORDER] {ticker}: Tiger returned empty result")
        except Exception as e:
            # Exception — keep pending_submit for retry
            err_msg = str(e)[:120]
            db.table("rotation_positions").update({
                "tiger_order_status": f"failed: {err_msg}",
            }).eq("id", pos_id).execute()
            results.append({"ticker": ticker, "success": False,
                            "msg": f"Order failed (kept pending_submit, retryable): {err_msg}"})
            logger.error(f"[PLACE-ORDER] {ticker} failed: {e}", exc_info=True)

    # Build result HTML
    rows_html = ""
    for r in results:
        ticker = r["ticker"]
        if r.get("skipped"):
            rows_html += (
                f'<div class="flex items-center gap-2 py-1.5 text-xs">'
                f'<span class="font-mono font-bold text-white">{ticker}</span>'
                f'<span class="text-gray-500">⏭ {r["msg"]}</span></div>'
            )
        elif r["success"]:
            rows_html += (
                f'<div class="flex items-center gap-2 py-1.5 text-xs">'
                f'<span class="font-mono font-bold text-white">{ticker}</span>'
                f'<span class="text-sq-green">{r["msg"]}</span></div>'
            )
        else:
            rows_html += (
                f'<div class="flex items-center gap-2 py-1.5 text-xs">'
                f'<span class="font-mono font-bold text-white">{ticker}</span>'
                f'<span class="text-sq-red">❌ {r["msg"]}</span></div>'
            )

    success_count = sum(1 for r in results if r["success"] and not r.get("skipped"))
    fail_count = sum(1 for r in results if not r["success"])
    skip_count = sum(1 for r in results if r.get("skipped"))

    summary = f"成功 {success_count} | 失败 {fail_count} | 跳过 {skip_count}"

    html = f"""
    <div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-2">
        <div class="flex items-center justify-between">
            <span class="text-sm font-bold text-white">🐯 Tiger 下单结果</span>
            <span class="text-xs text-gray-400">{summary}</span>
        </div>
        <div class="divide-y divide-gray-800">{rows_html}</div>
    </div>
    """
    return HTMLResponse(html)


@router.post("/api/tiger/activate-positions", response_class=HTMLResponse)
async def api_tiger_activate_positions(request: Request):
    """
    Step 1 of 2-step entry flow: verify entry conditions for all pending_entry positions.
    - Alpha positions: check above_ma20 from latest rotation_snapshot
    - Hedge positions: always pass (no condition check)
    - On pass: status → pending_submit, record signal_price + entry_condition_met
    - On fail: keep pending_entry, log reason
    """
    from app.database import get_db
    from app.services.massive_client import MassiveClient as MassiveAPIClient
    from datetime import datetime, timezone

    db = get_db()
    try:
        pos_result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, stop_loss, take_profit, status, position_type")
            .eq("status", "pending_entry")
            .execute()
        )
        positions = pos_result.data if pos_result.data else []
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">DB query failed</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    if not positions:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
            'No pending_entry positions</div>'
        )

    # Load latest snapshot scores: {ticker: {above_ma20, current_price, score}}
    snapshot_map = {}
    try:
        snap_result = (
            db.table("rotation_snapshots")
            .select("scores")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        snap_scores = (snap_result.data or [{}])[0].get("scores") or []
        for s in snap_scores:
            t = s.get("ticker")
            if t:
                snapshot_map[t] = {
                    "above_ma20": s.get("above_ma20", False),
                    "signal_price": s.get("current_price", 0),
                }
        logger.info(f"[ACTIVATE] Loaded snapshot for {len(snapshot_map)} tickers")
    except Exception as e:
        logger.warning(f"[ACTIVATE] Failed to load snapshot: {e}")

    # Get realtime prices from Massive API
    tickers = [p["ticker"] for p in positions]
    realtime_prices = {}
    try:
        massive = MassiveAPIClient()
        quotes = await massive.batch_get_quotes(tickers)
        for tk, q in quotes.items():
            price = q.get("latest_price", 0)
            if price and price > 0:
                realtime_prices[tk] = price
        logger.info(f"[ACTIVATE] Massive prices: {realtime_prices}")
    except Exception as e:
        logger.warning(f"[ACTIVATE] Massive API failed: {e}")

    results = []
    now_utc = datetime.now(timezone.utc).isoformat()

    for pos in positions:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")
        pos_type = pos.get("position_type", "alpha")

        # Get current price: Massive realtime → fallback to snapshot signal_price
        current_price = realtime_prices.get(ticker, 0)
        if current_price <= 0:
            current_price = snapshot_map.get(ticker, {}).get("signal_price", 0)
            price_source = "snapshot"
        else:
            price_source = "Massive"

        if current_price <= 0:
            results.append({"ticker": ticker, "success": False,
                            "msg": f"Cannot get price (Massive + snapshot both failed)"})
            continue

        # Hedge positions: skip condition check, pass directly
        if pos_type == "hedge":
            db.table("rotation_positions").update({
                "entry_price": round(current_price, 4),
                "signal_price": round(current_price, 4),
                "entry_condition_met": True,
                "price_fetch_time": now_utc,
                "status": "pending_submit",
            }).eq("id", pos_id).execute()
            results.append({"ticker": ticker, "success": True,
                            "msg": f"[HEDGE] pending_submit @ ${current_price:.2f} ({price_source})"})
            logger.info(f"[ACTIVATE] [HEDGE] {ticker} → pending_submit @ ${current_price:.2f}")
            continue

        # Alpha positions: check above_ma20 from snapshot
        snap = snapshot_map.get(ticker, {})
        above_ma20 = snap.get("above_ma20", False)
        snapshot_price = snap.get("signal_price", 0)

        if not above_ma20:
            results.append({"ticker": ticker, "success": False,
                            "msg": f"SKIP: not above MA20 (snapshot price=${snapshot_price:.2f})"})
            logger.warning(f"[ACTIVATE] SKIP {ticker}: above_ma20=False, price=${current_price:.2f}")
            continue

        # Condition met — move to pending_submit
        stop_loss = pos.get("stop_loss")
        take_profit = pos.get("take_profit")
        if not stop_loss or not take_profit:
            atr = current_price * 0.03
            stop_loss = round(current_price - 2 * atr, 2)
            take_profit = round(current_price + 3 * atr, 2)

        db.table("rotation_positions").update({
            "entry_price": round(current_price, 4),
            "signal_price": round(current_price, 4),
            "signal_date": now_utc,
            "entry_condition_met": True,
            "price_fetch_time": now_utc,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "pending_submit",
        }).eq("id", pos_id).execute()

        results.append({"ticker": ticker, "success": True,
                        "msg": f"pending_submit @ ${current_price:.2f} ({price_source}) | above_MA20=True"})
        logger.info(f"[ACTIVATE] {ticker} → pending_submit @ ${current_price:.2f} (above_MA20=True)")

    # Build result HTML
    rows_html = ""
    for r in results:
        color = "text-sq-green" if r["success"] else "text-sq-yellow"
        rows_html += (
            f'<div class="flex items-center gap-2 py-1.5 text-xs">'
            f'<span class="font-mono font-bold text-white">{r["ticker"]}</span>'
            f'<span class="{color}">{r["msg"]}</span></div>'
        )

    ok = sum(1 for r in results if r["success"])
    skip = sum(1 for r in results if not r["success"])

    html = f"""
    <div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-2">
        <div class="flex items-center justify-between">
            <span class="text-sm font-bold text-white">Step 1: Condition Check</span>
            <span class="text-xs text-gray-400">passed {ok} | skipped {skip}</span>
        </div>
        <div class="divide-y divide-gray-800">{rows_html}</div>
        <p class="text-xs text-gray-500 pt-1">Passed positions are now pending_submit — run "Place Orders" to submit to Tiger.</p>
    </div>
    """
    return HTMLResponse(html)


@router.post("/api/tiger/deactivate-positions", response_class=HTMLResponse)
async def api_tiger_deactivate_positions(request: Request):
    """
    Emergency rollback: revert pending_submit or today's active positions back to pending_entry.
    Clears entry_price, entry_date, stop_loss, take_profit, signal fields.
    """
    from app.database import get_db

    db = get_db()
    today = date.today().isoformat()

    try:
        # Roll back both pending_submit (condition checked but not yet ordered)
        # and today's active (ordered today but needs cancellation)
        pending_submit_result = (
            db.table("rotation_positions")
            .select("id, ticker, status")
            .eq("status", "pending_submit")
            .execute()
        )
        active_today_result = (
            db.table("rotation_positions")
            .select("id, ticker, status")
            .eq("status", "active")
            .eq("entry_date", today)
            .execute()
        )
        positions = (pending_submit_result.data or []) + (active_today_result.data or [])
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">DB query failed</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    if not positions:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
            'Nothing to rollback (no pending_submit or today\'s active positions)</div>'
        )

    results = []
    for pos in positions:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")
        prev_status = pos.get("status", "?")
        try:
            db.table("rotation_positions").update({
                "entry_price": None,
                "entry_date": None,
                "stop_loss": None,
                "take_profit": None,
                "signal_price": None,
                "signal_ma5": None,
                "signal_date": None,
                "entry_condition_met": None,
                "price_fetch_time": None,
                "tiger_order_status": None,
                "status": "pending_entry",
            }).eq("id", pos_id).execute()
            results.append({"ticker": ticker, "success": True,
                            "msg": f"{prev_status} → pending_entry"})
            logger.info(f"[DEACTIVATE] {ticker} {prev_status}→pending_entry (manual rollback)")
        except Exception as e:
            results.append({"ticker": ticker, "success": False, "msg": f"Rollback failed: {e}"})

    rows_html = ""
    for r in results:
        color = "text-sq-green" if r["success"] else "text-sq-red"
        icon = "" if r["success"] else "❌ "
        rows_html += (
            f'<div class="flex items-center gap-2 py-1.5 text-xs">'
            f'<span class="font-mono font-bold text-white">{r["ticker"]}</span>'
            f'<span class="{color}">{icon}{r["msg"]}</span></div>'
        )

    ok = sum(1 for r in results if r["success"])
    fail = sum(1 for r in results if not r["success"])

    html = f"""
    <div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-2">
        <div class="flex items-center justify-between">
            <span class="text-sm font-bold text-white">🔄 撤回激活结果</span>
            <span class="text-xs text-gray-400">成功 {ok} | 失败 {fail}</span>
        </div>
        <div class="divide-y divide-gray-800">{rows_html}</div>
    </div>
    """
    return HTMLResponse(html)


@router.post("/api/position/{position_id}/close", response_class=HTMLResponse)
async def api_close_position(request: Request, position_id: str):
    """
    手动关闭 DB 持仓记录（仅标记为 closed，不在 Tiger 执行卖出）。
    用于清理非当前信号的遗留仓位。
    """
    from app.database import get_db
    db = get_db()
    try:
        result = db.table("rotation_positions").select("ticker, status, entry_price").eq("id", position_id).execute()
        if not result.data:
            return HTMLResponse(
                '<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
                '<span class="text-sq-red">❌ 持仓记录不存在</span></div>'
            )
        pos = result.data[0]
        ticker = pos.get("ticker", "?")

        # 尝试从 Tiger 获取真实退出价：
        # 1. 先查 filled SELL orders（已卖出的真实成交价）
        # 2. 回退到 Tiger 当前持仓的 latest_price（尚未卖出但要关闭记录）
        exit_price = 0.0
        try:
            from app.services.order_service import get_tiger_trade_client, _fetch_exit_price_from_filled
            tiger = get_tiger_trade_client()
            # 优先从 filled SELL orders 获取成交价
            filled_price = await _fetch_exit_price_from_filled(tiger, ticker, lookback_days=30)
            if filled_price and filled_price > 0:
                exit_price = filled_price
            else:
                # 回退到 Tiger 当前持仓的 latest_price
                tiger_positions = await tiger.get_positions()
                for tp in tiger_positions:
                    if tp.get("ticker") == ticker:
                        exit_price = float(tp.get("latest_price") or tp.get("average_cost") or 0)
                        break
        except Exception as e:
            logger.warning(f"[CLOSE-POS] 获取 {ticker} Tiger 价格失败: {e}")

        update_data = {
            "status": "closed",
            "exit_date": date.today().isoformat(),
            "exit_reason": "manual_close",
        }
        if exit_price > 0:
            update_data["exit_price"] = round(exit_price, 4)

        db.table("rotation_positions").update(update_data).eq("id", position_id).execute()
        price_note = f"，退出价 ${exit_price:.2f}" if exit_price > 0 else ""
        logger.info(f"[CLOSE-POS] {ticker} (id={position_id}) manually closed{price_note}")
        return HTMLResponse(
            f'<div class="bg-gray-800 rounded-lg p-3 text-sm">'
            f'<span class="text-gray-400">✅ {ticker} 持仓记录已关闭（DB标记为 closed{price_note}）。'
            f'如Tiger仍持有该股，请在Tiger端手动卖出。</span>'
            f'<p class="text-xs text-gray-600 mt-1">刷新页面查看更新</p></div>'
        )
    except Exception as e:
        logger.error(f"[CLOSE-POS] 关闭失败 id={position_id}: {e}", exc_info=True)
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 关闭失败</span>'
            f'<p class="text-gray-400 mt-1 text-xs">{e}</p></div>'
        )


@router.post("/api/tiger/rebalance", response_class=HTMLResponse)
async def api_tiger_rebalance(request: Request):
    """
    补齐仓位：对每个 active filled 持仓，比较当前持股量 vs 目标等权数量，
    若不足则下 MKT 补买单。
    """
    from app.services.order_service import get_tiger_trade_client, calculate_position_size
    from app.config.rotation_watchlist import RotationConfig as RC
    from app.services.rotation_service import _detect_regime
    from app.services.portfolio_manager import get_strategy_allocations
    from app.database import get_db
    import math

    db = get_db()
    tiger = get_tiger_trade_client()

    # 获取 regime-aware hedge 比例（实时检测，不依赖缓存）
    # alpha 仓位 = 总权益 × (1 - hedge_alloc) / TOP_N
    _regime = await _detect_regime()
    _hedge_frac = RC.HEDGE_ALLOC_BY_REGIME.get(_regime, 0.0)
    _alpha_frac = 1.0 - _hedge_frac
    logger.info(f"[REBALANCE] regime={_regime} hedge={_hedge_frac:.0%} alpha={_alpha_frac:.0%}")

    # 1. 获取账户权益
    try:
        assets = await tiger.get_account_assets()
        equity = assets.get("net_liquidation", 0) if assets else 0
        if equity <= 0:
            return HTMLResponse('<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm"><span class="text-sq-red">❌ 无法获取账户权益</span></div>')
    except Exception as e:
        return HTMLResponse(f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm"><span class="text-sq-red">❌ {e}</span></div>')

    target_per_pos = (equity * _alpha_frac) / RC.TOP_N

    # 2. 获取 Tiger 实际持仓
    try:
        tiger_positions = await tiger.get_positions()
        tiger_held = {tp.get("ticker", ""): tp for tp in tiger_positions if tp.get("quantity", 0) > 0}
    except Exception as e:
        return HTMLResponse(f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm"><span class="text-sq-red">❌ 获取持仓失败: {e}</span></div>')

    # 3. 获取 DB 活跃持仓
    try:
        result = db.table("rotation_positions").select("id, ticker, quantity, entry_price").neq("status", "closed").execute()
        db_positions = result.data or []
    except Exception as e:
        return HTMLResponse(f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm"><span class="text-sq-red">❌ DB查询失败: {e}</span></div>')

    results = []
    seen_tickers = set()  # prevent duplicate orders if DB has multiple records for same ticker
    for pos in db_positions:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")

        if ticker in seen_tickers:
            results.append({"ticker": ticker, "action": "skip", "msg": "跳过重复DB记录"})
            continue
        seen_tickers.add(ticker)

        if ticker not in tiger_held:
            results.append({"ticker": ticker, "action": "skip", "msg": "Tiger未持有，跳过"})
            continue

        tp = tiger_held[ticker]
        current_qty = tp.get("quantity", 0)
        avg_cost = float(tp.get("average_cost", 0) or 0)
        # latest_price key may exist with value 0.0 (paper trading); fall back to avg_cost
        latest_price = float(tp.get("latest_price", 0) or 0) or avg_cost
        current_value = current_qty * latest_price

        if latest_price <= 0:
            logger.warning(f"[REBALANCE] {ticker}: no price data (avg_cost={avg_cost}, latest_price from Tiger={tp.get('latest_price')})")
            results.append({"ticker": ticker, "action": "skip", "msg": f"价格数据缺失，跳过 (avg={avg_cost})"})
            continue

        target_qty = math.floor(target_per_pos / latest_price)
        shortfall_qty = target_qty - current_qty

        # 安全检查：若当前持仓已超过目标 105%，不买（防止快速双击导致超仓）
        if current_value >= target_per_pos * 1.05:
            pct = round(current_value / target_per_pos * 100, 1)
            results.append({"ticker": ticker, "action": "ok", "msg": f"✅ 仓位正常 ({current_qty}股 = {pct}% 目标)"})
            continue

        if shortfall_qty <= 0:
            pct = round(current_value / target_per_pos * 100, 1)
            results.append({"ticker": ticker, "action": "ok", "msg": f"✅ 仓位正常 ({current_qty}股 = {pct}% 目标)"})
            continue

        # 下补仓买单
        try:
            logger.info(f"[REBALANCE] Placing BUY {shortfall_qty}x {ticker} @ MKT (target={target_qty}, current={current_qty}, price=${latest_price:.2f})")
            buy_result = await tiger.place_buy_order(ticker, shortfall_qty, order_type="MKT")
            order_id_val = buy_result.get("order_id") if buy_result else None
            if buy_result and order_id_val is not None:
                new_id = str(order_id_val)
                db.table("rotation_positions").update({
                    "tiger_order_id": new_id,
                    "tiger_order_status": "submitted",
                    "quantity": target_qty,
                }).eq("id", pos_id).execute()
                cost = round(shortfall_qty * latest_price)
                results.append({"ticker": ticker, "action": "topped_up", "msg": f"🔄 补买 +{shortfall_qty}股 ~${cost:,} (目标{target_qty}股)"})
            else:
                logger.error(f"[REBALANCE] {ticker}: place_buy_order returned {buy_result}")
                results.append({"ticker": ticker, "action": "failed", "msg": f"❌ 补买无返回 (result={buy_result})"})
        except Exception as e:
            results.append({"ticker": ticker, "action": "failed", "msg": f"❌ 补买失败: {e}"})

    rows_html = ""
    for r in results:
        color = "text-sq-green" if r["action"] in ("ok", "topped_up") else "text-sq-red" if r["action"] == "failed" else "text-gray-500"
        rows_html += (
            f'<div class="flex items-center gap-2 py-1.5 text-xs">'
            f'<span class="font-mono font-bold text-white w-12">{r["ticker"]}</span>'
            f'<span class="{color}">{r["msg"]}</span></div>'
        )

    target_fmt = f"${target_per_pos:,.0f}"
    html = (
        f'<div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-2">'
        f'<div class="text-sm font-bold text-white mb-1">⚖️ 补齐仓位结果</div>'
        f'<div class="text-xs text-gray-500 mb-2">账户权益 ${equity:,.0f} ÷ {RC.TOP_N}仓 = 每仓目标 {target_fmt}</div>'
        f'<div class="divide-y divide-gray-800">{rows_html}</div></div>'
    )
    return HTMLResponse(content=html, headers={"HX-Trigger": "refreshPositions"})


@router.get("/api/tiger/open-orders", response_class=HTMLResponse)
async def api_tiger_open_orders(request: Request):
    """诊断：显示 Tiger 当前所有挂单"""
    from app.services.order_service import get_tiger_trade_client
    tiger = get_tiger_trade_client()
    try:
        orders = await tiger.get_open_orders()
        if not orders:
            return HTMLResponse('<div class="bg-sq-card rounded-xl border border-sq-border p-4 text-xs text-gray-400">Tiger 当前无挂单</div>')
        rows = ""
        for o in orders:
            rows += (
                f'<div class="flex gap-3 py-1.5 text-xs border-b border-gray-800">'
                f'<span class="font-mono font-bold text-white w-12">{o.get("ticker","?")}</span>'
                f'<span class="text-gray-400">{o.get("action","?")} {o.get("quantity","?")}股</span>'
                f'<span class="text-gray-500">{o.get("order_type","?")} status={o.get("status","?")}</span>'
                f'<span class="text-gray-600 font-mono text-[10px]">id={o.get("order_id","?")}</span>'
                f'</div>'
            )
        return HTMLResponse(
            f'<div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-1">'
            f'<div class="text-sm font-bold text-white mb-2">Tiger 挂单列表 ({len(orders)}笔)</div>'
            f'{rows}</div>'
        )
    except Exception as e:
        return HTMLResponse(f'<div class="text-sq-red text-xs">❌ {e}</div>')


@router.post("/api/tiger/resubmit-unfilled", response_class=HTMLResponse)
async def api_tiger_resubmit_unfilled(request: Request):
    """
    手动触发：检查所有 tiger_order_status='submitted' 的活跃持仓，
    若 Tiger 实际没有该持仓，则撤销旧单并以市价重新下单。
    """
    from app.services.order_service import get_tiger_trade_client, TigerTradeClient
    from app.database import get_db

    db = get_db()
    tiger = get_tiger_trade_client()

    # 1. 获取所有已提交但未确认成交的活跃持仓
    try:
        result = (
            db.table("rotation_positions")
            .select("id, ticker, tiger_order_id, tiger_order_status, quantity, entry_price, atr14")
            .eq("tiger_order_status", "submitted")
            .neq("status", "closed")
            .execute()
        )
        submitted = result.data or []
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
            f'<span class="text-sq-red">❌ DB查询失败: {e}</span></div>'
        )

    if not submitted:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-3 text-sm text-gray-400 text-center">'
            '无已提交待确认的订单</div>'
        )

    # 2. 获取 Tiger 实际持仓
    try:
        tiger_positions = await tiger.get_positions()
        tiger_held = {tp.get("ticker", ""): tp for tp in tiger_positions if tp.get("quantity", 0) > 0}
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
            f'<span class="text-sq-red">❌ 获取Tiger持仓失败: {e}</span></div>'
        )

    results = []
    for pos in submitted:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")
        qty = pos.get("quantity", 0)
        tiger_id = pos.get("tiger_order_id")

        # 若 Tiger 实际已持有，仅更新状态为 filled
        if ticker in tiger_held:
            tp = tiger_held[ticker]
            fill_price = tp.get("average_cost", 0)
            fill_qty = tp.get("quantity", 0)
            update = {"tiger_order_status": "filled"}
            if fill_price > 0:
                update["entry_price"] = round(fill_price, 4)
                update["current_price"] = round(tp.get("latest_price", fill_price), 4)
                atr14 = float(pos.get("atr14") or 0)
                if atr14 > 0:
                    from app.config.rotation_watchlist import RotationConfig as RC
                    from app.services.rotation_service import _detect_regime
                    _regime = await _detect_regime()
                    _stop_mult = RC.ATR_STOP_BY_REGIME.get(_regime, RC.ATR_STOP_MULTIPLIER)
                    _target_mult = RC.ATR_TARGET_BY_REGIME.get(_regime, RC.ATR_TARGET_MULTIPLIER)
                    update["stop_loss"] = round(fill_price - _stop_mult * atr14, 2)
                    update["take_profit"] = round(fill_price + _target_mult * atr14, 2)
            if fill_qty > 0:
                update["quantity"] = fill_qty
            db.table("rotation_positions").update(update).eq("id", pos_id).execute()
            results.append({"ticker": ticker, "action": "synced", "msg": f"✅ 已同步成交: {fill_qty}股 @ ${fill_price:.2f}"})
            continue

        # Tiger 没有该持仓 → 撤旧单，重新下 MKT 单
        if tiger_id:
            try:
                await tiger.cancel_order(int(tiger_id))
                logger.info(f"[RESUBMIT] Cancelled old order {tiger_id} for {ticker}")
            except Exception as e:
                logger.warning(f"[RESUBMIT] Cancel failed for {tiger_id}: {e}")

        # 重新下 MKT 单 — 重新计算正确数量（hedge-aware，实时检测 regime）
        try:
            from app.config.rotation_watchlist import RotationConfig as RC
            from app.services.rotation_service import _detect_regime
            _regime = await _detect_regime()
            _hedge_frac = RC.HEDGE_ALLOC_BY_REGIME.get(_regime, 0.0)
            _v4_fraction = 1.0 - _hedge_frac
            entry_price = pos.get("entry_price") or 0
            if entry_price <= 0:
                # 从 Tiger 获取实时价格
                try:
                    quote_data = await tiger.get_stock_quote(ticker) if hasattr(tiger, 'get_stock_quote') else {}
                    entry_price = (quote_data or {}).get("latest_price", 0)
                except Exception:
                    pass
            if entry_price > 0:
                qty = await calculate_position_size(tiger, entry_price, max_positions=RC.TOP_N, equity_fraction=_v4_fraction)
        except Exception as e:
            logger.warning(f"[RESUBMIT] qty recalc failed for {ticker}: {e}")

        if qty and qty > 0:
            try:
                new_result = await tiger.place_buy_order(ticker, qty, order_type="MKT")
                if new_result and new_result.get("order_id"):
                    new_id = str(new_result["order_id"])
                    db.table("rotation_positions").update({
                        "tiger_order_id": new_id,
                        "tiger_order_status": "submitted",
                    }).eq("id", pos_id).execute()
                    results.append({"ticker": ticker, "action": "resubmitted", "msg": f"🔄 已重新下市价单 (新ID: {new_id[:8]}...)"})
                else:
                    results.append({"ticker": ticker, "action": "failed", "msg": "❌ 下单未返回订单ID"})
            except Exception as e:
                results.append({"ticker": ticker, "action": "failed", "msg": f"❌ 下单失败: {e}"})
        else:
            results.append({"ticker": ticker, "action": "skipped", "msg": "⚠️ 数量为0，跳过"})

    rows_html = ""
    for r in results:
        color = "text-sq-green" if r["action"] in ("synced", "resubmitted") else "text-sq-red" if r["action"] == "failed" else "text-gray-400"
        rows_html += (
            f'<div class="flex items-center gap-2 py-1.5 text-xs">'
            f'<span class="font-mono font-bold text-white">{r["ticker"]}</span>'
            f'<span class="{color}">{r["msg"]}</span></div>'
        )

    html = (
        f'<div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-2">'
        f'<div class="text-sm font-bold text-white mb-2">🔄 重提未成交订单结果</div>'
        f'<div class="divide-y divide-gray-800">{rows_html}</div></div>'
    )
    return HTMLResponse(content=html, headers={"HX-Trigger": "refreshPositions"})


@router.post("/api/tiger/sync-orders", response_class=HTMLResponse)
async def api_tiger_sync_orders(request: Request):
    """
    手动触发：同步 Tiger 实际成交价到 DB，更新止损/止盈。
    响应头带 HX-Trigger 通知前端刷新持仓列表。
    """
    from app.services.order_service import sync_tiger_orders
    try:
        await sync_tiger_orders()
        html = (
            '<div class="bg-green-900/30 border border-green-700 rounded-lg p-3 text-sm">'
            '<span class="text-green-400 font-bold">✅ Tiger成交价同步完成</span>'
            '<p class="text-gray-400 mt-1 text-xs">持仓状态已更新</p></div>'
        )
        return HTMLResponse(content=html, headers={"HX-Trigger": "refreshPositions"})
    except Exception as e:
        logger.error(f"[SYNC-ORDERS] 手动同步失败: {e}", exc_info=True)
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 同步失败</span>'
            f'<p class="text-gray-400 mt-1 text-xs">{e}</p></div>'
        )


@router.post("/api/tiger/reconcile-exits", response_class=HTMLResponse)
async def api_tiger_reconcile_exits(request: Request):
    """
    Tiger 对账（两步）：
    1. sync_tiger_orders — 检测 Tiger 已卖出但 DB 仍 active 的仓位，标记 closed
    2. reconcile_exit_prices — 从 Tiger filled SELL orders 补全 exit_price
    """
    from app.services.order_service import sync_tiger_orders, reconcile_exit_prices
    try:
        # Step 1: 同步持仓状态（关闭 Tiger 已卖出的仓位）
        sync_stats = await sync_tiger_orders()
        sync_closed = sync_stats.get("closed", 0)

        # Step 2: 修正 exit_price
        stats = await reconcile_exit_prices(lookback_days=60)
        details_html = ""
        if sync_closed > 0:
            details_html += f'<div class="text-xs text-green-300 py-0.5">• 检测到 {sync_closed} 笔 Tiger 已卖出，已关闭</div>'
        for d in stats.get("details", []):
            details_html += f'<div class="text-xs text-gray-300 py-0.5">• {d}</div>'

        if sync_closed > 0 or stats["updated"] > 0:
            parts = []
            if sync_closed > 0:
                parts.append(f"{sync_closed} 笔持仓已关闭")
            if stats["updated"] > 0:
                parts.append(f"{stats['updated']} 笔 exit_price 已修正")
            html = (
                f'<div class="bg-green-900/30 border border-green-700 rounded-lg p-3 text-sm">'
                f'<span class="text-green-400 font-bold">✅ 对账完成：{"，".join(parts)}</span>'
                f'<p class="text-gray-400 mt-1 text-xs">检查 {stats["checked"]} 笔 | 无匹配 {stats["no_match"]} 笔</p>'
                f'<div class="mt-2">{details_html}</div></div>'
            )
        else:
            html = (
                f'<div class="bg-gray-800 rounded-lg p-3 text-sm">'
                f'<span class="text-gray-400">无需修正（检查 {stats["checked"]} 笔，无匹配 {stats["no_match"]} 笔）</span></div>'
            )
        return HTMLResponse(content=html, headers={"HX-Trigger": "refreshPositions, refreshTrades"})
    except Exception as e:
        logger.error(f"[RECONCILE-EXIT] 对账失败: {e}", exc_info=True)
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 对账失败</span>'
            f'<p class="text-gray-400 mt-1 text-xs">{e}</p></div>'
        )


@router.get("/api/tiger/transactions", response_class=JSONResponse)
async def api_tiger_transactions(request: Request, days: int = 60):
    """调试端点：查看 Tiger 的全部交易执行记录"""
    from app.services.order_service import get_tiger_trade_client
    from datetime import timedelta
    client = get_tiger_trade_client()
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        txns = await client.get_transactions(since_date=start, to_date=end)
        filled = await client.get_filled_orders(start_date=start, end_date=end)
        return JSONResponse({
            "transactions": txns,
            "filled_orders": filled,
            "query": {"start": start, "end": end, "days": days},
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/positions/recalculate-sl-tp", response_class=HTMLResponse)
async def api_recalculate_sl_tp(request: Request):
    """
    一键按当前 regime 重算所有活跃持仓的 SL/TP。
    只处理有 entry_price + atr14 的持仓，跳过无 ATR 数据的记录。
    """
    from app.services.rotation_service import get_current_positions, _detect_regime
    from app.config.rotation_watchlist import RotationConfig as RC
    try:
        regime = await _detect_regime()
        stop_mult = RC.ATR_STOP_BY_REGIME.get(regime, RC.ATR_STOP_MULTIPLIER)
        target_mult = RC.ATR_TARGET_BY_REGIME.get(regime, RC.ATR_TARGET_MULTIPLIER)

        all_pos = await get_current_positions() or []
        active = [p for p in all_pos if p.get("status") in ("active", "pending_exit")]

        updated, skipped = [], []
        from app.database import get_db
        db = get_db()
        for pos in active:
            entry = float(pos.get("entry_price") or 0)
            atr14 = float(pos.get("atr14") or 0)
            if entry <= 0 or atr14 <= 0:
                skipped.append(pos.get("ticker", "?"))
                continue
            new_sl = round(entry - stop_mult * atr14, 2)
            new_tp = round(entry + target_mult * atr14, 2)
            db.table("rotation_positions").update({
                "stop_loss": new_sl,
                "take_profit": new_tp,
            }).eq("id", pos["id"]).execute()
            updated.append(f"{pos['ticker']} SL={new_sl} TP={new_tp}")

        regime_label = {"strong_bull": "强牛", "bull": "牛市", "choppy": "震荡", "bear": "熊市"}.get(regime, regime)
        skip_note = f"，跳过 {len(skipped)} 个无ATR数据 ({', '.join(skipped)})" if skipped else ""
        detail = "<br>".join(updated) if updated else "无持仓需更新"
        html = (
            f'<div class="bg-green-900/30 border border-green-700 rounded-lg p-3 text-sm">'
            f'<span class="text-green-400 font-bold">✅ SL/TP重算完成</span>'
            f'<p class="text-gray-400 mt-1 text-xs">当前Regime: <span class="text-cyan-300">{regime_label}</span>'
            f' | 止损{stop_mult}x / 止盈{target_mult}x | 更新{len(updated)}个持仓{skip_note}</p>'
            f'<p class="text-gray-500 mt-1 text-[11px] font-mono">{detail}</p></div>'
        )
        return HTMLResponse(content=html, headers={"HX-Trigger": "refreshPositions"})
    except Exception as e:
        logger.error(f"[RECALC-SL-TP] 失败: {e}", exc_info=True)
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 重算失败</span>'
            f'<p class="text-gray-400 mt-1 text-xs">{e}</p></div>'
        )


@router.get("/htmx/signals", response_class=HTMLResponse)
async def htmx_signals(request: Request):
    """信号列表（HTMX局部）"""
    try:
        from app.services.db_service import SignalService
        signals = await SignalService.get_observe_signals()
        signal_dicts = []
        for sig in (signals or []):
            if hasattr(sig, "model_dump"):
                signal_dicts.append(sig.model_dump())
            elif hasattr(sig, "dict"):
                signal_dicts.append(sig.dict())
            elif isinstance(sig, dict):
                signal_dicts.append(sig)
        return _tpl("partials/_signals.html", {
            "request": request,
            "signals": signal_dicts,
        })
    except Exception as e:
        logger.error(f"Signals error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


@router.get("/htmx/risk-badge", response_class=HTMLResponse)
async def htmx_risk_badge(request: Request):
    """风险状态徽章（HTMX局部，每60秒刷新）"""
    try:
        from app.services.risk_service import RiskEngine
        risk = await RiskEngine().get_current_risk_summary()
        return _tpl("partials/_risk_badge.html", {
            "request": request,
            "risk": risk,
        })
    except Exception as e:
        logger.error(f"Risk badge error: {e}")
        return _tpl("partials/_risk_badge.html", {
            "request": request,
            "risk": {},
        })


@router.get("/htmx/c5-sentiment", response_class=HTMLResponse)
async def htmx_c5_sentiment(request: Request):
    """C5 散户情绪面板（HTMX局部，每5分钟刷新）"""
    data = None
    try:
        from app.database import get_db
        db = get_db()
        res = db.table("retail_sentiment_regime") \
            .select("date,pc_ratio,pc_signal,wsb_meme_tickers,meme_mode,meme_intensity,rationale") \
            .order("date", desc=True).limit(1).execute()
        if res.data:
            row = res.data[0]
            data = {
                "date": row.get("date"),
                "pc_ratio": row.get("pc_ratio"),
                "pc_signal": row.get("pc_signal", "unavailable"),
                "wsb_meme_tickers": row.get("wsb_meme_tickers") or [],
                "wsb_meme_count": len(row.get("wsb_meme_tickers") or []),
                "meme_mode": row.get("meme_mode", False),
                "meme_intensity": row.get("meme_intensity", "unavailable"),
                "rationale": row.get("rationale", ""),
            }
    except Exception as e:
        logger.warning(f"C5 sentiment panel error: {e}")
    return _tpl("partials/_c5_sentiment.html", {"request": request, "data": data})


@router.get("/htmx/meme-badge", response_class=HTMLResponse)
async def htmx_meme_badge(request: Request):
    """C5 散户炒作模式指示器（HTMX局部，每60秒刷新）"""
    try:
        from app.services.retail_sentiment_service import get_today_meme_mode
        meme_mode, _ = await get_today_meme_mode()
    except Exception:
        meme_mode = False
    return _tpl("partials/_meme_badge.html", {"request": request, "meme_mode": meme_mode})


@router.get("/htmx/live-oos", response_class=HTMLResponse)
async def htmx_live_oos(request: Request):
    """2026 Live OOS 追踪面板（HTMX局部，每10分钟刷新）"""
    data = None
    try:
        from app.database import get_db
        db = get_db()
        res = db.table("live_oos_tracking") \
            .select("run_date,oos_start,oos_end,strategy,ytd_return,sharpe,max_drawdown,trading_days,spy_return,params") \
            .eq("strategy", "v4mr") \
            .order("run_date", desc=True).limit(1).execute()
        if res.data:
            row = res.data[0]
            data = {
                "run_date":     row.get("run_date"),
                "oos_start":    row.get("oos_start", "2026-01-02"),
                "oos_end":      row.get("oos_end"),
                "ytd_return":   row.get("ytd_return", 0.0),
                "sharpe":       row.get("sharpe", 0.0),
                "max_drawdown": row.get("max_drawdown", 0.0),
                "trading_days": row.get("trading_days", 0),
                "spy_return":   row.get("spy_return"),
                "params":       row.get("params") or {},
            }
    except Exception as e:
        logger.warning(f"Live OOS panel error: {e}")
    return _tpl("partials/_live_oos.html", {"request": request, "data": data})


@router.get("/htmx/knowledge-list", response_class=HTMLResponse)
async def htmx_knowledge_list(request: Request):
    """最近知识条目（HTMX局部）"""
    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()
        recent = await ks.get_recent(limit=20)
        return _tpl("partials/_knowledge_list.html", {
            "request": request,
            "entries": recent or [],
            "flash": None,
        })
    except Exception as e:
        logger.error(f"Knowledge list error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


@router.get("/htmx/knowledge-search", response_class=HTMLResponse)
async def htmx_knowledge_search(
    request: Request,
    query: str = Query(""),
    search_ticker: str = Query("", alias="search-ticker"),
    search_category: str = Query("", alias="search-category"),
):
    """实时语义搜索（HTMX局部，500ms防抖）"""
    if not query.strip():
        return HTMLResponse("")

    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()

        tickers = [search_ticker.strip().upper()] if search_ticker.strip() else None
        category = search_category.strip() or None

        results = await ks.search(
            query=query.strip(),
            top_k=10,
            category=category,
            tickers=tickers,
        )

        return _tpl("partials/_search_results.html", {
            "request": request,
            "results": results or [],
            "query": query.strip(),
        })

    except Exception as e:
        logger.error(f"Knowledge search error: {e}")
        return HTMLResponse(f'<div class="text-sq-red text-sm">搜索出错: {e}</div>')


@router.get("/htmx/knowledge-stats", response_class=HTMLResponse)
async def htmx_knowledge_stats(request: Request):
    """知识库统计（HTMX局部）"""
    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()
        stats = await ks.get_stats()
        stats_dict = stats.dict() if hasattr(stats, "dict") else stats.model_dump()
        return _tpl("partials/_knowledge_stats.html", {
            "request": request,
            "stats": stats_dict,
        })
    except Exception as e:
        logger.error(f"Knowledge stats error: {e}")
        return HTMLResponse('<div class="text-sq-red text-sm">统计加载失败</div>')


@router.post("/htmx/feed-text", response_class=HTMLResponse)
async def htmx_feed_text(request: Request):
    """投喂文本（表单提交，返回更新后的条目列表）"""
    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()

        form = await request.form()
        content = form.get("content", "").strip()
        category = form.get("category", "").strip() or None
        tickers_raw = form.get("tickers", "").strip()
        tags_raw = form.get("tags", "").strip()

        tickers = [t.strip().upper() for t in tickers_raw.split(",") if t.strip()] or None
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] or None

        if not content:
            recent = await ks.get_recent(limit=20)
            return _tpl("partials/_knowledge_list.html", {
                "request": request,
                "entries": recent or [],
                "flash": "内容不能为空",
            })

        entry = await ks.add_knowledge(
            content=content,
            source_type="user_feed_text",
            category=category,
            tickers=tickers,
            tags=tags,
        )

        recent = await ks.get_recent(limit=20)
        flash = "投喂成功！已向量化入库" if entry else "投喂失败，请重试"

        return _tpl("partials/_knowledge_list.html", {
            "request": request,
            "entries": recent or [],
            "flash": flash,
        })

    except Exception as e:
        logger.error(f"Feed text error: {e}")
        return HTMLResponse(f'<div class="text-sq-red text-sm py-2">投喂失败: {e}</div>')


@router.post("/htmx/feed-url", response_class=HTMLResponse)
async def htmx_feed_url(request: Request):
    """投喂URL（表单提交，返回更新后的条目列表）"""
    try:
        from app.services.knowledge_service import get_knowledge_service
        ks = get_knowledge_service()

        form = await request.form()
        url = form.get("url", "").strip()
        category = form.get("category", "").strip() or None
        tickers_raw = form.get("tickers", "").strip()
        tags_raw = form.get("tags", "").strip()

        tickers = [t.strip().upper() for t in tickers_raw.split(",") if t.strip()] or None
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] or None

        if not url:
            recent = await ks.get_recent(limit=20)
            return _tpl("partials/_knowledge_list.html", {
                "request": request,
                "entries": recent or [],
                "flash": "URL不能为空",
            })

        entry = await ks.add_from_url(
            url=url,
            category=category,
            tickers=tickers,
            tags=tags,
        )

        recent = await ks.get_recent(limit=20)
        flash = "URL内容已抓取并入库！" if entry else "URL抓取失败，请检查链接"

        return _tpl("partials/_knowledge_list.html", {
            "request": request,
            "entries": recent or [],
            "flash": flash,
        })

    except Exception as e:
        logger.error(f"Feed URL error: {e}")
        return HTMLResponse(f'<div class="text-sq-red text-sm py-2">URL投喂失败: {e}</div>')


# ==================== BACKTEST PAGE ====================

@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    """策略回测 — 轻量页面加载，数据按需通过API获取"""
    return _tpl("backtest.html", {"request": request})


_APP_BOOT_TS = time.time()


def _get_system_status_snapshot() -> dict:
    now_ts = time.time()
    return {
        "warmup_left_seconds": 0,
        "backtest": {
            "active": False,
            "job_id": None,
            "phase": "idle",
            "elapsed_seconds": 0.0,
            "timeout_seconds": 0,
        },
        "jobs_in_memory": 0,
    }


@router.get("/api/system/status", response_class=JSONResponse)
async def api_system_status():
    """Runtime diagnostics for dashboard health panel."""
    data = _get_system_status_snapshot()
    return JSONResponse({"status": "ok", "data": data})


@router.get("/htmx/system-status", response_class=HTMLResponse)
async def htmx_system_status(request: Request):
    data = _get_system_status_snapshot()
    return _tpl("partials/_system_status.html", {"request": request, "data": data})


@router.get("/api/walk-forward")
async def api_walk_forward():
    """
    Walk-Forward 验证结果 — 读取预计算的 JSON 文件（V5, 500股票, 40窗口）。
    """
    import pathlib
    json_path = pathlib.Path("site/data/walk-forward-validation.json")
    if not json_path.exists():
        return JSONResponse({"error": "Walk-Forward 验证数据尚未生成"}, status_code=404)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return JSONResponse(data)


# ==================== WEEKLY REPORT ====================

@router.get("/htmx/weekly-report", response_class=HTMLResponse)
async def htmx_weekly_report(request: Request):
    """生成本周调仓建议周报"""
    try:
        from app.services.rotation_service import (
            run_rotation, get_current_positions,
            _fetch_history, _compute_ma, _compute_atr, RC,
        )
        from app.config.rotation_watchlist import get_ticker_info
        import numpy as np

        result = await run_rotation(trigger_source="weekly_report")
        if not result or "error" in result:
            return HTMLResponse('<div class="text-sq-red py-4">无法生成周报，请检查系统状态</div>')

        regime = result.get("regime", "unknown")
        selected = result.get("selected", [])
        scores_top = result.get("scores_top10", [])

        # Current positions
        positions = await get_current_positions()
        current_holdings = [p.get("ticker") for p in positions] if positions else []

        # Compute changes
        added = [t for t in selected if t not in current_holdings]
        removed = [t for t in current_holdings if t not in selected]
        kept = [t for t in selected if t in current_holdings]

        # Build report HTML
        regime_colors = {
            "strong_bull": ("STRONG_BULL 强牛", "text-sq-green", "bg-green-900/50"),
            "bull": ("BULL 牛市", "text-green-400", "bg-green-900/30"),
            "choppy": ("CHOPPY 震荡", "text-sq-gold", "bg-yellow-900/30"),
            "bear": ("BEAR 熊市", "text-sq-red", "bg-red-900/50"),
        }
        r_label, r_color, r_bg = regime_colors.get(regime, ("UNKNOWN", "text-gray-400", "bg-gray-700"))

        html = f'''
        <div class="bg-sq-card rounded-xl border border-sq-accent/30 p-6 space-y-5">
            <div class="flex items-center justify-between">
                <h3 class="text-white font-bold text-lg flex items-center gap-2">
                    <svg class="w-5 h-5 text-sq-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                    </svg>
                    本周调仓建议
                </h3>
                <span class="text-xs {r_color} {r_bg} px-3 py-1 rounded-full font-semibold">{r_label}</span>
            </div>

            <div class="grid grid-cols-3 gap-4 text-center">
                <div class="bg-sq-bg rounded-lg p-3">
                    <div class="text-xs text-gray-500 mb-1">建议持仓</div>
                    <div class="text-lg font-bold text-white">{len(selected)} 只</div>
                </div>
                <div class="bg-sq-bg rounded-lg p-3">
                    <div class="text-xs text-gray-500 mb-1">本周买入</div>
                    <div class="text-lg font-bold text-sq-green">{len(added)} 只</div>
                </div>
                <div class="bg-sq-bg rounded-lg p-3">
                    <div class="text-xs text-gray-500 mb-1">本周卖出</div>
                    <div class="text-lg font-bold text-sq-red">{len(removed)} 只</div>
                </div>
            </div>
        '''

        # Compute entry/stop/target for all selected tickers (regime-aware)
        _stop_mult = RC.ATR_STOP_BY_REGIME.get(regime, RC.ATR_STOP_MULTIPLIER)
        _target_mult = RC.ATR_TARGET_BY_REGIME.get(regime, RC.ATR_TARGET_MULTIPLIER)
        price_targets = {}
        import asyncio as _aio
        _hist_tasks = [_fetch_history(t, days=30) for t in selected]
        _hist_results = await _aio.gather(*_hist_tasks, return_exceptions=True) if _hist_tasks else []
        for t, data in zip(selected, _hist_results):
            try:
                if isinstance(data, Exception) or not data:
                    continue
                if len(data["close"]) < 20:
                    continue
                closes = data["close"]
                price = float(closes[-1])
                atr = _compute_atr(data["high"], data["low"], closes)
                ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
                avg_vol = float(np.mean(data["volume"][-RC.ENTRY_VOL_PERIOD:])) if len(data["volume"]) >= RC.ENTRY_VOL_PERIOD else 0
                cur_vol = float(data["volume"][-1])
                stop = round(price - _stop_mult * atr, 2)
                target = round(price + _target_mult * atr, 2)
                above_ma = price > ma5
                vol_ok = cur_vol > avg_vol if avg_vol > 0 else False
                price_targets[t] = {
                    "price": price, "stop": stop, "target": target,
                    "stop_pct": round((stop / price - 1) * 100, 1),
                    "target_pct": round((target / price - 1) * 100, 1),
                    "entry_ok": above_ma and vol_ok,
                }
            except Exception:
                pass

        if added:
            html += '<div class="space-y-2"><div class="text-xs text-sq-green font-semibold mb-2">🟢 买入</div>'
            for t in added:
                info = get_ticker_info(t)
                name = info.get("name", "") if info else ""
                pt = price_targets.get(t, {})
                entry_badge = '<span class="text-[10px] bg-green-900/60 text-green-300 px-1 rounded">可入场</span>' if pt.get("entry_ok") else '<span class="text-[10px] bg-yellow-900/60 text-yellow-300 px-1 rounded">等确认</span>'
                price_html = ""
                if pt:
                    price_html = (
                        f'<div class="flex gap-4 text-xs mt-1">'
                        f'<span class="text-gray-400">入场 <span class="text-white font-mono">${pt["price"]:.2f}</span></span>'
                        f'<span class="text-sq-red">止损 <span class="font-mono">${pt["stop"]:.2f}</span> ({pt["stop_pct"]:+.1f}%)</span>'
                        f'<span class="text-sq-green">止盈 <span class="font-mono">${pt["target"]:.2f}</span> ({pt["target_pct"]:+.1f}%)</span>'
                        f'</div>'
                    )
                html += (
                    f'<div class="bg-green-900/20 rounded-lg p-3 border border-green-800/30">'
                    f'<div class="flex items-center gap-2 text-sm">'
                    f'<span class="text-sq-green font-mono font-bold">{t}</span>'
                    f'<span class="text-gray-400 text-xs">{name}</span>'
                    f'{entry_badge}'
                    f'</div>'
                    f'{price_html}'
                    f'</div>'
                )
            html += '</div>'

        if removed:
            html += '<div class="space-y-2"><div class="text-xs text-sq-red font-semibold mb-2">🔴 卖出</div>'
            for t in removed:
                info = get_ticker_info(t)
                name = info.get("name", "") if info else ""
                html += f'<div class="bg-red-900/20 rounded-lg p-3 border border-red-800/30"><div class="flex items-center gap-2 text-sm"><span class="text-sq-red font-mono font-bold">{t}</span><span class="text-gray-400 text-xs">{name}</span></div></div>'
            html += '</div>'

        if kept:
            html += '<div class="space-y-2"><div class="text-xs text-gray-400 font-semibold mb-2">⚪ 继续持有</div>'
            for t in kept:
                pt = price_targets.get(t, {})
                price_html = ""
                if pt:
                    price_html = (
                        f'<div class="flex gap-4 text-xs mt-1">'
                        f'<span class="text-gray-400">现价 <span class="text-white font-mono">${pt["price"]:.2f}</span></span>'
                        f'<span class="text-sq-red">止损 <span class="font-mono">${pt["stop"]:.2f}</span></span>'
                        f'<span class="text-sq-green">止盈 <span class="font-mono">${pt["target"]:.2f}</span></span>'
                        f'</div>'
                    )
                html += (
                    f'<div class="bg-sq-bg rounded-lg p-3 border border-sq-border/30">'
                    f'<div class="flex items-center gap-2 text-sm">'
                    f'<span class="text-gray-300 font-mono font-bold">{t}</span>'
                    f'</div>'
                    f'{price_html}'
                    f'</div>'
                )
            html += '</div>'

        # Top 10 scores
        if scores_top:
            html += '<div class="border-t border-sq-border/50 pt-4"><div class="text-xs text-gray-400 font-semibold mb-2">📊 本周评分排行 Top 10</div>'
            html += '<div class="overflow-x-auto"><table class="w-full text-xs"><thead><tr class="text-gray-500 border-b border-sq-border">'
            html += '<th class="py-1 text-left">排名</th><th class="text-left">股票</th><th class="text-right">评分</th><th class="text-right">1周</th><th class="text-right">1月</th><th class="text-center">MA20</th></tr></thead><tbody>'
            for i, s in enumerate(scores_top[:10], 1):
                ticker = s.get("ticker", "")
                score = s.get("score", 0)
                r1w = s.get("return_1w", 0)
                r1m = s.get("return_1m", 0)
                ma = "✅" if s.get("above_ma20") else "❌"
                in_sel = "font-semibold text-sq-gold" if ticker in selected else "text-gray-300"
                html += f'<tr class="border-b border-sq-border/30 {in_sel}"><td class="py-1.5">{i}</td><td class="font-mono">{ticker}</td><td class="text-right">{score:+.2f}</td><td class="text-right {"text-sq-green" if r1w > 0 else "text-sq-red"}">{r1w:+.1%}</td><td class="text-right {"text-sq-green" if r1m > 0 else "text-sq-red"}">{r1m:+.1%}</td><td class="text-center">{ma}</td></tr>'
            html += '</tbody></table></div></div>'

        # Push to Feishu button
        html += '''
            <div class="border-t border-sq-border/50 pt-4 flex items-center gap-3">
                <button hx-post="/htmx/weekly-report-push"
                        hx-swap="outerHTML"
                        class="bg-sq-blue/80 hover:bg-sq-blue text-white text-xs px-4 py-2 rounded-lg transition-colors flex items-center gap-1">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                    </svg>
                    推送到飞书
                </button>
                <span class="text-xs text-gray-500">将本周调仓建议发送到飞书群</span>
            </div>
        '''

        html += '</div>'
        return HTMLResponse(html)

    except Exception as e:
        logger.error(f"Weekly report error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return HTMLResponse(f'<div class="text-sq-red py-4">生成周报失败: {e}</div>')


@router.post("/htmx/weekly-report-push", response_class=HTMLResponse)
async def htmx_weekly_report_push(request: Request):
    """推送周报到飞书"""
    try:
        from app.services.rotation_service import run_rotation
        from app.services.notification_service import notify_rotation_summary

        result = await run_rotation(trigger_source="weekly_report_push")
        if result and "error" not in result:
            success = await notify_rotation_summary(result)
            if success:
                return HTMLResponse(
                    '<span class="text-sq-green text-xs flex items-center gap-1">'
                    '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>'
                    '已推送到飞书 ✓</span>'
                )
        return HTMLResponse('<span class="text-sq-red text-xs">推送失败，请检查飞书配置</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="text-sq-red text-xs">推送失败: {e}</span>')


# ==================== KNOWLEDGE COLLECTION ====================

@router.post("/htmx/knowledge-collect-all", response_class=HTMLResponse)
async def htmx_knowledge_collect_all(request: Request):
    """一键触发所有知识收集器"""
    try:
        from app.services.knowledge_collectors import run_all_collectors
        results = await run_all_collectors()

        # Format results as HTML
        html_parts = ['<div class="space-y-2 mt-3">']
        html_parts.append('<h3 class="text-sm font-semibold text-sq-green mb-2">采集完成</h3>')

        if isinstance(results, dict):
            for name, detail in results.items():
                status = "text-sq-green" if detail else "text-gray-400"
                count = ""
                if isinstance(detail, dict):
                    count = f" — 新增 {detail.get('added', detail.get('count', '?'))} 条"
                elif isinstance(detail, (int, float)):
                    count = f" — {detail} 条"
                html_parts.append(
                    f'<div class="flex items-center gap-2 text-xs">'
                    f'<span class="w-2 h-2 rounded-full bg-sq-green inline-block"></span>'
                    f'<span class="{status}">{name}{count}</span></div>'
                )
        elif isinstance(results, list):
            for r in results:
                html_parts.append(f'<div class="text-xs text-gray-300">{r}</div>')
        else:
            html_parts.append(f'<div class="text-xs text-gray-300">{results}</div>')

        html_parts.append('</div>')
        return HTMLResponse("\n".join(html_parts))

    except Exception as e:
        logger.error(f"Knowledge collect error: {e}")
        return HTMLResponse(f'<div class="text-sq-red text-sm mt-2">采集失败: {e}</div>')


# ==================== SCHEDULER ====================

@router.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request):
    """调度器活动 — 独立页面，显示所有定时任务的详细信息"""
    try:
        from app.scheduler import get_scheduler_logs
        jobs = get_scheduler_logs(limit=100)
    except Exception as e:
        logger.error(f"Scheduler page error: {e}")
        jobs = []

    return _tpl("scheduler.html", {
        "request": request,
        "jobs": jobs,
    })


@router.get("/htmx/scheduler-logs", response_class=HTMLResponse)
async def htmx_scheduler_logs(request: Request):
    """调度器活动日志（HTMX局部，仪表盘用，每60秒刷新）"""
    try:
        from app.scheduler import get_scheduler_logs
        logs = get_scheduler_logs(limit=30)
        return _tpl("partials/_scheduler_logs.html", {
            "request": request,
            "logs": logs,
        })
    except Exception as e:
        logger.error(f"Scheduler logs error: {e}")
        return HTMLResponse(f'<div class="text-gray-500 text-sm text-center py-4">日志加载失败: {e}</div>')



@router.get("/htmx/scheduler-logs-full", response_class=HTMLResponse)
async def htmx_scheduler_logs_full(request: Request):
    """调度器活动日志（HTMX局部，独立页面用，详细版）"""
    try:
        from app.scheduler import get_scheduler_logs
        logs = get_scheduler_logs(limit=100)
        return _tpl("partials/_scheduler_logs_full.html", {
            "request": request,
            "logs": logs,
        })
    except Exception as e:
        logger.error(f"Scheduler logs error: {e}")
        return HTMLResponse(f'<div class="text-gray-500 text-sm text-center py-4">日志加载失败: {e}</div>')


@router.get("/htmx/scheduler-runs", response_class=HTMLResponse)
async def htmx_scheduler_runs(request: Request):
    """Job 执行历史（每 job 最新一条，HTMX 局部）"""
    try:
        from app.scheduler import get_scheduler_runs
        runs = get_scheduler_runs(limit=200)
        return _tpl("partials/_scheduler_runs.html", {
            "request": request,
            "runs": runs,
        })
    except Exception as e:
        logger.error(f"Scheduler runs error: {e}")
        return HTMLResponse(f'<div class="text-gray-500 text-sm text-center py-4">执行记录加载失败: {e}</div>')


# ==================================================================
# Trade History Page (历史交易)
# ==================================================================

@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request):
    """历史交易 — 显示已成交持仓、挂盘中订单、已平仓交易"""
    trades = []
    filled_positions = []   # tiger_order_status=filled, status=active/pending_exit
    pending_orders = []     # tiger_order_status=submitted, status=active
    summary = {"total_trades": 0, "win_rate": 0, "avg_return": 0, "avg_hold_days": 0}

    try:
        from app.database import get_db
        from datetime import datetime, date
        db = get_db()

        # ---- 已平仓交易（只保留真实成交、exit_price > 0 的记录） ----
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", "closed")
            .gt("exit_price", 0)
            .order("exit_date", desc=True)
            .execute()
        )
        closed = result.data or []

        total_return = 0.0
        wins = 0
        total_hold_days = 0

        for p in closed:
            entry_price = float(p.get("entry_price") or 0)
            exit_price = float(p.get("exit_price") or 0)
            return_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price > 0 and exit_price > 0 else 0

            hold_days = 0
            entry_date = p.get("entry_date", "")
            exit_date = p.get("exit_date", "")
            if entry_date and exit_date:
                try:
                    d1 = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d")
                    d2 = datetime.strptime(str(exit_date)[:10], "%Y-%m-%d")
                    hold_days = (d2 - d1).days
                except Exception:
                    pass

            total_return += return_pct
            if return_pct > 0:
                wins += 1
            total_hold_days += hold_days

            trades.append({
                "ticker": p.get("ticker", ""),
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "return_pct": return_pct,
                "entry_date": str(entry_date)[:10] if entry_date else "",
                "exit_date": str(exit_date)[:10] if exit_date else "",
                "hold_days": hold_days,
                "exit_reason": p.get("exit_reason", ""),
            })

        total = len(trades)
        summary = {
            "total_trades": total,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "avg_return": round(total_return / total, 2) if total > 0 else 0,
            "avg_hold_days": round(total_hold_days / total, 1) if total > 0 else 0,
        }

        # ---- 活跃持仓 (filled + submitted) — 用统一函数，Tiger数据已内置overlay ----
        from app.services.order_service import get_active_positions
        active_positions = await get_active_positions()
        # Also include pending_exit from DB (not returned by get_active_positions which filters status=active)
        pending_exit_result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", "pending_exit")
            .order("created_at", desc=True)
            .execute()
        )
        all_active = active_positions + (pending_exit_result.data or [])

        today = date.today()
        for p in all_active:
            ticker = p.get("ticker", "")
            entry_price = float(p.get("entry_price") or 0)
            current_price = float(p.get("current_price") or 0)
            pnl_pct = round(float(p.get("unrealized_pnl_pct") or 0) * 100, 3)
            if pnl_pct == 0 and entry_price > 0 and current_price > 0:
                pnl_pct = round((current_price - entry_price) / entry_price * 100, 3)

            hold_days = 0
            entry_date = p.get("entry_date", "")
            if entry_date:
                try:
                    d1 = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d").date()
                    hold_days = (today - d1).days
                except Exception:
                    pass

            pos_data = {
                "ticker": ticker,
                "entry_price": round(entry_price, 2),
                "current_price": round(current_price, 2),
                "pnl_pct": pnl_pct,
                "quantity": p.get("quantity") or 0,
                "stop_loss": round(float(p.get("stop_loss") or 0), 2),
                "take_profit": round(float(p.get("take_profit") or 0), 2),
                "entry_date": str(entry_date)[:10] if entry_date else "",
                "hold_days": hold_days,
                "status": p.get("status", ""),
                "tiger_order_status": p.get("tiger_order_status", ""),
            }

            tiger_status = p.get("tiger_order_status", "")
            if tiger_status == "filled":
                filled_positions.append(pos_data)
            elif tiger_status == "submitted":
                pending_orders.append(pos_data)
            else:
                if entry_price > 0:
                    filled_positions.append(pos_data)

    except Exception as e:
        logger.error(f"Trades page error: {e}")

    return _tpl("trades.html", {
        "request": request,
        "trades": trades,
        "summary": summary,
        "filled_positions": filled_positions,
        "pending_orders": pending_orders,
    })


@router.get("/htmx/trade-history", response_class=HTMLResponse)
async def htmx_trade_history(request: Request):
    """HTMX endpoint: 返回交易历史表格 partial"""
    trades = []
    try:
        from app.database import get_db
        from datetime import datetime
        db = get_db()
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", "closed")
            .gt("exit_price", 0)
            .order("exit_date", desc=True)
            .execute()
        )
        closed = result.data or []

        for p in closed:
            entry_price = float(p.get("entry_price") or 0)
            exit_price = float(p.get("exit_price") or 0)
            return_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price > 0 and exit_price > 0 else 0

            hold_days = 0
            entry_date = p.get("entry_date", "")
            exit_date = p.get("exit_date", "")
            if entry_date and exit_date:
                try:
                    d1 = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d")
                    d2 = datetime.strptime(str(exit_date)[:10], "%Y-%m-%d")
                    hold_days = (d2 - d1).days
                except Exception:
                    pass

            trades.append({
                "ticker": p.get("ticker", ""),
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "return_pct": return_pct,
                "entry_date": str(entry_date)[:10] if entry_date else "",
                "exit_date": str(exit_date)[:10] if exit_date else "",
                "hold_days": hold_days,
                "exit_reason": p.get("exit_reason", ""),
            })
    except Exception as e:
        logger.error(f"HTMX trade-history error: {e}")
        return HTMLResponse('<tr><td colspan="7" class="text-center text-sq-red py-4">加载失败</td></tr>')

    return _tpl("partials/_trade_history.html", {
        "request": request,
        "trades": trades,
    })


# ==================================================================
# Strategy Parameters Page (策略锁定)
# ==================================================================

@router.get("/strategy", response_class=HTMLResponse)
async def strategy_page(request: Request):
    """策略锁定 — 显示 V5 Luohan (五百罗汉) Walk-Forward 验证后的锁定参数"""
    strategy_data = {}
    try:
        config_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
            "app", "config", "luohan.json"
        )
        with open(config_path, "r", encoding="utf-8") as f:
            strategy_data = json.load(f)
    except Exception as e:
        logger.error(f"Strategy page error loading config: {e}")

    return _tpl("strategy.html", {
        "request": request,
        "strategy": strategy_data,
    })


@router.get("/changelog", response_class=HTMLResponse)
async def changelog_page(request: Request):
    """更新日志页面"""
    changelog = {"entries": []}
    try:
        changelog_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
            "site", "data", "changelog.json"
        )
        with open(changelog_path, "r", encoding="utf-8") as f:
            changelog = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load changelog: {e}")

    return _tpl("changelog.html", {
        "request": request,
        "changelog": changelog,
    })


# ==================================================================
# Public API — for stockqueen.co (real-time signals + prices)
# ==================================================================

@router.get("/api/public/signals", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_signals(request: Request):
    """公开API：返回当前活跃持仓 + Tiger实时行情，供 stockqueen.co 调用"""
    try:
        from app.services.rotation_service import get_current_positions, _detect_regime
        from app.services.order_service import get_tiger_trade_client

        # 1) Market regime
        try:
            regime = await _detect_regime()
        except Exception:
            regime = "unknown"

        # 2) Active + pending_exit positions from DB
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") in ("active", "pending_exit")]

        # 3) Tiger positions (always fetch for prices, and as fallback when DB is empty)
        tiger_positions_raw = []
        tiger_prices = {}   # ticker -> latest_price
        tiger_costs = {}    # ticker -> average_cost (real fill price)
        try:
            tiger_client = get_tiger_trade_client()
            tiger_positions_raw = await tiger_client.get_positions()
            for tp in tiger_positions_raw:
                tk = tp.get("ticker", "")
                price = tp.get("latest_price", 0)
                cost = float(tp.get("average_cost", 0) or 0)
                if tk and price > 0:
                    tiger_prices[tk] = price
                if tk and cost > 0:
                    tiger_costs[tk] = cost
        except Exception as e:
            logger.warning(f"[PUBLIC-API] Tiger positions error: {e}")

        # Fallback: if DB has no active positions but Tiger does, use Tiger directly
        if not active and tiger_positions_raw:
            logger.info(f"[PUBLIC-API] DB empty, using {len(tiger_positions_raw)} Tiger positions as source")
            for tp in tiger_positions_raw:
                tk = tp.get("ticker", "")
                qty = int(tp.get("quantity", 0))
                if not tk or qty <= 0:
                    continue
                active.append({
                    "ticker": tk,
                    "status": "active",
                    "entry_price": tp.get("average_cost", 0),
                    "current_price": tp.get("latest_price", 0),
                    "quantity": qty,
                    "created_at": "",
                })

        # QuoteClient fallback for any tickers missing real-time price
        if active:
            missing = [p.get("ticker") for p in active if p.get("ticker") and p["ticker"] not in tiger_prices]
            if missing:
                try:
                    from app.services.market_service import TigerAPIClient
                    tiger_quote = TigerAPIClient()
                    for t in missing:
                        q = await tiger_quote.get_stock_quote(t)
                        if q and q.get("latest_price", 0) > 0:
                            tiger_prices[t] = q["latest_price"]
                except Exception:
                    pass

        # 4) Build response — use Tiger cost as entry_price when available
        positions_data = []
        for p in active:
            tk = p.get("ticker", "")
            entry_price = float(p.get("entry_price", 0) or 0)
            # Override with Tiger's actual fill cost
            if tk in tiger_costs:
                entry_price = tiger_costs[tk]
            current_price = float(tiger_prices.get(tk, 0))
            if current_price <= 0:
                current_price = float(p.get("current_price", 0) or 0)
            return_pct = round((current_price - entry_price) / entry_price, 4) if entry_price > 0 and current_price > 0 else 0
            stop_loss = float(p.get("stop_loss", 0) or 0)
            take_profit = float(p.get("take_profit", 0) or 0)
            # Signal date from created_at (DB timestamp)
            created = p.get("created_at", "")
            signal_date = str(created)[:10] if created else ""
            positions_data.append({
                "ticker": tk,
                "status": p.get("status", "active"),
                "entry_price": round(entry_price, 2),
                "current_price": round(current_price, 2),
                "return_pct": return_pct,
                "stop_loss": round(stop_loss, 2) if stop_loss > 0 else None,
                "take_profit": round(take_profit, 2) if take_profit > 0 else None,
                "signal_date": signal_date,
            })

        return JSONResponse({
            "date": date.today().isoformat(),
            "market_regime": regime.upper() if regime else "UNKNOWN",
            "positions": positions_data,
        })
    except Exception as e:
        logger.error(f"[PUBLIC-API] Error: {e}", exc_info=True)
        return JSONResponse({"date": date.today().isoformat(), "market_regime": "UNKNOWN", "positions": []}, status_code=200)


@router.get("/api/public/signal-history", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_signal_history(request: Request):
    """公开API：返回所有已平仓交易记录 + 汇总统计"""
    try:
        from app.database import get_db
        db = get_db()
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", "closed")
            .gt("exit_price", 0)
            .order("exit_date", desc=True)
            .limit(200)
            .execute()
        )
        closed = result.data or []

        trades = []
        total_return = 0.0
        wins = 0
        total_hold_days = 0

        for p in closed:
            entry_price = float(p.get("entry_price") or 0)
            exit_price = float(p.get("exit_price") or 0)
            return_pct = round((exit_price - entry_price) / entry_price, 4) if entry_price > 0 and exit_price > 0 else 0

            # Calculate hold days
            hold_days = 0
            entry_date = p.get("entry_date", "")
            exit_date = p.get("exit_date", "")
            if entry_date and exit_date:
                try:
                    from datetime import datetime
                    d1 = datetime.strptime(str(entry_date)[:10], "%Y-%m-%d")
                    d2 = datetime.strptime(str(exit_date)[:10], "%Y-%m-%d")
                    hold_days = (d2 - d1).days
                except Exception:
                    pass

            total_return += return_pct
            if return_pct > 0:
                wins += 1
            total_hold_days += hold_days

            trades.append({
                "ticker": p.get("ticker", ""),
                "direction": p.get("direction", "long"),
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "return_pct": return_pct,
                "entry_date": str(entry_date)[:10] if entry_date else "",
                "exit_date": str(exit_date)[:10] if exit_date else "",
                "hold_days": hold_days,
                "exit_reason": p.get("exit_reason", ""),
            })

        total = len(trades)
        summary = {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 3) if total > 0 else 0,
            "avg_return": round(total_return / total, 4) if total > 0 else 0,
            "avg_hold_days": round(total_hold_days / total, 1) if total > 0 else 0,
        }

        return JSONResponse({"summary": summary, "trades": trades})
    except Exception as e:
        logger.error(f"[PUBLIC-API] signal-history error: {e}", exc_info=True)
        return JSONResponse({"summary": {}, "trades": []}, status_code=200)


@router.get("/api/public/paper-vs-wf", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_paper_vs_wf(request: Request):
    """公开API：模拟盘实盘数据 vs Walk-Forward基线对比，用于融资尽调"""
    import math
    from datetime import datetime as _dt

    # ── WF 基线（6窗口年度 PIT Walk-Forward OOS，与 IM/融资材料一致）────────
    WF_BASELINE = {
        "sharpe":            1.322,  # V4 固定参数WF avg OOS Sharpe（GHA #23423631911 + #23446074874）
        "annualized_return": 0.139,  # 6窗口OOS复利年化：(1+118.0%)^(1/6)-1
        "cumulative_return": 1.180,  # 6窗口OOS累计收益 118.0%（2020-2025）
        "max_drawdown":      -0.193, # W3 2022年最大回撤
        "win_rate":          0.577,
        "avg_hold_days":     7.0,    # 周度轮动，理论持仓周期
        "description":       "固定参数Walk-Forward 6窗口年度OOS验证（top_n=3 HB=0，PIT修正，GHA #23423631911 + #23446074874，2020-2025）",
    }

    try:
        from app.database import get_db
        db = get_db()
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", "closed")
            .gt("exit_price", 0)
            .order("exit_date", desc=False)
            .limit(500)
            .execute()
        )
        closed = result.data or []

        # ── 计算每笔交易指标 ───────────────────────────────────────────────────
        # trades_display: 所有平仓记录（含无出场价的手动平仓）
        # trades_stat:    只用有完整价格的记录做统计
        trades_display = []
        trades_stat    = []
        for p in closed:
            entry = float(p.get("entry_price") or 0)
            exit_ = float(p.get("exit_price") or 0)
            has_price = entry > 0 and exit_ > 0
            ret = (exit_ - entry) / entry if has_price else None

            hold_days = 1
            entry_date_str = str(p.get("entry_date") or "")[:10]
            exit_date_str  = str(p.get("exit_date")  or "")[:10]
            if entry_date_str and exit_date_str:
                try:
                    d1 = _dt.strptime(entry_date_str, "%Y-%m-%d")
                    d2 = _dt.strptime(exit_date_str,  "%Y-%m-%d")
                    hold_days = max(1, (d2 - d1).days)
                except Exception:
                    pass

            record = {
                "ticker":      p.get("ticker", ""),
                "return":      round(ret, 4) if ret is not None else None,
                "hold_days":   hold_days,
                "entry_date":  entry_date_str,
                "exit_date":   exit_date_str,
                "exit_reason": p.get("exit_reason", ""),
                "entry_price": round(entry, 2) if entry > 0 else None,
                "exit_price":  round(exit_, 2) if exit_ > 0 else None,
            }
            trades_display.append(record)
            if has_price:
                trades_stat.append(record)

        # 统计数据用有完整价格的交易；展示表格用全部平仓记录
        trades = trades_stat

        if len(trades) < 3:
            return JSONResponse({
                "status": "INSUFFICIENT_DATA",
                "status_label": "数据不足",
                "status_detail": f"已有 {len(trades)} 笔完整交易（含价格），至少需要 3 笔",
                "wf_baseline": WF_BASELINE,
                "paper_trading": {"total_trades": len(trades)},
                "comparison": {},
                "trades": trades_display,
                "last_updated": _dt.utcnow().isoformat() + "Z",
            })

        # ── 胜率 / 持仓天数 ───────────────────────────────────────────────────
        returns     = [t["return"] for t in trades]
        hold_days_l = [t["hold_days"] for t in trades]
        wins        = sum(1 for r in returns if r > 0)
        win_rate    = wins / len(returns)
        avg_hold    = sum(hold_days_l) / len(hold_days_l)

        # ── 累计收益（等权 6 仓近似）─────────────────────────────────────────
        equity = 1.0
        equity_curve = [1.0]
        for r in returns:
            equity *= (1 + r / 6)
            equity_curve.append(round(equity, 4))
        cum_return = equity - 1.0

        # ── CAGR ─────────────────────────────────────────────────────────────
        first_date = _dt.strptime(trades[0]["entry_date"],  "%Y-%m-%d")
        last_date  = _dt.strptime(trades[-1]["exit_date"],  "%Y-%m-%d")
        total_days = max(1, (last_date - first_date).days)
        cagr = (equity ** (365.0 / total_days) - 1.0) if total_days >= 14 else None

        # ── Sharpe（按持仓周期归一化到周频）─────────────────────────────────
        weekly_returns = [r * (7.0 / hd) for r, hd in zip(returns, hold_days_l)]
        mean_wr = sum(weekly_returns) / len(weekly_returns)
        variance = sum((r - mean_wr) ** 2 for r in weekly_returns) / len(weekly_returns)
        std_wr   = math.sqrt(variance) if variance > 0 else None
        sharpe   = (mean_wr / std_wr * math.sqrt(52)) if std_wr and std_wr > 0 else None

        # ── 最大回撤 ──────────────────────────────────────────────────────────
        peak   = 1.0
        max_dd = 0.0
        running = 1.0
        for r in returns:
            running *= (1 + r / 6)
            if running > peak:
                peak = running
            dd = (running - peak) / peak
            if dd < max_dd:
                max_dd = dd

        paper = {
            "total_trades":      len(trades_display),  # 全部平仓记录（含无出场价）
            "stat_trades":       len(trades),           # 有完整价格的记录（用于统计）
            "wins":              wins,
            "losses":            len(returns) - wins,
            "win_rate":          round(win_rate, 3),
            "avg_hold_days":     round(avg_hold, 1),
            "cumulative_return": round(cum_return, 3),
            "cagr":              round(cagr, 3) if cagr is not None else None,
            "sharpe":            round(sharpe, 2) if sharpe is not None else None,
            "max_drawdown":      round(max_dd, 3),
            "period_start":      trades[0]["entry_date"],
            "period_end":        trades[-1]["exit_date"],
            "equity_curve":      equity_curve,
        }

        # ── 偏差计算 ─────────────────────────────────────────────────────────
        def _dev(paper_val, wf_val):
            """相对偏差 (paper - wf) / abs(wf)"""
            if paper_val is None or wf_val is None or wf_val == 0:
                return None
            return round((paper_val - wf_val) / abs(wf_val), 3)

        comparison = {
            "sharpe": {
                "wf": WF_BASELINE["sharpe"],
                "paper": paper["sharpe"],
                "deviation": _dev(paper["sharpe"], WF_BASELINE["sharpe"]),
            },
            "win_rate": {
                "wf": WF_BASELINE["win_rate"],
                "paper": paper["win_rate"],
                "deviation": _dev(paper["win_rate"], WF_BASELINE["win_rate"]),
            },
            "avg_hold_days": {
                "wf": WF_BASELINE["avg_hold_days"],
                "paper": paper["avg_hold_days"],
                "deviation": _dev(paper["avg_hold_days"], WF_BASELINE["avg_hold_days"]),
            },
            "max_drawdown": {
                "wf": WF_BASELINE["max_drawdown"],
                "paper": paper["max_drawdown"],
                "deviation": _dev(paper["max_drawdown"], WF_BASELINE["max_drawdown"]),
            },
            "cagr": {
                "wf": WF_BASELINE["annualized_return"],
                "paper": paper["cagr"],
                "deviation": _dev(paper["cagr"], WF_BASELINE["annualized_return"]),
            },
        }

        # ── 总体状态判断 ──────────────────────────────────────────────────────
        significant_devs = [
            abs(v["deviation"])
            for v in comparison.values()
            if v["deviation"] is not None
        ]
        max_dev = max(significant_devs) if significant_devs else 0

        if len(trades) < 10:
            status, label, detail = (
                "EARLY_STAGE", "早期验证中",
                f"已有 {len(trades)} 笔交易，建议累积至 20+ 笔后参考偏差数据"
            )
        elif max_dev <= 0.20:
            status, label, detail = (
                "ON_TRACK", "策略一致",
                "模拟盘各项指标与 Walk-Forward 预测偏差 < 20%，策略运行正常"
            )
        elif max_dev <= 0.40:
            status, label, detail = (
                "DIVERGING", "轻微偏离",
                f"最大偏差 {max_dev:.0%}，建议关注偏差来源（市场体制切换或参数漂移）"
            )
        else:
            status, label, detail = (
                "WARNING", "需要关注",
                f"最大偏差 {max_dev:.0%}，建议排查策略执行链路或市场结构性变化"
            )

        return JSONResponse({
            "status":        status,
            "status_label":  label,
            "status_detail": detail,
            "wf_baseline":   WF_BASELINE,
            "paper_trading": paper,
            "comparison":    comparison,
            "trades":        trades_display,  # 全部平仓记录（含无出场价的手动平仓）
            "last_updated":  _dt.utcnow().isoformat() + "Z",
        })

    except Exception as e:
        logger.error(f"[PUBLIC-API] paper-vs-wf error: {e}", exc_info=True)
        return JSONResponse({
            "status": "ERROR",
            "status_label": "加载失败",
            "status_detail": str(e),
            "wf_baseline": WF_BASELINE,
            "paper_trading": {},
            "comparison": {},
            "trades": [],
            "last_updated": "",
        }, status_code=200)


@router.get("/api/public/rotation-history", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_rotation_history(request: Request):
    """公开API：返回周度轮动快照历史 (DB去重 + 静态JSON补全)"""
    try:
        from app.database import get_db
        from datetime import datetime as _dt
        db = get_db()

        # ---------- 1. 从 DB 读取并按日期去重（每天只保留最新、有持仓的快照）----------
        result = (
            db.table("rotation_snapshots")
            .select("snapshot_date, regime, selected_tickers, scores, trigger_source, created_at")
            .order("snapshot_date", desc=True)
            .limit(200)
            .execute()
        )
        snapshots = result.data or []

        # 按日期去重：优先 scheduler > weekly_report > manual_api，取有持仓的
        # 同时合并同一天所有快照的 scores（防御ETF可能只出现在非scheduler快照中）
        _source_priority = {"scheduler": 0, "weekly_report": 1, "manual_api": 2}
        date_best: dict = {}
        date_all_scores: dict = {}  # date -> merged scores list
        for snap in snapshots:
            d = snap.get("snapshot_date", "")
            tickers = snap.get("selected_tickers") or []
            # 合并所有快照的 scores
            snap_scores = snap.get("scores") or []
            if isinstance(snap_scores, list):
                if d not in date_all_scores:
                    date_all_scores[d] = {}
                for s in snap_scores:
                    tk = s.get("ticker")
                    if tk and tk not in date_all_scores[d]:
                        date_all_scores[d][tk] = s
            if not tickers:
                continue  # 跳过空持仓
            src = snap.get("trigger_source", "manual_api")
            prio = _source_priority.get(src, 9)
            if d not in date_best or prio < _source_priority.get(date_best[d].get("trigger_source", ""), 9):
                date_best[d] = snap

        # 按 ISO week 去重：每周只保留最晚日期的快照
        week_best: dict = {}
        for d, snap in date_best.items():
            try:
                dt = _dt.strptime(str(d)[:10], "%Y-%m-%d")
                iso_week = dt.strftime("%G-W%V")  # e.g. "2026-W11"
            except Exception:
                continue
            if iso_week not in week_best or d > week_best[iso_week].get("snapshot_date", ""):
                week_best[iso_week] = snap

        # 构建 DB history
        db_history = []
        for snap in week_best.values():
            tickers = snap.get("selected_tickers") or []
            d = snap.get("snapshot_date", "")
            # 使用合并后的 scores（包含同一天所有快照的数据，确保防御ETF也能匹配）
            merged_scores = date_all_scores.get(d, {})
            return_1w = None
            if merged_scores:
                rets = [merged_scores[tk].get("return_1w") for tk in tickers
                        if tk in merged_scores and merged_scores[tk].get("return_1w") is not None]
                if rets:
                    return_1w = round(sum(rets) / len(rets), 4)
            db_history.append({
                "week": snap.get("snapshot_date", ""),
                "regime": (snap.get("regime") or "unknown").upper(),
                "holdings": tickers,
                "return_1w": return_1w,
            })

        # ---------- 2. 用静态 JSON 补全历史周次 ----------
        db_weeks = {h["week"] for h in db_history}
        try:
            import os, json
            static_path = os.path.join(os.path.dirname(__file__), "..", "..", "site", "data", "signal-history.json")
            if os.path.exists(static_path):
                with open(static_path) as f:
                    static_items = json.load(f)
                for item in static_items:
                    # 静态 JSON 的 week 可能是 "Mar 10, 2026" 或 "2026-03-10" 格式
                    w = item.get("week", "")
                    try:
                        dt = _dt.strptime(w, "%b %d, %Y")
                        w_iso = dt.strftime("%Y-%m-%d")
                    except Exception:
                        w_iso = w
                    if w_iso not in db_weeks:
                        holdings = item.get("holdings", "")
                        if isinstance(holdings, str):
                            holdings = [h.strip() for h in holdings.split(",") if h.strip()]
                        db_history.append({
                            "week": w_iso,
                            "regime": (item.get("regime") or "unknown").upper(),
                            "holdings": holdings,
                            "return_1w": item.get("return_1w"),
                            "hold_days": item.get("hold_days"),
                        })
        except Exception:
            pass  # 静态文件读取失败不影响 DB 数据

        # ---------- 3. 计算持有天数 ----------
        sorted_history = sorted(db_history, key=lambda x: x["week"])
        _prev_tickers = None
        _holding_start = None
        for item in sorted_history:
            cur_tickers = sorted(item.get("holdings") or [])
            snap_date = item.get("week", "")
            if cur_tickers != _prev_tickers:
                _holding_start = snap_date
                _prev_tickers = cur_tickers
            if _holding_start and snap_date:
                try:
                    d1 = _dt.strptime(str(_holding_start)[:10], "%Y-%m-%d")
                    d2 = _dt.strptime(str(snap_date)[:10], "%Y-%m-%d")
                    item["hold_days"] = (d2 - d1).days + 7
                except Exception:
                    item["hold_days"] = item.get("hold_days", 7)
            else:
                item["hold_days"] = item.get("hold_days", 7)

        # ---------- 4. 排序、标记、限制 ----------
        history = sorted(db_history, key=lambda x: x["week"], reverse=True)[:20]
        if history:
            history[0]["is_latest"] = True

        # ---------- 5. 已平仓交易汇总 ----------
        closed_result = (
            db.table("rotation_positions")
            .select("ticker, entry_price, exit_price, entry_date, exit_date, exit_reason, status")
            .eq("status", "closed")
            .gt("exit_price", 0)
            .order("exit_date", desc=True)
            .execute()
        )
        closed_trades = closed_result.data or []

        trade_summary = {"total_trades": 0, "wins": 0, "win_rate": 0, "avg_return": 0}
        if closed_trades:
            total = len(closed_trades)
            wins = 0
            total_return = 0.0
            for t in closed_trades:
                ep = float(t.get("entry_price") or 0)
                xp = float(t.get("exit_price") or 0)
                if ep > 0 and xp > 0:
                    ret = (xp - ep) / ep
                    total_return += ret
                    if ret > 0:
                        wins += 1
            trade_summary = {
                "total_trades": total,
                "wins": wins,
                "win_rate": round(wins / total, 3) if total > 0 else 0,
                "avg_return": round(total_return / total, 4) if total > 0 else 0,
            }

        return JSONResponse({
            "history": history,
            "trade_summary": trade_summary,
            "closed_trades": [{
                "ticker": t.get("ticker", ""),
                "entry_price": float(t.get("entry_price") or 0),
                "exit_price": float(t.get("exit_price") or 0),
                "entry_date": str(t.get("entry_date", ""))[:10],
                "exit_date": str(t.get("exit_date", ""))[:10],
                "exit_reason": t.get("exit_reason", ""),
            } for t in closed_trades[:20]],
        })
    except Exception as e:
        logger.error(f"[PUBLIC-API] rotation-history error: {e}", exc_info=True)
        return JSONResponse({"history": [], "trade_summary": {}, "closed_trades": []}, status_code=200)


@router.get("/api/public/regime-details", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_regime_details(request: Request):
    """公开API：返回 Regime 状态机详情 (当前状态、信号分解、转换距离)"""
    try:
        from app.services.rotation_service import detect_regime_details
        details = await detect_regime_details()
        return JSONResponse(details)
    except Exception as e:
        logger.error(f"[PUBLIC-API] regime-details error: {e}", exc_info=True)
        return JSONResponse({"regime": "unknown", "score": 0, "signals": [], "transitions": {}}, status_code=200)


def _load_static_yearly_performance() -> dict | None:
    """Load static yearly-performance.json as fallback data."""
    try:
        import os, json
        static_path = os.path.join(os.path.dirname(__file__), "..", "..", "site", "data", "yearly-performance.json")
        if os.path.exists(static_path):
            with open(static_path) as f:
                return json.load(f)
    except Exception:
        pass
    return None


async def _compute_yearly_performance_from_db() -> dict | None:
    """
    从 rotation_snapshots 计算年度业绩。
    使用前瞻性收益：snapshot N 的 selected_tickers 在 snapshot N+1 中的 return_1w。
    返回 dict with years/total/last_updated/source, 或 None 如果数据不足。
    """
    from app.database import get_db
    from collections import defaultdict
    import math

    db = get_db()
    result = (
        db.table("rotation_snapshots")
        .select("snapshot_date, regime, scores, selected_tickers")
        .order("snapshot_date", desc=False)
        .execute()
    )
    snapshots = result.data or []
    if len(snapshots) < 2:
        return None

    # ---------- 按 ISO 周去重：每周只保留最晚日期的快照，避免同日多条重复累乘 ----------
    from datetime import datetime as _dt
    _source_prio = {"scheduler": 0, "weekly_report": 1, "manual_api": 2}
    week_deduped: dict = {}  # iso_week -> best snapshot (with merged scores)
    week_all_scores: dict = {}  # iso_week -> {ticker: score_obj}

    for snap in snapshots:
        d = snap.get("snapshot_date", "")
        try:
            dt = _dt.strptime(str(d)[:10], "%Y-%m-%d")
            iso_week = dt.strftime("%G-W%V")
        except Exception:
            continue

        # 合并同周所有快照的 scores
        snap_scores = snap.get("scores") or []
        if isinstance(snap_scores, list):
            if iso_week not in week_all_scores:
                week_all_scores[iso_week] = {}
            for s in snap_scores:
                tk = s.get("ticker")
                if tk and tk not in week_all_scores[iso_week]:
                    week_all_scores[iso_week][tk] = s

        tickers = snap.get("selected_tickers") or []
        if not tickers:
            continue
        src = snap.get("trigger_source", "manual_api")
        prio = _source_prio.get(src, 9)
        # 同周取最晚日期，同日取最高优先级
        if iso_week not in week_deduped or d > week_deduped[iso_week].get("snapshot_date", "") or \
                (d == week_deduped[iso_week].get("snapshot_date", "") and
                 prio < _source_prio.get(week_deduped[iso_week].get("trigger_source", ""), 9)):
            week_deduped[iso_week] = snap

    # 按 ISO 周排序
    sorted_weeks = sorted(week_deduped.keys())
    deduped_snapshots = [week_deduped[w] for w in sorted_weeks]

    if len(deduped_snapshots) < 2:
        return None

    # ---------- 构建 forward returns: 去重后 snapshot[i] → snapshot[i+1] 的 return_1w ----------
    yearly_returns = defaultdict(list)  # year -> [weekly portfolio returns]

    for i in range(len(deduped_snapshots) - 1):
        curr = deduped_snapshots[i]
        nxt = deduped_snapshots[i + 1]
        selected = set(curr.get("selected_tickers") or [])
        if not selected:
            continue

        # 使用下一周合并后的 scores（覆盖进攻+防御 ETF）
        nxt_date = nxt.get("snapshot_date", "")
        try:
            nxt_iso = _dt.strptime(str(nxt_date)[:10], "%Y-%m-%d").strftime("%G-W%V")
        except Exception:
            continue
        merged_scores = week_all_scores.get(nxt_iso, {})

        rets = []
        for tk in selected:
            if tk in merged_scores:
                r = merged_scores[tk].get("return_1w")
                if r is not None:
                    rets.append(float(r))

        if rets:
            avg_ret = sum(rets) / len(rets)
            if nxt_date:
                yearly_returns[nxt_date[:4]].append(avg_ret)

    if not yearly_returns:
        return None

    # 获取 SPY/QQQ 基准数据
    spy_qqq = {}
    try:
        from app.services.rotation_service import _fetch_history
        for ticker in ["SPY", "QQQ"]:
            data = await _fetch_history(ticker, days=1300)
            if data and len(data["close"]) > 0:
                spy_qqq[ticker] = data
    except Exception as e:
        logger.warning(f"[YEARLY-PERF] Failed to fetch benchmark data: {e}")

    # 构建年度数据
    years = []
    current_year = str(date.today().year)

    for year in sorted(yearly_returns.keys()):
        weekly_rets = yearly_returns[year]
        cumulative = 1.0
        for r in weekly_rets:
            cumulative *= (1 + r)
        strategy_return = round(cumulative - 1, 4)

        n_weeks = len(weekly_rets)
        annualized = None
        sharpe = None
        if year != current_year and n_weeks >= 20:
            annualized = round(strategy_return, 4)
            import numpy as np
            mean_w = sum(weekly_rets) / len(weekly_rets)
            std_w = float(np.std(weekly_rets)) if len(weekly_rets) > 1 else 0.001
            sharpe = round((mean_w / std_w) * math.sqrt(52), 2) if std_w > 0 else None

        spy_return = None
        qqq_return = None
        for ticker in ["SPY", "QQQ"]:
            if ticker in spy_qqq:
                closes = spy_qqq[ticker]["close"]
                dates = spy_qqq[ticker].get("dates", [])
                if len(dates) > 0:
                    year_closes = [(d, c) for d, c in zip(dates, closes) if str(d).startswith(year)]
                    if len(year_closes) >= 2:
                        yr = round(float(year_closes[-1][1]) / float(year_closes[0][1]) - 1, 4)
                        if ticker == "SPY":
                            spy_return = yr
                        else:
                            qqq_return = yr

        label = f"{year} YTD" if year == current_year else year
        years.append({
            "year": label,
            "strategy_return": strategy_return,
            "spy_return": spy_return,
            "qqq_return": qqq_return,
            "annualized_return": annualized,
            "sharpe": sharpe,
            "weeks": n_weeks,
        })

    # 总计 (仅 DB 数据的汇总，用于纯 DB 模式)
    all_rets = []
    for wr in yearly_returns.values():
        all_rets.extend(wr)

    total_cum = 1.0
    for r in all_rets:
        total_cum *= (1 + r)

    import numpy as np
    total = {
        "strategy_return": round(total_cum - 1, 4),
        "weeks": len(all_rets),
    }
    if len(all_rets) > 10:
        mean_w = sum(all_rets) / len(all_rets)
        std_w = float(np.std(all_rets))
        total["sharpe"] = round((mean_w / std_w) * math.sqrt(52), 2) if std_w > 0 else None
        total["annualized_return"] = round((total_cum ** (52 / len(all_rets))) - 1, 4)
        peak = 1.0
        max_dd = 0.0
        cum = 1.0
        for r in all_rets:
            cum *= (1 + r)
            peak = max(peak, cum)
            dd = (cum - peak) / peak
            max_dd = min(max_dd, dd)
        total["max_drawdown"] = round(max_dd, 4)
        wins = sum(1 for r in all_rets if r > 0)
        total["win_rate"] = round(wins / len(all_rets), 3)

    if not years or total.get("weeks", 0) == 0:
        return None

    return {
        "years": years,
        "total": total,
        "last_updated": date.today().isoformat(),
        "source": "database",
    }


def _recalculate_total_from_merged_years(merged_years: list, static_total: dict) -> dict:
    """
    从合并后的年度数据重算 total 指标，避免 DB 短期数据覆盖历史累计值。
    - strategy_return / spy_return / qqq_return: 从各年复利累乘
    - alpha: 策略减基准
    - sharpe: 按 weeks 加权平均各年 sharpe
    - max_drawdown / win_rate: 从年度 equity curve 近似或保留静态值
    - annualized_return: 从累计收益和总周数推算
    - 保留 static_total 中的元数据字段 (validation_method, note 等)
    """
    import math

    merged_total = {**static_total}  # 保留元数据字段

    # 复利累乘各年收益
    strat_cum = 1.0
    spy_cum = 1.0
    qqq_cum = 1.0
    total_weeks = 0
    sharpe_wsum = 0.0
    sharpe_weeks = 0

    for y in merged_years:
        sr = y.get("strategy_return")
        if sr is not None:
            strat_cum *= (1 + sr)

        spy_r = y.get("spy_return")
        if spy_r is not None:
            spy_cum *= (1 + spy_r)

        qqq_r = y.get("qqq_return")
        if qqq_r is not None:
            qqq_cum *= (1 + qqq_r)

        w = y.get("weeks", 52)  # 历史年默认 52 周
        total_weeks += w

        if y.get("sharpe") is not None:
            sharpe_wsum += y["sharpe"] * w
            sharpe_weeks += w

    merged_total["strategy_return"] = round(strat_cum - 1, 4)
    merged_total["spy_return"] = round(spy_cum - 1, 4)
    merged_total["qqq_return"] = round(qqq_cum - 1, 4)
    merged_total["alpha_vs_spy"] = round((strat_cum - 1) - (spy_cum - 1), 4)
    merged_total["alpha_vs_qqq"] = round((strat_cum - 1) - (qqq_cum - 1), 4)
    merged_total["weeks"] = total_weeks
    merged_total["total_weeks"] = total_weeks

    if total_weeks > 0:
        merged_total["annualized_return"] = round(
            (strat_cum ** (52 / total_weeks)) - 1, 4
        )

    if sharpe_weeks > 0:
        merged_total["sharpe"] = round(sharpe_wsum / sharpe_weeks, 2)

    # max_drawdown / win_rate：无法从年度数据精确计算，
    # 用各年最差 max_drawdown 近似 (如果年度数据有)，否则保留 static_total 值
    yearly_mds = [y["max_drawdown"] for y in merged_years if y.get("max_drawdown") is not None]
    if yearly_mds:
        merged_total["max_drawdown"] = round(min(yearly_mds), 4)

    yearly_wrs = [(y["win_rate"], y.get("weeks", 52)) for y in merged_years if y.get("win_rate") is not None]
    if yearly_wrs:
        wr_wsum = sum(wr * w for wr, w in yearly_wrs)
        wr_wtotal = sum(w for _, w in yearly_wrs)
        merged_total["win_rate"] = round(wr_wsum / wr_wtotal, 3) if wr_wtotal > 0 else None

    return merged_total


@router.get("/api/public/yearly-performance", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_yearly_performance(request: Request):
    """公开API：从rotation_snapshots自动计算年度业绩表，静态历史+DB实时混合"""
    try:
        # 1) 尝试从 DB 计算实时数据
        db_data = await _compute_yearly_performance_from_db()

        # 2) 加载静态历史数据
        static_data = _load_static_yearly_performance()

        if db_data and db_data.get("years"):
            current_year = str(date.today().year)

            if static_data and static_data.get("years"):
                # 3) 混合：WF OOS 覆盖的年份用静态数据，其余用 DB 实盘数据
                static_year_keys = {y["year"] for y in static_data["years"]}
                merged_years = list(static_data["years"])

                # DB 中不在静态覆盖范围的年份（如 2025、2026 YTD）追加
                for dy in db_data["years"]:
                    dy_key = dy["year"].replace(" YTD", "")
                    if dy_key not in static_year_keys:
                        merged_years.append(dy)
                # 按年份排序
                merged_years.sort(key=lambda y: y["year"].replace(" YTD", "9999") if "YTD" in y["year"] else y["year"])

                # total 直接用静态 WF OOS 数据，不与 YTD 累乘（方法论不同，不能混算）
                static_total = static_data.get("total", {})

                return JSONResponse({
                    "years": merged_years,
                    "total": static_total,
                    "last_updated": date.today().isoformat(),
                    "source": "database",
                })
            else:
                # 没有静态数据，纯 DB
                return JSONResponse(db_data)

        # 4) DB 计算失败，降级到静态 JSON
        if static_data:
            static_data["source"] = "static"
            static_data.setdefault("last_updated", date.today().isoformat())
            return JSONResponse(static_data)

        return JSONResponse({"source": "static", "fallback": True, "error": "No data available"}, status_code=200)

    except Exception as e:
        logger.warning(f"[PUBLIC-API] yearly-performance error: {e}", exc_info=True)
        static_data = _load_static_yearly_performance()
        if static_data:
            static_data["source"] = "static"
            static_data.setdefault("last_updated", date.today().isoformat())
            return JSONResponse(static_data)
        return JSONResponse({"source": "static", "fallback": True, "error": str(e)}, status_code=200)


async def refresh_yearly_performance_json() -> dict:
    """
    自动刷新 site/data/yearly-performance.json 静态文件。
    从 DB 计算最新数据，与静态历史合并后写回文件。
    可被 scheduler 或手动 API 调用。返回 {"status": "ok"/"skipped", ...}。
    """
    import os, json

    static_path = os.path.join(os.path.dirname(__file__), "..", "..", "site", "data", "yearly-performance.json")

    try:
        db_data = await _compute_yearly_performance_from_db()
        if not db_data or not db_data.get("years"):
            return {"status": "skipped", "reason": "DB data insufficient"}

        # 加载现有静态文件
        existing = {}
        if os.path.exists(static_path):
            with open(static_path, encoding="utf-8") as f:
                existing = json.load(f)

        # 合并：保留静态中 DB 没覆盖的年份
        db_years_set = {y["year"].replace(" YTD", "") for y in db_data["years"]}
        merged_years = []
        if existing.get("years"):
            for sy in existing["years"]:
                sy_key = sy["year"].replace(" YTD", "")
                if sy_key not in db_years_set:
                    merged_years.append(sy)
        merged_years.extend(db_data["years"])
        merged_years.sort(key=lambda y: y["year"].replace(" YTD", "9999") if "YTD" in y["year"] else y["year"])

        # 从合并后的年度数据重算 total
        existing_total = existing.get("total", {})
        merged_total = _recalculate_total_from_merged_years(merged_years, existing_total)

        output = {
            "years": merged_years,
            "total": merged_total,
            "last_updated": date.today().isoformat(),
        }

        with open(static_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info(f"[YEARLY-PERF] Static JSON refreshed: {len(merged_years)} years, last_updated={output['last_updated']}")
        return {"status": "ok", "years": len(merged_years), "last_updated": output["last_updated"]}

    except Exception as e:
        logger.error(f"[YEARLY-PERF] Failed to refresh static JSON: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.post("/api/admin/refresh-yearly-performance", response_class=JSONResponse)
async def api_admin_refresh_yearly_performance(request: Request):
    """手动触发刷新年度业绩静态JSON（需 admin token）"""
    # 简单 token 校验
    import os
    token = request.headers.get("X-Admin-Token", "")
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or token != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    result = await refresh_yearly_performance_json()
    return JSONResponse(result)


# ==================================================================
# Equity Curve Auto-refresh
# ==================================================================

async def _extend_equity_curve_from_db(after_date: str, base_equity: float,
                                        base_spy: float | None, base_qqq: float | None) -> list | None:
    """
    从 rotation_snapshots 中 after_date 所在月之后的快照延伸权益曲线。
    base_equity/spy/qqq 为 after_date 月的末值，新点在此基础上累积（不重置为 1.0）。
    """
    from app.database import get_db
    from collections import defaultdict

    db = get_db()
    result = (
        db.table("rotation_snapshots")
        .select("snapshot_date, scores, selected_tickers")
        .gte("snapshot_date", after_date)
        .order("snapshot_date", desc=False)
        .execute()
    )
    snapshots = result.data or []
    if len(snapshots) < 2:
        return None

    base_month = after_date[:7]
    monthly_returns: dict = defaultdict(list)
    for i in range(len(snapshots) - 1):
        curr = snapshots[i]
        nxt = snapshots[i + 1]
        selected = set(curr.get("selected_tickers") or [])
        if not selected:
            continue
        next_scores = nxt.get("scores") or []
        if not isinstance(next_scores, list):
            continue
        rets = []
        for s in next_scores:
            if s.get("ticker") in selected:
                r = s.get("return_1w")
                if r is not None:
                    rets.append(float(r))
        if rets:
            nxt_date = nxt.get("snapshot_date", "")
            if nxt_date and len(nxt_date) >= 7:
                m = nxt_date[:7]
                if m >= base_month:  # 包含当月（可能更新当月最后一周）
                    monthly_returns[m].append(sum(rets) / len(rets))

    if not monthly_returns:
        return None

    # 从 base_equity 延伸
    equity = base_equity
    points = []
    for month_key in sorted(monthly_returns.keys()):
        for r in monthly_returns[month_key]:
            equity *= (1 + r)
        points.append({"date": month_key + "-01", "strategy": round(equity, 4)})

    if not points:
        return None

    # 延伸 SPY/QQQ（以 after_date 月的价格为锚点）
    try:
        from app.services.rotation_service import _fetch_history
        for ticker, key, base_val in [("SPY", "spy", base_spy), ("QQQ", "qqq", base_qqq)]:
            if base_val is None:
                continue
            hist = await _fetch_history(ticker, days=400)
            if hist and hist.get("close") and hist.get("dates"):
                month_last: dict = {}
                for d, c in zip(hist["dates"], hist["close"]):
                    month_last[str(d)[:7]] = float(c)
                anchor_price = month_last.get(base_month)
                if anchor_price:
                    for pt in points:
                        m = pt["date"][:7]
                        if m in month_last:
                            pt[key] = round(base_val * month_last[m] / anchor_price, 4)
    except Exception as e:
        logger.warning(f"[EQUITY-CURVE] Benchmark extension failed: {e}")

    return points


async def refresh_equity_curve_json() -> dict:
    """
    自动刷新 site/data/equity-curve.json 静态文件。
    从现有最后一个数据点向后延伸，不重置基数，保证曲线连续。
    """
    import os, json as _json

    static_path = os.path.join(os.path.dirname(__file__), "..", "..", "site", "data", "equity-curve.json")
    try:
        existing: list = []
        if os.path.exists(static_path):
            with open(static_path, encoding="utf-8") as f:
                existing = _json.load(f)

        if not existing:
            return {"status": "skipped", "reason": "No existing static data to extend from"}

        last_pt = existing[-1]
        last_date = last_pt["date"]       # e.g. "2026-03-01"
        last_equity = last_pt["strategy"] # e.g. 5.944
        last_spy = last_pt.get("spy")
        last_qqq = last_pt.get("qqq")

        new_points = await _extend_equity_curve_from_db(last_date, last_equity, last_spy, last_qqq)
        if not new_points:
            return {"status": "skipped", "reason": f"No new data after {last_date}"}

        new_months = {pt["date"][:7] for pt in new_points}
        merged = [pt for pt in existing if pt.get("date", "")[:7] not in new_months]
        merged.extend(new_points)
        merged.sort(key=lambda x: x.get("date", ""))

        with open(static_path, "w", encoding="utf-8") as f:
            _json.dump(merged, f, indent=2, ensure_ascii=False)

        last = merged[-1]["date"] if merged else "N/A"
        logger.info(f"[EQUITY-CURVE] Extended: {len(new_points)} new/updated points, last={last}")
        return {"status": "ok", "points": len(merged), "last_date": last}

    except Exception as e:
        logger.error(f"[EQUITY-CURVE] Failed to refresh: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@router.get("/api/public/equity-curve", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_equity_curve(request: Request):
    """公开API：月度权益曲线静态文件（scheduler 每周六更新）"""
    import os, json as _json

    static_path = os.path.join(os.path.dirname(__file__), "..", "..", "site", "data", "equity-curve.json")
    if os.path.exists(static_path):
        with open(static_path, encoding="utf-8") as f:
            points = _json.load(f)
        last_updated = points[-1]["date"][:10] if points else None
        return JSONResponse({"points": points, "source": "static", "last_updated": last_updated})

    return JSONResponse({"error": "No equity curve data available"}, status_code=503)


@router.post("/api/admin/refresh-equity-curve", response_class=JSONResponse)
async def api_admin_refresh_equity_curve(request: Request):
    """手动触发刷新权益曲线静态JSON（需 admin token）"""
    import os
    token = request.headers.get("X-Admin-Token", "")
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or token != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    result = await refresh_equity_curve_json()
    return JSONResponse(result)


# ==================================================================
# Newsletter 审批流程
# ==================================================================

def _newsletter_week_key() -> str:
    """生成本周唯一 key，格式 2026-W12"""
    now = datetime.now()
    return f"{now.year}-W{now.isocalendar()[1]:02d}"

def _newsletter_approve_token(week_key: str) -> str:
    """生成审批 token（HMAC，防伪造）"""
    import hashlib, hmac, os
    secret = os.getenv("UNSUB_SECRET", "stockqueen-unsub-2026")
    return hmac.new(secret.encode(), week_key.encode(), hashlib.sha256).hexdigest()[:16]

@router.get("/api/admin/newsletter/approve", response_class=HTMLResponse)
async def api_newsletter_approve(request: Request, token: str = "", week: str = ""):
    """
    Newsletter 审批链接 —— 在预览邮件里点击后批准发送。
    GET /api/admin/newsletter/approve?week=2026-W12&token=xxxx
    """
    week_key = week or _newsletter_week_key()
    expected_token = _newsletter_approve_token(week_key)
    if token != expected_token:
        return HTMLResponse("<h2>❌ 无效审批链接</h2>", status_code=403)

    try:
        from app.database import get_db
        supabase = get_db()
        supabase.table("newsletter_approvals").upsert({
            "week_year": week_key,
            "approved_at": datetime.utcnow().isoformat(),
        }).execute()
        logger.info(f"[NEWSLETTER-APPROVE] {week_key} 已审批通过")
    except Exception as e:
        logger.error(f"[NEWSLETTER-APPROVE] 写入审批记录失败: {e}")
        return HTMLResponse(f"<h2>❌ 审批记录写入失败: {e}</h2>", status_code=500)

    return HTMLResponse("""
    <html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#0f172a;color:#fff;">
    <h1 style="color:#22c55e;">✅ Newsletter 审批通过</h1>
    <p style="color:#94a3b8;font-size:18px;">系统将在今晚 NZT 9:00 正式发送给所有订阅者。</p>
    <p style="color:#64748b;">如需取消，请直接联系管理员。</p>
    </body></html>
    """)

@router.get("/api/admin/newsletter/status", response_class=JSONResponse)
async def api_newsletter_status(request: Request):
    """查询本周 newsletter 审批状态"""
    week_key = _newsletter_week_key()
    try:
        from app.database import get_db
        supabase = get_db()
        resp = supabase.table("newsletter_approvals").select("*").eq("week_year", week_key).execute()
        row = resp.data[0] if resp.data else None
        return JSONResponse({
            "week": week_key,
            "approved": row is not None and row.get("approved_at") is not None,
            "approved_at": row.get("approved_at") if row else None,
            "preview_sent_at": row.get("preview_sent_at") if row else None,
            "send_sent_at": row.get("send_sent_at") if row else None,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ==================================================================
# C2: After-Hours Event Signal Scan（手动触发）
# ==================================================================

@router.post("/api/admin/run-trailing-stop", response_class=JSONResponse)
async def api_admin_run_trailing_stop(request: Request):
    """手动立即触发止盈/止损检查（需 admin token）"""
    import os
    token = request.headers.get("X-Admin-Token", "")
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or token != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    from app.services.order_service import run_intraday_trailing_stop
    result = await run_intraday_trailing_stop()
    return JSONResponse({"status": "ok", **result})


@router.post("/api/admin/run-event-scan", response_class=JSONResponse)
async def api_admin_run_event_scan(request: Request):
    """手动触发盘后 AI 事件信号扫描（需 admin token）"""
    import os
    token = request.headers.get("X-Admin-Token", "")
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or token != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    from app.services.news_scanner_service import get_news_scanner
    result = await get_news_scanner().run_daily_scan()
    return JSONResponse(result)


@router.post("/api/admin/refresh-universe", response_class=JSONResponse)
async def api_admin_refresh_universe(request: Request):
    """手动触发动态选股池刷新（需 admin token）"""
    import os
    token = request.headers.get("X-Admin-Token", "")
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or token != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        from app.services.universe_service import UniverseService
        result = await UniverseService().refresh_universe(concurrency=5)
        return JSONResponse({
            "status": "ok",
            "total_screened": result.get("total_screened", 0),
            "final_count": result.get("final_count", 0),
            "elapsed_seconds": result.get("elapsed_seconds", 0),
        })
    except Exception as e:
        logger.error(f"Universe refresh error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/universe/status", response_class=JSONResponse)
async def api_universe_status(request: Request):
    """获取选股池当前状态（无需鉴权）"""
    try:
        from app.services.universe_service import UniverseService
        data = UniverseService().get_current_universe_full()
        if not data:
            return JSONResponse({"status": "empty", "count": 0})

        sector_counts = {}
        for t in data.get("tickers", []):
            s = t.get("sector", "OTHER")
            sector_counts[s] = sector_counts.get(s, 0) + 1

        return JSONResponse({
            "status": "ok",
            "count": len(data.get("tickers", [])),
            "timestamp": data.get("timestamp", ""),
            "sectors": sector_counts,
            "filters": data.get("filters", {}),
        })
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)},
                            status_code=500)


# ==================================================================
# Newsletter Subscribe API（后端代理 - 避免前端暴露 API Key）
# ==================================================================

@router.post("/api/newsletter/subscribe", response_class=JSONResponse)
@_limiter.limit("10/minute")
async def api_newsletter_subscribe(request: Request):
    """
    Newsletter 订阅 API
    接收 email + lang，写入 Resend Audience + 发送欢迎邮件
    前端调用此 API 代替直接调用 Resend API
    """
    import os
    try:
        body = await request.json()
        email = body.get("email", "").strip().lower()
        lang = body.get("lang", "en")  # "en" or "zh"

        if not email or "@" not in email:
            return JSONResponse({"success": False, "error": "Invalid email"}, status_code=400)

        resend_api_key = os.getenv("RESEND_API_KEY", "")
        if not resend_api_key:
            logger.error("[SUBSCRIBE] RESEND_API_KEY not configured")
            return JSONResponse({"success": False, "error": "Service unavailable"}, status_code=503)

        try:
            import resend
        except ImportError as e:
            logger.error(f"[SUBSCRIBE] resend package not installed: {e}")
            return JSONResponse({"success": False, "error": "Service unavailable"}, status_code=503)

        resend.api_key = resend_api_key
        logger.info(f"[SUBSCRIBE] Processing: {email} (lang={lang})")

        # 1) 添加到 Resend Audience（如果配置了 audience_id）
        audience_id = os.getenv("RESEND_AUDIENCE_ID", "")
        contact_added = False
        if audience_id:
            try:
                resend.Contacts.create({
                    "audience_id": audience_id,
                    "email": email,
                    "first_name": lang,  # 用 first_name 存语言偏好 (en/zh)
                    "unsubscribed": False,
                })
                contact_added = True
                logger.info(f"[SUBSCRIBE] Contact added to audience: {email}")
            except Exception as e:
                # 可能已存在，不阻塞
                logger.warning(f"[SUBSCRIBE] Add contact warning: {e}")
        else:
            logger.warning("[SUBSCRIBE] RESEND_AUDIENCE_ID not set, skipping contact creation")

        # 2) 发送欢迎邮件
        from_email = os.getenv("NEWSLETTER_FROM", "")
        if not from_email:
            from_email = "StockQueen <newsletter@stockqueen.tech>"
        logger.info(f"[SUBSCRIBE] Using from_email: {from_email}")

        if lang == "zh":
            subject = "欢迎订阅 StockQueen 量化策略周报！"
            html = _welcome_email_zh(email)
        else:
            subject = "Welcome to StockQueen Weekly Newsletter!"
            html = _welcome_email_en(email)

        welcome_sent = False
        try:
            result = resend.Emails.send({
                "from": from_email,
                "to": [email],
                "subject": subject,
                "html": html,
            })
            email_id = getattr(result, "id", None) or (result.get("id") if isinstance(result, dict) else "unknown")
            logger.info(f"[SUBSCRIBE] Welcome email sent: {email} (lang={lang}, id={email_id})")
            welcome_sent = True
        except Exception as e:
            logger.error(f"[SUBSCRIBE] Welcome email failed with from='{from_email}': {e}")
            # Fallback: 尝试 onboarding@resend.dev（只能发给账号拥有者）
            if "onboarding@resend.dev" not in from_email:
                try:
                    logger.info("[SUBSCRIBE] Retrying with Resend test sender...")
                    result = resend.Emails.send({
                        "from": "StockQueen <onboarding@resend.dev>",
                        "to": [email],
                        "subject": subject,
                        "html": html,
                    })
                    email_id = getattr(result, "id", None) or (result.get("id") if isinstance(result, dict) else "unknown")
                    logger.info(f"[SUBSCRIBE] Retry OK: {email} (id={email_id})")
                    welcome_sent = True
                except Exception as e2:
                    logger.error(f"[SUBSCRIBE] Retry also failed: {e2}")

        # 3) 通知管理员（不阻塞主流程）
        try:
            admin_email = os.getenv("ADMIN_NOTIFY_EMAIL", "bigbigraydeng@gmail.com")
            resend.Emails.send({
                "from": from_email,
                "to": [admin_email],
                "subject": f"New Newsletter Subscriber: {email}",
                "html": f"<p>New subscriber: <strong>{email}</strong> (lang: {lang})</p><p>Contact added: {contact_added}, Welcome sent: {welcome_sent}</p>",
            })
        except Exception:
            pass  # 管理员通知失败不影响用户

        # 即使欢迎邮件发送失败，只要用户邮箱被记录就算成功
        return JSONResponse({
            "success": True,
            "message": "Subscribed successfully",
            "details": {
                "contact_added": contact_added,
                "welcome_sent": welcome_sent,
            }
        })

    except Exception as e:
        logger.error(f"[SUBSCRIBE] Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": f"Subscription failed: {type(e).__name__}: {str(e)}"}, status_code=500)


@router.post("/api/contact", response_class=JSONResponse)
@_limiter.limit("5/minute")
async def api_contact_inquiry(request: Request):
    """
    投资者咨询表单 API
    接收表单数据，通过 Resend 发送通知邮件给管理员，并自动回复用户
    """
    import os
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        email = body.get("email", "").strip().lower()
        country = body.get("country", "").strip()
        experience = body.get("experience", "")
        capital = body.get("capital", "")
        expected_return = body.get("expectedReturn", "")
        message = body.get("message", "").strip()

        if not name or not email or "@" not in email:
            return JSONResponse({"success": False, "error": "姓名和邮箱为必填项"}, status_code=400)

        resend_api_key = os.getenv("RESEND_API_KEY", "")
        if not resend_api_key:
            logger.error("[CONTACT] RESEND_API_KEY not configured")
            return JSONResponse({"success": False, "error": "Service unavailable"}, status_code=503)

        try:
            import resend
        except ImportError as e:
            logger.error(f"[CONTACT] resend package not installed: {e}")
            return JSONResponse({"success": False, "error": "Service unavailable"}, status_code=503)

        resend.api_key = resend_api_key
        admin_email = os.getenv("CONTACT_EMAIL", "bigbigraydeng@gmail.com")
        from_email = "StockQueen <newsletter@stockqueen.tech>"

        # 1. 发送通知给管理员
        admin_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;color:#333;max-width:600px;margin:0 auto;padding:20px;">
  <div style="background:linear-gradient(135deg,#1e3a5f 0%,#0d2137 100%);padding:30px;text-align:center;border-radius:8px 8px 0 0;">
    <h1 style="color:#22d3ee;margin:0;font-size:24px;">StockQueen</h1>
    <p style="color:#94a3b8;margin:8px 0 0 0;font-size:14px;">新投资者咨询</p>
  </div>
  <div style="background:#fff;padding:30px;border:1px solid #e2e8f0;border-top:none;">
    <table style="width:100%;border-collapse:collapse;">
      <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px;font-weight:bold;width:30%;">姓名：</td><td style="padding:12px;">{name}</td></tr>
      <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px;font-weight:bold;">邮箱：</td><td style="padding:12px;">{email}</td></tr>
      <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px;font-weight:bold;">国家/地区：</td><td style="padding:12px;">{country or '未填写'}</td></tr>
      <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px;font-weight:bold;">投资经验：</td><td style="padding:12px;">{experience or '未填写'}</td></tr>
      <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px;font-weight:bold;">可用资金：</td><td style="padding:12px;">{capital or '未填写'}</td></tr>
      <tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px;font-weight:bold;">预期年化：</td><td style="padding:12px;">{expected_return or '未填写'}</td></tr>
      <tr><td style="padding:12px;font-weight:bold;">留言：</td><td style="padding:12px;">{message or '无'}</td></tr>
    </table>
    <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">
    <p style="color:#94a3b8;font-size:12px;text-align:center;margin:0;">提交时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
  </div>
</body>
</html>"""

        resend.Emails.send({
            "from": from_email,
            "to": [admin_email],
            "subject": f"[StockQueen] 新投资者咨询 - {name} ({country})",
            "html": admin_html,
        })
        logger.info(f"[CONTACT] Admin notification sent for {email}")

        # 2. 发送自动回复给用户
        user_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;line-height:1.6;color:#333;max-width:600px;margin:0 auto;padding:20px;">
  <div style="background:linear-gradient(135deg,#1e3a5f 0%,#0d2137 100%);padding:30px;text-align:center;border-radius:8px 8px 0 0;">
    <h1 style="color:#22d3ee;margin:0;font-size:24px;">StockQueen</h1>
    <p style="color:#94a3b8;margin:8px 0 0 0;font-size:14px;">瑞德资本</p>
  </div>
  <div style="background:#fff;padding:30px;border:1px solid #e2e8f0;border-top:none;">
    <h2 style="color:#0f172a;font-size:18px;margin-bottom:16px;">您好，{name}！</h2>
    <p style="color:#374151;font-size:14px;line-height:1.8;">
      感谢您向 StockQueen 提交投资咨询申请。我们已收到您的信息，团队将在 24-48 小时内与您联系。
    </p>
    <div style="background:#f0fdf4;border-radius:8px;padding:16px;margin:24px 0;">
      <p style="color:#166534;font-size:14px;margin:0;">
        <strong>您的提交信息：</strong><br>
        国家/地区：{country or '未填写'}<br>
        投资经验：{experience or '未填写'}<br>
        可用资金：{capital or '未填写'}<br>
        预期年化：{expected_return or '未填写'}
      </p>
    </div>
    <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0;">
    <p style="color:#94a3b8;font-size:12px;text-align:center;margin:0;">
      StockQueen 量化研究团队 | 瑞德资本<br>
      <a href="https://stockqueen.tech" style="color:#0891b2;text-decoration:none;">stockqueen.tech</a>
    </p>
  </div>
</body>
</html>"""

        try:
            resend.Emails.send({
                "from": from_email,
                "to": [email],
                "subject": "我们已收到您的咨询 - StockQueen",
                "html": user_html,
            })
            logger.info(f"[CONTACT] Auto-reply sent to {email}")
        except Exception as e:
            logger.warning(f"[CONTACT] Auto-reply failed (non-fatal): {e}")

        return JSONResponse({"success": True, "message": "咨询已提交，我们将尽快与您联系"})

    except Exception as e:
        logger.error(f"[CONTACT] Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        return JSONResponse({"success": False, "error": "提交失败，请稍后重试"}, status_code=500)


@router.get("/api/newsletter/unsubscribe")
async def api_newsletter_unsubscribe(request: Request):
    """取消订阅 — 通过 HMAC token 验证，无需登录"""
    import os
    from fastapi.responses import HTMLResponse
    email = request.query_params.get("email", "").strip().lower()
    token = request.query_params.get("token", "")

    # 验证 token
    import hmac, hashlib
    unsub_secret = os.getenv("UNSUB_SECRET", "stockqueen-unsub-2026")
    expected = hmac.new(unsub_secret.encode(), email.encode(), hashlib.sha256).hexdigest()[:32]

    if not email or not token or not hmac.compare_digest(token, expected):
        return HTMLResponse("""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Error</title></head>
        <body style="font-family:sans-serif;text-align:center;padding:60px;background:#f8fafc;">
        <h1 style="color:#dc2626;">Invalid Link</h1>
        <p style="color:#64748b;">This unsubscribe link is invalid or expired.</p>
        </body></html>""", status_code=400)

    # 在 Resend Audience 中标记为取消订阅
    unsubscribed = False
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY", "")
        audience_id = os.getenv("RESEND_AUDIENCE_ID", "")
        if audience_id:
            # 先找到联系人 ID
            contacts_resp = resend.Contacts.list(audience_id=audience_id)
            contacts = contacts_resp.get("data", []) if isinstance(contacts_resp, dict) else contacts_resp
            for c in contacts:
                c_email = c.get("email", "") if isinstance(c, dict) else getattr(c, "email", "")
                c_id = c.get("id", "") if isinstance(c, dict) else getattr(c, "id", "")
                if c_email.lower() == email and c_id:
                    resend.Contacts.update({
                        "audience_id": audience_id,
                        "id": c_id,
                        "unsubscribed": True,
                    })
                    unsubscribed = True
                    logger.info(f"[UNSUBSCRIBE] ✅ {email} marked as unsubscribed")
                    break
    except Exception as e:
        logger.error(f"[UNSUBSCRIBE] Error: {e}")

    # 返回确认页面
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Unsubscribed</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;text-align:center;padding:60px;background:#f8fafc;">
    <div style="max-width:480px;margin:0 auto;background:#fff;padding:40px;border-radius:16px;box-shadow:0 4px 12px rgba(0,0,0,0.08);">
        <h1 style="color:#22d3ee;font-size:28px;margin-bottom:8px;">StockQueen</h1>
        <h2 style="color:#0f172a;margin-bottom:16px;">Successfully Unsubscribed</h2>
        <p style="color:#64748b;font-size:14px;line-height:1.8;">
            <strong>{email}</strong> has been removed from our mailing list.<br>
            You will no longer receive weekly newsletters.
        </p>
        <p style="color:#94a3b8;font-size:12px;margin-top:24px;">
            Changed your mind? <a href="https://stockqueen.tech/subscribe.html" style="color:#4f46e5;">Re-subscribe here</a>
        </p>
    </div>
</body></html>""")


@router.get("/api/newsletter/health", response_class=JSONResponse)
async def api_newsletter_health(request: Request):
    """Newsletter 服务健康检查 — 诊断 Resend 配置"""
    import os
    checks = {}
    checks["resend_api_key_set"] = bool(os.getenv("RESEND_API_KEY", ""))
    checks["resend_api_key_prefix"] = os.getenv("RESEND_API_KEY", "")[:8] + "..." if os.getenv("RESEND_API_KEY", "") else ""
    checks["resend_audience_id_set"] = bool(os.getenv("RESEND_AUDIENCE_ID", ""))
    checks["resend_audience_id"] = os.getenv("RESEND_AUDIENCE_ID", "")
    checks["newsletter_from"] = os.getenv("NEWSLETTER_FROM", "(not set, will use newsletter@stockqueen.tech)")

    try:
        import resend
        checks["resend_package"] = f"installed v{resend.__version__}"
    except ImportError:
        checks["resend_package"] = "NOT INSTALLED"

    # 尝试列出 audiences 来验证 API key 是否有效
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY", "")
        audiences = resend.Audiences.list()
        checks["api_key_valid"] = True
        checks["audiences_raw_type"] = type(audiences).__name__
        # SDK v2 返回 dict 而不是对象
        if isinstance(audiences, dict):
            data = audiences.get("data", [])
        else:
            data = getattr(audiences, "data", [])
        checks["audiences"] = [
            {"id": a.get("id", "?") if isinstance(a, dict) else getattr(a, "id", "?"),
             "name": a.get("name", "?") if isinstance(a, dict) else getattr(a, "name", "?")}
            for a in data
        ]
    except Exception as e:
        checks["api_key_valid"] = False
        checks["api_key_error"] = f"{type(e).__name__}: {str(e)}"

    return JSONResponse(checks)


# ==================================================================
# 破浪实验室 C3：Newsletter 管理面板（HTMX 局部）
# ==================================================================

@router.get("/htmx/lab-c3-status", response_class=HTMLResponse)
async def htmx_lab_c3_status(request: Request):
    """C3 订阅者统计 + 配置健康检查"""
    import os
    stats = {
        "resend_ok":      False,
        "stripe_ok":      False,
        "audience_id":    os.getenv("RESEND_AUDIENCE_ID", ""),
        "total":          0,
        "paid":           0,
        "free":           0,
        "stripe_monthly": os.getenv("STRIPE_PRICE_MONTHLY", ""),
        "stripe_webhook": bool(os.getenv("STRIPE_WEBHOOK_SECRET", "")),
    }

    # --- Resend 订阅者统计 ---
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY", "")
        audience_id = stats["audience_id"]
        if resend.api_key and audience_id:
            contacts_resp = resend.Contacts.list(audience_id=audience_id)
            contacts = contacts_resp.get("data", []) if isinstance(contacts_resp, dict) else getattr(contacts_resp, "data", [])
            stats["total"] = len(contacts)
            stats["paid"]  = sum(1 for c in contacts
                                 if ("paid" in (c.get("last_name", "") if isinstance(c, dict) else getattr(c, "last_name", ""))))
            stats["free"]  = stats["total"] - stats["paid"]
            stats["resend_ok"] = True
    except Exception as e:
        stats["resend_error"] = str(e)

    # --- Stripe 健康检查 ---
    try:
        import stripe as _stripe
        _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if _stripe.api_key:
            _stripe.Balance.retrieve()   # 最轻量的 API 验证
            stats["stripe_ok"] = True
    except Exception as e:
        stats["stripe_error"] = str(e)

    return _tpl("partials/_lab_c3_status.html", {"request": request, "s": stats})


@router.post("/htmx/lab-newsletter-preview", response_class=HTMLResponse)
async def htmx_lab_newsletter_preview(request: Request):
    """即时生成本周周报预览（free-zh 版本）"""
    try:
        import sys, os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        api_base = os.getenv("STOCKQUEEN_API_BASE", "https://stockqueen-api.onrender.com")
        from scripts.newsletter.data_fetcher import DataFetcher
        from scripts.newsletter.renderer import NewsletterRenderer
        fetcher = DataFetcher(api_base=api_base)
        data    = await fetcher.fetch_all()
        renderer = NewsletterRenderer()
        newsletters = renderer.render_all(data)
        preview_html = newsletters.get("free-zh") or newsletters.get("free-en") or "<p>无内容</p>"

        return HTMLResponse(f"""
<div class="bg-white rounded-lg overflow-hidden" style="max-height:600px;overflow-y:auto;">
  <div class="bg-yellow-50 border-b border-yellow-200 px-4 py-2 text-xs text-yellow-700 font-medium">
    📧 预览：免费版周报（zh）— 仅展示，未发送
  </div>
  <iframe srcdoc="{preview_html.replace(chr(34), '&quot;').replace(chr(39), '&#39;')}"
          style="width:100%;height:550px;border:none;"></iframe>
</div>""")
    except Exception as e:
        return HTMLResponse(f'<div class="text-sq-red p-4 text-sm">生成预览失败：{e}</div>')


@router.post("/htmx/lab-send-test", response_class=HTMLResponse)
async def htmx_lab_send_test(request: Request):
    """发送测试周报到指定邮箱"""
    form = await request.form()
    test_email = (form.get("test_email") or "").strip()
    if not test_email or "@" not in test_email:
        return HTMLResponse('<div class="text-sq-red text-sm p-3">请输入有效邮箱</div>')
    try:
        import sys, os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        api_base = os.getenv("STOCKQUEEN_API_BASE", "https://stockqueen-api.onrender.com")
        from scripts.newsletter.data_fetcher import DataFetcher
        from scripts.newsletter.renderer import NewsletterRenderer
        from scripts.newsletter.sender import NewsletterSender

        fetcher = DataFetcher(api_base=api_base)
        data    = await fetcher.fetch_all()
        newsletters = NewsletterRenderer().render_all(data)
        sender  = NewsletterSender()

        if not sender.validate_config():
            return HTMLResponse('<div class="text-yellow-400 text-sm p-3">⚠️ RESEND_API_KEY 未配置，无法发送</div>')

        import resend
        resend.api_key = os.getenv("RESEND_API_KEY", "")
        from_email = os.getenv("NEWSLETTER_FROM", "StockQueen <newsletter@stockqueen.tech>")
        resend.Emails.send({
            "from":    from_email,
            "to":      [test_email],
            "subject": f"[测试] StockQueen 周报 W{data.get('week_number', '?')} {data.get('year', '')}",
            "html":    newsletters.get("free-zh") or newsletters.get("free-en", "<p>无内容</p>"),
        })
        return HTMLResponse(f'<div class="text-sq-green text-sm p-3">✅ 测试邮件已发送至 {test_email}</div>')
    except Exception as e:
        return HTMLResponse(f'<div class="text-sq-red text-sm p-3">发送失败：{e}</div>')


def _welcome_email_en(email: str) -> str:
    """英文欢迎邮件 HTML"""
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 0;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">Welcome to Our Newsletter</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">Welcome Aboard! 🎉</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8;">
            Thank you for subscribing to the StockQueen newsletter. You'll receive our weekly quantitative strategy reports every Saturday.
        </p>
        <div style="background: #f0fdf4; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="color: #166534; font-size: 14px; margin: 0;">
                <strong>What you'll get:</strong><br>
                • Weekly strategy performance vs SPY/QQQ<br>
                • Market regime analysis (Bull/Bear/Choppy)<br>
                • Trade history and position updates<br>
                • AI-powered market insights
            </p>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.tech/weekly-report/"
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%);
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px;
                      font-weight: 600; font-size: 14px;">
                View Latest Report
            </a>
        </div>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center;">
            StockQueen Quantitative Research | Rayde Capital<br>
            <a href="https://stockqueen.tech" style="color: #0891b2;">stockqueen.tech</a>
        </p>
    </div>
</body></html>"""


def _welcome_email_zh(email: str) -> str:
    """中文欢迎邮件 HTML"""
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 0;">
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%); padding: 30px; text-align: center;">
        <h1 style="color: #22d3ee; margin: 0; font-size: 28px;">StockQueen</h1>
        <p style="color: #94a3b8; margin: 8px 0 0 0; font-size: 14px;">欢迎订阅量化策略周报</p>
    </div>
    <div style="background: #fff; padding: 30px; border: 1px solid #e2e8f0; border-top: none;">
        <h2 style="color: #0f172a; font-size: 20px; margin-bottom: 16px;">欢迎加入！🎉</h2>
        <p style="color: #374151; font-size: 14px; line-height: 1.8;">
            感谢您订阅 StockQueen 量化策略周报。您将在每周六收到我们的策略报告。
        </p>
        <div style="background: #f0fdf4; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="color: #166534; font-size: 14px; margin: 0;">
                <strong>您将获得：</strong><br>
                • 每周策略收益 vs SPY/QQQ 对比<br>
                • 市场状态分析（牛市/熊市/震荡市）<br>
                • 交易记录和持仓更新<br>
                • AI 驱动的市场洞察
            </p>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://stockqueen.tech/weekly-report/"
               style="display: inline-block; background: linear-gradient(135deg, #4f46e5 0%, #0891b2 100%);
                      color: white; padding: 14px 32px; text-decoration: none; border-radius: 8px;
                      font-weight: 600; font-size: 14px;">
                查看最新报告
            </a>
        </div>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
        <p style="color: #94a3b8; font-size: 12px; text-align: center;">
            StockQueen 量化研究团队 | 瑞德资本<br>
            <a href="https://stockqueen.tech" style="color: #0891b2;">stockqueen.tech</a>
        </p>
    </div>
</body></html>"""


# ==================== 策略矩阵 ====================

@router.get("/strategy-matrix", response_class=HTMLResponse)
async def strategy_matrix_page(request: Request):
    """策略矩阵仪表盘 — 多策略组合分析可视化"""
    return _tpl("strategy_matrix.html", {"request": request})


@router.get("/api/strategy-matrix/results", response_class=JSONResponse)
async def api_strategy_matrix_results(request: Request):
    """读取策略矩阵回测结果：优先从 Supabase cache_store 读取，本地文件作 fallback 并同步写回 DB"""
    import os
    import glob as _glob

    _SM_CACHE_KEY = "strategy_matrix:results"

    # ── L1: 优先读 Supabase cache_store ──────────────────────────────
    cached = _cache_get(_SM_CACHE_KEY)
    if cached:
        return JSONResponse(cached)

    # ── L2: fallback → 本地 JSON 文件（本地开发环境）────────────────
    results_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "scripts", "strategy_matrix_results"
    )

    def _load_latest(prefix: str) -> dict:
        pattern = os.path.join(results_dir, f"{prefix}_*.json")
        files = sorted(_glob.glob(pattern))
        if not files:
            return {}
        try:
            with open(files[-1], "rb") as f:
                raw = f.read()
            # 容错：先尝试 utf-8，失败则替换非法字节
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            text = text.replace(": NaN", ": null").replace(":NaN", ":null")
            return json.loads(text)
        except Exception as e:
            logger.warning(f"strategy_matrix: 读取 {files[-1]} 失败: {e}")
            return {}

    mr_data = _load_latest("mean_reversion_standalone")
    ed_data = _load_latest("event_driven_standalone")
    alloc_data = _load_latest("allocation_schemes_comparison")
    corr_data = _load_latest("correlation_analysis")

    # 从 allocation 数据提取各方案汇总指标
    alloc_summary = {}
    for scheme_name, scheme in alloc_data.items():
        p = scheme.get("portfolio", {})
        sub = scheme.get("sub_strategies", {})
        alloc_summary[scheme_name] = {
            "allocation": scheme.get("allocation", {}),
            "cumulative_return": p.get("cumulative_return"),
            "annualized_return": p.get("annualized_return"),
            "sharpe_ratio": p.get("sharpe_ratio"),
            "max_drawdown": p.get("max_drawdown"),
            "win_rate": p.get("win_rate"),
            "sub_v4": sub.get("v4", {}),
            "sub_mr": sub.get("mean_reversion", {}),
            "sub_ed": sub.get("event_driven", {}),
        }

    payload = {
        "alloc_summary": alloc_summary,
        "correlation": corr_data.get("correlations", {}),
        "period": corr_data.get("period", "2018-01-01→2024-12-31"),
        "mr_summary": {
            yr.split(" ")[0]: {
                "cumulative_return": v.get("cumulative_return"),
                "sharpe_ratio": v.get("sharpe_ratio"),
                "max_drawdown": v.get("max_drawdown"),
                "win_rate": v.get("win_rate"),
                "total_trades": v.get("total_trades"),
            }
            for yr, v in mr_data.items()
            if yr.split(" ")[0].isdigit()
        },
        "ed_summary": {
            yr.split(" ")[0]: {
                "cumulative_return": v.get("cumulative_return"),
                "sharpe_ratio": v.get("sharpe_ratio"),
                "max_drawdown": v.get("max_drawdown"),
                "win_rate": v.get("win_rate"),
                "total_trades": v.get("total_trades"),
            }
            for yr, v in ed_data.items()
            if yr.split(" ")[0].isdigit()
        },
    }

    # 本地文件读取成功时同步写入 Supabase，方便后续生产环境直接读取
    if alloc_summary or payload["mr_summary"] or payload["ed_summary"]:
        _cache_set(_SM_CACHE_KEY, payload, _BACKTEST_TTL)

    return JSONResponse(payload)


# ==================================================================
# Dynamic Universe — Full Page + HTMX Table + Background Refresh
# ==================================================================

# File-based status for universe refresh (survives process restarts/redeploys)
_UNIVERSE_STATUS_PATH = _os.path.join(_CACHE_DIR, "universe", "refresh_status.json")


def _universe_read_status() -> dict:
    """Read refresh status from file; auto-clears if stale (>2 hours)."""
    import json as _j, datetime as _dt
    if not _os.path.exists(_UNIVERSE_STATUS_PATH):
        return {"running": False}
    try:
        with open(_UNIVERSE_STATUS_PATH) as f:
            data = _j.load(f)
        if data.get("running"):
            started = data.get("started_at", "")
            if started:
                age = (_dt.datetime.utcnow() - _dt.datetime.fromisoformat(started)).total_seconds()
                if age > 7200:  # 2 hours → treat as crashed
                    data["running"] = False
                    data["error"] = "任务超时（>2小时），请重新触发"
                    with open(_UNIVERSE_STATUS_PATH, "w") as f:
                        _j.dump(data, f)
        return data
    except Exception:
        return {"running": False}


def _universe_write_status(running: bool, error: str = None):
    """Write refresh status to file."""
    import json as _j, datetime as _dt
    _os.makedirs(_os.path.dirname(_UNIVERSE_STATUS_PATH), exist_ok=True)
    if running:
        data = {"running": True, "started_at": _dt.datetime.utcnow().isoformat(), "error": None}
    else:
        existing: dict = {}
        try:
            with open(_UNIVERSE_STATUS_PATH) as f:
                existing = _j.load(f)
        except Exception:
            pass
        data = {"running": False, "started_at": existing.get("started_at"), "error": error}
    with open(_UNIVERSE_STATUS_PATH, "w") as f:
        _j.dump(data, f)


@router.get("/universe", response_class=HTMLResponse)
async def page_universe(request: Request):
    """动态选股池管理页面"""
    if getattr(request.state, "is_guest", True):
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/dashboard", status_code=302)

    from app.services.universe_service import UniverseService
    svc = UniverseService()
    data = svc.get_current_universe_full()

    summary = {
        "count": 0,
        "timestamp": None,
        "age_days": None,
        "filters": {},
        "step1": 0,
        "step2": 0,
        "elapsed": None,
    }
    if data:
        import datetime
        summary["count"] = data.get("final_count", len(data.get("tickers", [])))
        ts = data.get("timestamp", "")
        summary["timestamp"] = ts[:16].replace("T", " ") if ts else None
        if ts:
            try:
                age = (datetime.date.today() - datetime.date.fromisoformat(ts[:10])).days
                summary["age_days"] = age
            except Exception:
                pass
        summary["filters"] = data.get("filters", {})
        summary["step1"] = data.get("step1_candidates", 0)
        summary["step2"] = data.get("step2_passed", 0)
        summary["elapsed"] = data.get("elapsed_seconds")

    return _tpl("universe.html", {
        "request": request,
        "summary": summary,
        "refresh_running": _universe_read_status().get("running", False),
    })


@router.get("/htmx/universe-table", response_class=HTMLResponse)
async def htmx_universe_table(
    request: Request,
    search: str = "",
    sector: str = "",
    page: int = 1,
):
    """选股池 ticker 列表（分页 + 搜索 + 行业过滤）"""
    from app.services.universe_service import UniverseService
    data = UniverseService().get_current_universe_full()
    if not data or not data.get("tickers"):
        return HTMLResponse(
            '<div class="text-center text-gray-500 py-12 text-sm">选股池暂无数据，请先刷新选股池</div>'
        )

    tickers = data["tickers"]

    # Filter
    if search:
        q = search.upper()
        tickers = [t for t in tickers if q in t["ticker"] or q in t.get("name", "").upper()]
    if sector:
        tickers = [t for t in tickers if t.get("sector", "") == sector]

    # Pagination
    page_size = 50
    total = len(tickers)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    page_tickers = tickers[start:start + page_size]

    rows = ""
    for t in page_tickers:
        mcap = t.get("market_cap", 0)
        mcap_str = f"${mcap/1e9:.1f}B" if mcap >= 1e9 else f"${mcap/1e6:.0f}M"
        vol = t.get("avg_volume", 0)
        vol_str = f"{vol/1e6:.1f}M" if vol >= 1e6 else f"{vol/1e3:.0f}K"
        price = t.get("price", 0)
        rows += (
            f'<tr class="border-t border-sq-border hover:bg-sq-border/30 transition-colors">'
            f'<td class="px-4 py-2 font-mono text-sq-accent font-semibold">{t["ticker"]}</td>'
            f'<td class="px-4 py-2 text-gray-300 text-sm max-w-[200px] truncate">{t.get("name","")}</td>'
            f'<td class="px-4 py-2 text-gray-400 text-sm">{t.get("exchange","")}</td>'
            f'<td class="px-4 py-2 text-gray-400 text-xs">{t.get("sector","")}</td>'
            f'<td class="px-4 py-2 text-right text-white font-mono text-sm">${price:.2f}</td>'
            f'<td class="px-4 py-2 text-right text-gray-300 text-sm">{mcap_str}</td>'
            f'<td class="px-4 py-2 text-right text-gray-400 text-sm">{vol_str}</td>'
            f'<td class="px-4 py-2 text-gray-500 text-xs">{t.get("ipoDate","")}</td>'
            f'</tr>'
        )

    # Pagination controls
    base_params = f"search={search}&sector={sector}"
    prev_btn = (
        f'<button hx-get="/htmx/universe-table?{base_params}&page={page-1}" '
        f'hx-target="#universe-table" hx-swap="innerHTML" '
        f'class="px-3 py-1 rounded border border-sq-border text-gray-400 hover:text-white hover:bg-sq-border text-sm transition-colors">'
        f'← 上页</button>'
        if page > 1 else
        '<button disabled class="px-3 py-1 rounded border border-sq-border text-gray-600 text-sm cursor-not-allowed">← 上页</button>'
    )
    next_btn = (
        f'<button hx-get="/htmx/universe-table?{base_params}&page={page+1}" '
        f'hx-target="#universe-table" hx-swap="innerHTML" '
        f'class="px-3 py-1 rounded border border-sq-border text-gray-400 hover:text-white hover:bg-sq-border text-sm transition-colors">'
        f'下页 →</button>'
        if page < total_pages else
        '<button disabled class="px-3 py-1 rounded border border-sq-border text-gray-600 text-sm cursor-not-allowed">下页 →</button>'
    )

    html = f"""
<div class="overflow-x-auto">
  <table class="w-full text-sm">
    <thead>
      <tr class="text-gray-500 text-xs uppercase tracking-wider">
        <th class="px-4 py-2 text-left">Ticker</th>
        <th class="px-4 py-2 text-left">名称</th>
        <th class="px-4 py-2 text-left">交易所</th>
        <th class="px-4 py-2 text-left">行业</th>
        <th class="px-4 py-2 text-right">股价</th>
        <th class="px-4 py-2 text-right">市值</th>
        <th class="px-4 py-2 text-right">日均量</th>
        <th class="px-4 py-2 text-left">IPO</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<div class="flex items-center justify-between px-4 py-3 border-t border-sq-border">
  <span class="text-xs text-gray-500">共 {total} 只 · 第 {page}/{total_pages} 页</span>
  <div class="flex gap-2">{prev_btn}{next_btn}</div>
</div>"""
    return HTMLResponse(html)


@router.post("/htmx/admin/refresh-universe", response_class=HTMLResponse)
async def htmx_admin_refresh_universe(request: Request, background_tasks: BackgroundTasks):
    """触发动态选股池刷新（后台任务，不阻塞）"""
    if getattr(request.state, "is_guest", True):
        return HTMLResponse('<div class="text-sq-red text-sm">无权限</div>', status_code=403)

    if _universe_read_status().get("running"):
        return HTMLResponse(
            '<div class="text-sq-gold text-sm flex items-center gap-2">'
            '<span class="animate-pulse">●</span> 刷新正在进行中，请稍候...</div>'
        )

    async def _do_refresh():
        _universe_write_status(True)
        try:
            from app.services.universe_service import UniverseService
            await UniverseService().refresh_universe(concurrency=5)
            logger.info("Universe refresh completed via admin page")
            _universe_write_status(False)
        except Exception as e:
            logger.error(f"Universe refresh failed: {e}")
            _universe_write_status(False, error=str(e))

    background_tasks.add_task(_do_refresh)

    return HTMLResponse(
        '<div class="text-sq-green text-sm flex items-center gap-2">'
        '<span class="animate-pulse">●</span>'
        ' 刷新已启动，预计需要 30-60 分钟，左下角可跟踪进度。</div>'
    )


@router.get("/htmx/universe-refresh-badge", response_class=HTMLResponse)
async def htmx_universe_refresh_badge():
    """全局选股池刷新进度角标（每30s轮询，返回内容注入到 base.html 固定容器）"""
    import datetime as _dt
    status = _universe_read_status()
    if not status.get("running"):
        # 如有错误，短暂显示失败提示（仅当刚结束时）
        err = status.get("error")
        if err:
            return HTMLResponse(
                f'<div class="flex items-center gap-2 px-4 py-2.5 bg-sq-card border border-sq-red/40 '
                f'text-sq-red rounded-xl shadow-lg text-sm">'
                f'<span>✕</span><span>选股池刷新失败</span></div>'
            )
        return HTMLResponse("")

    elapsed_html = ""
    started = status.get("started_at", "")
    if started:
        try:
            elapsed = (_dt.datetime.utcnow() - _dt.datetime.fromisoformat(started)).total_seconds()
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            elapsed_str = f"{mins}分{secs:02d}秒" if mins else f"{secs}秒"
            elapsed_html = f'<span class="text-gray-400 text-xs">· {elapsed_str}</span>'
        except Exception:
            pass

    return HTMLResponse(
        f'<a href="/universe" '
        f'class="flex items-center gap-2 px-4 py-2.5 bg-sq-card border border-sq-accent/50 '
        f'text-sq-accent rounded-xl shadow-lg hover:bg-sq-accent/10 transition-colors text-sm font-medium">'
        f'<span class="inline-block w-4 h-4 border-2 border-sq-accent border-t-transparent rounded-full animate-spin"></span>'
        f'<span>选股池刷新中</span>'
        f'{elapsed_html}'
        f'</a>'
    )


# =====================================================================
# Intraday (铃铛) Full Page + HTMX Endpoints
# =====================================================================


@router.get("/intraday", response_class=HTMLResponse)
async def intraday_page(request: Request):
    """铃铛策略 — 日内杠杆交易监控页面"""
    quote = _get_daily_quote()
    pt = float(settings.intraday_daily_profit_target_usd)
    return _tpl("intraday.html", {
        "request": request,
        "quote": quote,
        "intraday_profit_target_usd": pt,
        "intraday_profit_target_label": f"${pt:,.0f}",
    })


@router.get("/htmx/intraday-hero", response_class=HTMLResponse)
async def htmx_intraday_hero(request: Request):
    """HTMX: 铃铛 Hero 卡片 — 利润进度条 + 账户概览"""
    try:
        import asyncio as _aio
        from app.config.intraday_runtime import get_max_total_exposure
        from app.services.order_service import get_tiger_trade_client

        exp_cap = get_max_total_exposure()
        tiger = get_tiger_trade_client("leverage")
        assets = await _aio.wait_for(tiger.get_account_assets(), timeout=10.0)
        positions = await _aio.wait_for(tiger.get_positions(), timeout=10.0)

        if not assets:
            return HTMLResponse(
                '<div class="text-center text-gray-500 py-6">杠杆账户未连接</div>'
            )

        nlv = assets.get("net_liquidation", 0)
        cash = assets.get("cash", 0)
        buying_power = assets.get("buying_power", 0)

        # Calculate daily P&L
        initial_capital = 1_000_000  # Paper trading initial
        acct_str = str(settings.tiger_account_2 or "")
        is_paper = acct_str.startswith("214")
        if not is_paper:
            initial_capital = nlv  # For real account, use current as base

        daily_pnl = nlv - initial_capital
        daily_pnl_pct = (daily_pnl / initial_capital * 100) if initial_capital > 0 else 0

        # Profit target progress（与铃铛页 Hero 一致，见 settings.intraday_daily_profit_target_usd）
        profit_target = float(settings.intraday_daily_profit_target_usd)
        progress_pct = max(0, min(100, (daily_pnl / profit_target * 100))) if profit_target > 0 else 0
        pt_label = f"${profit_target:,.0f}"
        tick_a = f"${profit_target * 0.25:,.0f}"
        tick_b = f"${profit_target * 0.5:,.0f}"
        tick_c = f"${profit_target * 0.75:,.0f}"
        tick_d = pt_label

        pnl_color = "text-sq-green" if daily_pnl >= 0 else "text-sq-red"
        pnl_sign = "+" if daily_pnl >= 0 else ""
        bar_color = "bg-cyan-500" if daily_pnl >= 0 else "bg-red-500"

        # Position metrics
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
        total_market_value = sum(p.get("market_value", 0) for p in positions)
        ur_color = "text-sq-green" if total_unrealized >= 0 else "text-sq-red"
        ur_sign = "+" if total_unrealized >= 0 else ""

        # Leverage ratio
        leverage_ratio = (total_market_value / nlv * 100) if nlv > 0 else 0

        # Mode badge update
        mode = "模拟盘" if is_paper else "实盘"

        html = f"""
        <!-- Mode badge OOB update -->
        <span id="intraday-mode-badge" hx-swap-oob="outerHTML"
              class="px-2 py-0.5 rounded-full text-[10px] {'bg-amber-900/60 text-amber-300 border border-amber-800/50' if is_paper else 'bg-red-900/60 text-red-300 border border-red-800/50'}">
            {mode} · 敞口上限 {exp_cap:.1f}x
        </span>

        <!-- Big NLV -->
        <div class="flex items-center justify-between mb-3">
            <div>
                <div class="text-3xl lg:text-4xl font-bold text-white font-mono tracking-tight">
                    ${nlv:,.2f}
                </div>
                <div class="flex items-center gap-3 mt-1">
                    <span class="text-sm font-mono font-semibold {pnl_color}">{pnl_sign}${daily_pnl:,.2f}</span>
                    <span class="text-xs {pnl_color}">({pnl_sign}{daily_pnl_pct:.2f}%)</span>
                </div>
            </div>
            <div class="text-right">
                <div class="text-xs text-gray-500">未实现盈亏</div>
                <div class="text-lg font-mono font-bold {ur_color}">{ur_sign}${total_unrealized:,.2f}</div>
            </div>
        </div>

        <!-- Profit Progress Bar -->
        <div class="mb-3">
            <div class="flex items-center justify-between mb-1">
                <span class="text-xs text-gray-400">利润进度</span>
                <span class="text-xs font-mono {'text-sq-gold' if progress_pct >= 100 else 'text-cyan-400'}">{pnl_sign}${daily_pnl:,.0f} / {pt_label}</span>
            </div>
            <div class="h-3 bg-gray-800 rounded-full overflow-hidden">
                <div class="{bar_color} h-full rounded-full transition-all duration-1000 relative"
                     style="width: {progress_pct:.1f}%">
                    {'<div class="absolute inset-0 bg-gradient-to-r from-transparent to-white/20 animate-pulse"></div>' if progress_pct > 0 and progress_pct < 100 else ''}
                </div>
            </div>
            <div class="flex justify-between mt-1">
                <span class="text-[10px] text-gray-600">$0</span>
                <span class="text-[10px] text-gray-600">{tick_a}</span>
                <span class="text-[10px] text-gray-600">{tick_b}</span>
                <span class="text-[10px] text-gray-600">{tick_c}</span>
                <span class="text-[10px] text-sq-gold font-bold">{tick_d}</span>
            </div>
        </div>

        <!-- Sub-metrics -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
                <div class="text-xs text-gray-500 mb-0.5">持仓市值</div>
                <div class="text-base font-mono text-white">${total_market_value:,.2f}</div>
            </div>
            <div>
                <div class="text-xs text-gray-500 mb-0.5">现金余额</div>
                <div class="text-base font-mono text-white">${cash:,.2f}</div>
            </div>
            <div>
                <div class="text-xs text-gray-500 mb-0.5">购买力</div>
                <div class="text-base font-mono text-white">${buying_power:,.2f}</div>
            </div>
            <div>
                <div class="text-xs text-gray-500 mb-0.5">杠杆使用率</div>
                <div class="text-base font-mono {'text-sq-green' if leverage_ratio < 100 else 'text-cyan-400' if leverage_ratio < 150 else 'text-sq-gold'}">{leverage_ratio:.1f}%</div>
            </div>
        </div>
        """
        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Intraday hero error: {e}")
        return HTMLResponse(
            f'<div class="text-center text-gray-500 py-6">杠杆账户加载失败: {str(e)[:80]}</div>'
        )


@router.get("/htmx/intraday-gauge", response_class=HTMLResponse)
async def htmx_intraday_gauge(request: Request):
    """HTMX: 铃铛风控仪表盘（维持率/日P&L/头寸数/PDT）"""
    gauge_type = request.query_params.get("type", "maintenance")

    try:
        import asyncio as _aio
        from app.services.order_service import get_tiger_trade_client

        tiger = get_tiger_trade_client("leverage")
        assets = await _aio.wait_for(tiger.get_account_assets(), timeout=10.0)
        positions = await _aio.wait_for(tiger.get_positions(), timeout=10.0)

        nlv = assets.get("net_liquidation", 0) if assets else 0
        cash = assets.get("cash", 0) if assets else 0
        buying_power = assets.get("buying_power", 0) if assets else 0
        total_market_value = sum(p.get("market_value", 0) for p in positions) if positions else 0

        initial_capital = 1_000_000
        daily_pnl = nlv - initial_capital
        daily_pnl_pct = (daily_pnl / initial_capital * 100) if initial_capital > 0 else 0

        if gauge_type == "maintenance":
            # Maintenance ratio = equity / market_value
            ratio = (nlv / total_market_value * 100) if total_market_value > 0 else 100.0
            if ratio > 80:
                color, status = "text-sq-green", "安全"
            elif ratio > 50:
                color, status = "text-cyan-400", "正常"
            elif ratio > 40:
                color, status = "text-sq-gold", "注意"
            else:
                color, status = "text-sq-red", "危险!"

            return HTMLResponse(
                f'<div class="text-2xl font-mono font-bold {color}">{ratio:.1f}%</div>'
                f'<div class="text-[10px] {color} mt-0.5">{status}</div>'
            )

        elif gauge_type == "daily_pnl":
            pnl_color = "text-sq-green" if daily_pnl >= 0 else "text-sq-red"
            pnl_sign = "+" if daily_pnl >= 0 else ""
            return HTMLResponse(
                f'<div class="text-2xl font-mono font-bold {pnl_color}">{pnl_sign}${daily_pnl:,.0f}</div>'
                f'<div class="text-[10px] {pnl_color} mt-0.5">{pnl_sign}{daily_pnl_pct:.2f}%</div>'
            )

        elif gauge_type == "positions":
            from app.config.intraday_config import IntradayConfig as _IC
            _max_pos = int(getattr(_IC, "MAX_CONCURRENT_POSITIONS", 10) or 10)
            pos_count = len(positions) if positions else 0
            color = "text-white" if pos_count <= _max_pos else "text-sq-gold"
            return HTMLResponse(
                f'<div class="text-2xl font-mono font-bold {color}">{pos_count}</div>'
                f'<div class="text-[10px] text-gray-500 mt-0.5">最大 {_max_pos} 个</div>'
                f'<script>document.getElementById("lev-pos-count").textContent="{pos_count} 个";</script>'
            )

        elif gauge_type == "pdt":
            # PDT count from intraday_scores table (count today's round-trip trades)
            try:
                from app.services.db_service import get_supabase
                sb = get_supabase()
                from datetime import datetime, timedelta
                five_days_ago = (datetime.utcnow() - timedelta(days=5)).isoformat()
                result = sb.table("intraday_trades").select("id").gte("traded_at", five_days_ago).eq("trade_type", "round_trip").execute()
                pdt_count = len(result.data) if result.data else 0
            except Exception:
                pdt_count = 0

            color = "text-sq-green" if pdt_count < 2 else ("text-sq-gold" if pdt_count < 3 else "text-sq-red")
            return HTMLResponse(
                f'<div class="text-2xl font-mono font-bold {color}">{pdt_count}/3</div>'
                f'<div class="text-[10px] {"text-sq-green" if pdt_count < 3 else "text-sq-red"} mt-0.5">{"安全" if pdt_count < 3 else "达到上限!"}</div>'
            )

        return HTMLResponse('<div class="text-gray-500">--</div>')
    except Exception as e:
        logger.error(f"Intraday gauge ({gauge_type}) error: {e}")
        return HTMLResponse(f'<div class="text-2xl font-mono font-bold text-gray-600">--</div>')


@router.get("/htmx/intraday-trade-log", response_class=HTMLResponse)
async def htmx_intraday_trade_log(request: Request):
    """HTMX: 铃铛今日交易记录"""
    try:
        from app.services.db_service import get_supabase
        from datetime import datetime
        sb = get_supabase()

        today = datetime.utcnow().strftime("%Y-%m-%d")
        result = sb.table("intraday_trades").select("*").gte("traded_at", today).order("traded_at", desc=True).limit(50).execute()

        trades = result.data if result.data else []
        if not trades:
            return HTMLResponse(
                '<div class="text-center text-gray-500 py-8 text-sm">'
                '今日暂无交易 — 等待盘中评分触发</div>'
            )

        html = ""
        for t in trades:
            ticker = t.get("ticker", "")
            trade_type = t.get("trade_type", "entry")
            price = float(t.get("price", 0) or 0)
            qty = int(t.get("quantity", 0) or 0)
            pnl = float(t.get("pnl", 0) or 0)
            reason = t.get("reason", "")
            traded_at = t.get("traded_at", "")[:16]

            if trade_type == "entry":
                icon = '<span class="text-sq-green">BUY</span>'
                detail = f'${price:.2f} x {qty}'
            else:
                icon = '<span class="text-sq-red">SELL</span>'
                pnl_c = "text-sq-green" if pnl >= 0 else "text-sq-red"
                pnl_s = "+" if pnl >= 0 else ""
                detail = f'<span class="{pnl_c}">{pnl_s}${pnl:,.0f}</span>'

            html += f"""
            <div class="flex items-center justify-between py-2 border-b border-gray-800/50 text-xs">
                <div class="flex items-center gap-2">
                    <span class="font-mono font-bold text-white">{ticker}</span>
                    {icon}
                </div>
                <div class="text-right">
                    <div class="font-mono text-gray-300">{detail}</div>
                    <div class="text-[10px] text-gray-600">{traded_at}</div>
                </div>
            </div>"""

        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Intraday trade log error: {e}")
        return HTMLResponse(
            '<div class="text-center text-gray-500 py-6 text-sm">交易记录加载失败</div>'
        )


@router.get("/htmx/intraday-risk-events", response_class=HTMLResponse)
async def htmx_intraday_risk_events(request: Request):
    """HTMX: 铃铛风控事件日志"""
    try:
        from app.services.db_service import get_supabase
        from datetime import datetime
        sb = get_supabase()

        today = datetime.utcnow().strftime("%Y-%m-%d")
        result = sb.table("intraday_risk_events").select("*").gte("created_at", today).order("created_at", desc=True).limit(20).execute()

        events = result.data if result.data else []
        if not events:
            return HTMLResponse(
                '<div class="flex items-center justify-center gap-2 py-4">'
                '<span class="w-2 h-2 rounded-full bg-sq-green animate-pulse"></span>'
                '<span class="text-sm text-gray-500">暂无风控事件 — 系统运行正常</span>'
                '</div>'
                '<script>document.getElementById("risk-status-badge").className='
                '"px-2 py-0.5 rounded-full text-[10px] bg-green-900/60 text-sq-green";'
                'document.getElementById("risk-status-badge").textContent="正常";</script>'
            )

        html = ""
        has_critical = False
        for ev in events:
            event_type = ev.get("event_type", "info")
            message = ev.get("message", "")
            created_at = ev.get("created_at", "")[:19]

            if event_type == "critical":
                badge = '<span class="px-1.5 py-0.5 rounded text-[10px] bg-red-900/60 text-red-400">CRITICAL</span>'
                has_critical = True
            elif event_type == "warning":
                badge = '<span class="px-1.5 py-0.5 rounded text-[10px] bg-amber-900/60 text-amber-400">WARNING</span>'
            else:
                badge = '<span class="px-1.5 py-0.5 rounded text-[10px] bg-gray-800 text-gray-400">INFO</span>'

            html += f"""
            <div class="flex items-start gap-2 py-2 border-b border-gray-800/50">
                {badge}
                <div class="flex-1 text-xs text-gray-300">{message}</div>
                <span class="text-[10px] text-gray-600 whitespace-nowrap">{created_at}</span>
            </div>"""

        # Update risk badge
        if has_critical:
            badge_script = (
                '<script>document.getElementById("risk-status-badge").className='
                '"px-2 py-0.5 rounded-full text-[10px] bg-red-900/60 text-red-400";'
                'document.getElementById("risk-status-badge").textContent="警告";</script>'
            )
        else:
            badge_script = (
                '<script>document.getElementById("risk-status-badge").className='
                '"px-2 py-0.5 rounded-full text-[10px] bg-amber-900/60 text-amber-300";'
                'document.getElementById("risk-status-badge").textContent="有事件";</script>'
            )

        return HTMLResponse(html + badge_script)
    except Exception as e:
        logger.error(f"Intraday risk events error: {e}")
        return HTMLResponse(
            '<div class="text-center text-gray-500 py-4 text-sm">风控事件加载失败</div>'
        )


@router.post("/api/intraday/stop", response_class=HTMLResponse)
async def api_intraday_stop(request: Request):
    """紧急停止铃铛自动交易"""
    try:
        from app.config.intraday_config import IntradayConfig
        IntradayConfig.AUTO_EXECUTE = False
        logger.warning("[INTRADAY] AUTO_EXECUTE set to False by user!")
        return HTMLResponse(
            '<div class="px-4 py-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-400 text-sm">'
            'AUTO_EXECUTE 已关闭 — 铃铛策略不再自动下单。需要手动重启。'
            '</div>'
        )
    except Exception as e:
        return HTMLResponse(f'<div class="text-sq-red text-sm">停止失败: {e}</div>')


@router.post("/api/intraday/close-all", response_class=HTMLResponse)
async def api_intraday_close_all(request: Request):
    """紧急平仓所有日内头寸"""
    try:
        import asyncio as _aio
        from app.services.order_service import get_tiger_trade_client

        tiger = get_tiger_trade_client("leverage")
        positions = await _aio.wait_for(tiger.get_positions(), timeout=10.0)

        if not positions:
            return HTMLResponse(
                '<div class="px-4 py-3 bg-gray-800 rounded-lg text-gray-400 text-sm">'
                '当前无持仓，无需平仓。'
                '</div>'
            )

        closed = []
        for p in positions:
            ticker = p.get("ticker", "")
            qty = int(p.get("quantity", 0) or 0)
            if qty > 0:
                try:
                    result = await tiger.place_order(ticker, "SELL", qty, order_type="MKT")
                    closed.append(f"{ticker} x {qty}")
                    logger.warning(f"[INTRADAY] Emergency close: {ticker} x {qty}")
                except Exception as e:
                    closed.append(f"{ticker} FAILED: {e}")

        return HTMLResponse(
            f'<div class="px-4 py-3 bg-red-900/30 border border-red-700/50 rounded-lg text-red-400 text-sm">'
            f'已提交平仓指令: {", ".join(closed)}'
            f'</div>'
        )
    except Exception as e:
        return HTMLResponse(f'<div class="text-sq-red text-sm">平仓失败: {e}</div>')


@router.post("/api/intraday/force-scan", response_class=HTMLResponse)
async def api_intraday_force_scan(request: Request):
    """手动触发一轮盘中评分"""
    try:
        from app.services.intraday_service import run_intraday_trading_round
        result = await run_intraday_trading_round(enable_auto_execute=False)

        scored = result.get("total_scored", 0)
        top = result.get("top", [])
        top_tickers = ", ".join([s.get("ticker", "") for s in top[:5]])

        return HTMLResponse(
            f'<div class="px-4 py-3 bg-cyan-900/30 border border-cyan-700/50 rounded-lg text-cyan-400 text-sm">'
            f'评分完成 — {scored} 只股票已评分<br>'
            f'TOP 5: {top_tickers}'
            f'</div>'
        )
    except Exception as e:
        return HTMLResponse(f'<div class="text-sq-red text-sm">评分失败: {e}</div>')


# =====================================================================
# Intraday Scoring Endpoints
# =====================================================================

@router.get("/htmx/leverage-positions", response_class=HTMLResponse)
async def htmx_leverage_positions(request: Request):
    """杠杆账户（日内）持仓列表（HTMX 局部）"""
    try:
        import asyncio as _aio
        from app.services.order_service import get_tiger_trade_client
        from app.services import intraday_state as _intraday_state_mod
        from app.config.intraday_config import IntradayConfig as _IC

        tiger = get_tiger_trade_client("leverage")
        positions = await _aio.wait_for(tiger.get_positions(), timeout=10.0)

        if not positions:
            return HTMLResponse(
                '<div class="text-center text-gray-500 py-8 text-sm">杠杆账户暂无持仓</div>'
                '<script>document.getElementById("leverage-count").textContent="0";</script>'
            )

        _st = _intraday_state_mod.ensure_fresh_trading_day(_intraday_state_mod.load_state())
        _entry_times: Dict[str, str] = dict(_st.get("entry_times_et") or {})

        total_ur = sum(p.get("unrealized_pnl", 0) for p in positions)
        ur_color = "text-sq-green" if total_ur >= 0 else "text-sq-red"
        ur_sign = "+" if total_ur >= 0 else ""

        rows = ""
        for p in positions:
            tk = p.get("ticker", "")
            tk_key = str(tk or "").upper().strip()
            if " " in tk_key:
                tk_key = tk_key.split()[0]
            qty = int(p.get("quantity", 0) or 0)
            cost = float(p.get("average_cost", 0) or 0)
            price = float(p.get("latest_price", 0) or 0)
            mv = float(p.get("market_value", 0) or 0)
            ur = float(p.get("unrealized_pnl", 0) or 0)
            pnl_pct = ((price - cost) / cost * 100) if cost > 0 else 0
            pc = "text-sq-green" if ur >= 0 else "text-sq-red"
            ps = "+" if ur >= 0 else ""

            et_iso = _entry_times.get(tk_key) or _entry_times.get(str(tk or "").upper())
            ex = _intraday_leverage_row_extras(cost, price, et_iso)
            if getattr(_IC, "USE_ENTRY_BRACKET_TAKE_PROFIT", False) and ex.get("bracket_tp") is not None:
                dtp = float(ex["dist_tp_pct"] or 0)
                tp_line = f'挂价≈${ex["bracket_tp"]:.2f} <span class="text-cyan-400">距TP {dtp:+.2f}%</span>'
            else:
                tp_line = '<span class="text-gray-600">括号止盈关</span>'
            dsp = ex.get("dist_stop_pct")
            rm_line = (
                f'距FULL_STOP <span class="text-amber-400/90">{float(dsp):+.2f}%</span>'
                if dsp is not None
                else ""
            )
            bh = ex.get("bars_held")
            mx = int(ex.get("max_bars") or 13)
            bm = int(ex.get("bar_minutes") or 30)
            if bh is not None:
                bar_line = f"已持 <span class=\"text-gray-300\">{bh}/{mx}</span> 根{bm}m"
            else:
                bar_line = f'已持 <span class="text-gray-600">—</span>/{mx}根{bm}m <span class="text-gray-600">(无建仓时间)</span>'

            rows += f"""
            <div class="grid grid-cols-12 gap-2 px-2 py-3 border-b border-gray-800/60 hover:bg-white/[0.02] transition-colors items-center">
                <div class="col-span-3 min-w-0">
                    <span class="font-mono font-bold text-white text-base">{tk}</span>
                    <div class="text-[10px] text-cyan-500 mt-0.5">日内 · {qty:,}股</div>
                </div>
                <div class="col-span-2 text-right min-w-0">
                    <div class="font-mono text-white text-sm font-semibold">{qty:,}</div>
                    <div class="text-[10px] text-gray-500 font-mono">{mv:,.0f}</div>
                </div>
                <div class="col-span-2 text-right min-w-0">
                    <div class="font-mono text-white text-sm">{price:.2f}</div>
                    <div class="text-[10px] text-gray-500 font-mono">{cost:.2f}</div>
                </div>
                <div class="col-span-2 text-right min-w-0">
                    <div class="font-mono text-xs font-bold {pc}">{ps}{ur:,.0f}</div>
                    <div class="text-[10px] font-mono {pc}">{ps}{pnl_pct:.1f}%</div>
                </div>
                <div class="col-span-3 text-right min-w-0 space-y-0.5 leading-tight">
                    <div class="text-[9px] text-gray-400">{tp_line}</div>
                    <div class="text-[9px] text-gray-400">{rm_line}</div>
                    <div class="text-[9px]">{bar_line}</div>
                </div>
            </div>"""

        count_script = f'<script>document.getElementById("leverage-count").textContent="{len(positions)}";</script>'
        ur_script = f'<script>document.getElementById("leverage-unrealized-total").innerHTML=\'<span class="{ur_color}">{ur_sign}{total_ur:,.0f}</span>\';</script>'

        return HTMLResponse(rows + count_script + ur_script)
    except Exception as e:
        logger.error(f"Leverage positions error: {e}")
        return HTMLResponse(
            f'<div class="text-center text-gray-500 py-6 text-sm">杠杆账户未连接</div>'
            f'<script>document.getElementById("leverage-count").textContent="--";</script>'
        )


@router.get("/htmx/intraday-scores", response_class=HTMLResponse)
async def htmx_intraday_scores(request: Request):
    """最近一轮盘中评分排名（HTMX 局部刷新）— 含分数柱状图 + 因子分解"""
    try:
        from app.services.intraday_service import get_cached_intraday_scores
        cache = get_cached_intraday_scores()
        if not cache:
            return HTMLResponse(
                '<div class="text-center py-8 text-gray-500 text-sm">'
                '暂无盘中评分 — 交易时段每30分钟自动运行</div>'
            )

        scored_at = cache.get("scored_at", "")[:19]
        round_num = cache.get("round", 0)
        total = cache.get("total_scored", 0)
        top = cache.get("top", [])

        # Factor short labels
        factor_labels = {
            "intraday_momentum": ("MTM", "动量"),
            "vwap_deviation": ("VWAP", "偏离"),
            "volume_profile": ("VOL", "量能"),
            "micro_rsi": ("RSI", "超买卖"),
            "spread_quality": ("SPD", "效率"),
            "relative_flow": ("REL", "超额"),
        }

        cards_html = ""
        for i, s in enumerate(top):
            ticker = s.get("ticker", "")
            score = s.get("total_score", 0)
            price = s.get("latest_price", 0)
            vwap = s.get("vwap", 0)
            factors = s.get("factors", {})

            score_color = "text-sq-green" if score > 0 else "text-sq-red"
            bar_color = "bg-cyan-500" if score > 0 else "bg-red-500"
            bar_width = min(100, abs(score) * 10)  # scale: 10 = 100%
            rank = i + 1

            # Factor mini bars
            factor_bars = ""
            for fname, (label, _cn) in factor_labels.items():
                fdata = factors.get(fname, {})
                fs = fdata.get("score", 0)
                fc = "bg-cyan-400" if fs > 0 else "bg-red-400"
                fw = min(100, abs(fs) * 100)
                ft = "text-cyan-400" if fs > 0 else ("text-red-400" if fs < -0.1 else "text-gray-600")
                factor_bars += (
                    f'<div class="flex items-center gap-1">'
                    f'<span class="text-[9px] text-gray-500 w-8">{label}</span>'
                    f'<div class="flex-1 h-1 bg-gray-800 rounded-full overflow-hidden">'
                    f'<div class="{fc} h-full rounded-full" style="width:{fw}%"></div></div>'
                    f'<span class="{ft} text-[9px] font-mono w-8 text-right">{fs:+.2f}</span>'
                    f'</div>'
                )

            vwap_dev = factors.get("vwap_deviation", {}).get("deviation_pct", 0)
            vwap_color = "text-cyan-400" if vwap_dev > 0 else "text-red-400"
            rsi_val = factors.get("micro_rsi", {}).get("rsi", 50)

            cards_html += f"""
            <div class="bg-gray-900/50 rounded-xl p-3 border border-gray-800/50 hover:border-cyan-800/30 transition-colors">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] text-gray-600 font-mono">#{rank}</span>
                        <span class="font-mono font-bold text-white text-lg">{ticker}</span>
                        <span class="text-xs font-mono text-gray-400">${price:,.2f}</span>
                    </div>
                    <div class="text-right">
                        <span class="font-mono font-bold text-lg {score_color}">{score:+.2f}</span>
                    </div>
                </div>
                <!-- Score bar -->
                <div class="h-1.5 bg-gray-800 rounded-full mb-2 overflow-hidden">
                    <div class="{bar_color} h-full rounded-full transition-all duration-500" style="width:{bar_width}%"></div>
                </div>
                <!-- Factor breakdown -->
                <div class="grid grid-cols-1 gap-0.5">
                    {factor_bars}
                </div>
                <!-- VWAP + RSI summary -->
                <div class="flex items-center gap-4 mt-2 pt-2 border-t border-gray-800/50">
                    <span class="text-[10px] text-gray-500">VWAP ${vwap:,.2f} <span class="{vwap_color}">{vwap_dev:+.2f}%</span></span>
                    <span class="text-[10px] text-gray-500">RSI {rsi_val:.0f}</span>
                </div>
            </div>"""

        html = f"""
        <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-3">
                <span class="text-xs font-mono text-cyan-500">Round #{round_num}</span>
                <span class="text-[10px] text-gray-600">{scored_at}</span>
            </div>
            <span class="text-xs text-gray-500">{total} tickers scored</span>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
            {cards_html}
        </div>
        <script>
            (function(){{
                var t = 'Round #{round_num} · {total} tickers';
                var a = document.getElementById('intraday-round-info');
                var b = document.getElementById('scores-round-label');
                if (a) a.textContent = t;
                if (b) b.textContent = t;
            }})();
        </script>
        """
        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Intraday scores HTMX error: {e}")
        return HTMLResponse(f'<div class="text-red-400 text-sm py-4">Error: {str(e)[:100]}</div>')


@router.post("/api/trigger/intraday-scoring")
async def api_trigger_intraday_scoring(request: Request):
    """手动触发一轮盘中评分（调试用，忽略交易时段检查）"""
    try:
        from app.services.intraday_service import run_intraday_scoring_round
        result = await run_intraday_scoring_round()
        return result
    except Exception as e:
        logger.error(f"Manual intraday scoring error: {e}")
        return {"status": "error", "message": str(e)[:200]}


@router.get("/htmx/account-summary-all", response_class=HTMLResponse)
async def htmx_account_summary_all(request: Request):
    """双账户资产摘要 — Primary + Leverage（HTMX 局部）"""
    try:
        from app.services.order_service import get_all_accounts_assets
        all_assets = await get_all_accounts_assets()

        cards = []
        labels = {"primary": ("宝典", "amber"), "leverage": ("日内", "cyan")}
        for label, (cn, color) in labels.items():
            assets = all_assets.get(label)
            if not assets:
                cards.append(
                    f'<div class="bg-sq-card rounded-xl p-4 border border-gray-800">'
                    f'<div class="text-xs text-{color}-400 mb-1">{cn}账户</div>'
                    f'<div class="text-lg text-gray-500 font-mono">未连接</div></div>'
                )
                continue
            nlv = assets.get("net_liquidation", 0)
            cash = assets.get("cash", 0)
            bp = assets.get("buying_power", 0)
            upnl = assets.get("unrealized_pnl", 0)
            upnl_color = "text-sq-green" if upnl >= 0 else "text-sq-red"
            upnl_sign = "+" if upnl >= 0 else ""
            cards.append(f"""
            <div class="bg-sq-card rounded-xl p-4 border border-gray-800">
                <div class="text-xs text-{color}-400 mb-1">{cn}账户</div>
                <div class="text-2xl font-bold text-white font-mono">${nlv:,.0f}</div>
                <div class="grid grid-cols-3 gap-2 mt-2 text-xs">
                    <div><span class="text-gray-500">Cash</span><br><span class="font-mono text-white">${cash:,.0f}</span></div>
                    <div><span class="text-gray-500">购买力</span><br><span class="font-mono text-white">${bp:,.0f}</span></div>
                    <div><span class="text-gray-500">未实现</span><br><span class="font-mono {upnl_color}">{upnl_sign}${upnl:,.0f}</span></div>
                </div>
            </div>""")

        return HTMLResponse(f'<div class="grid grid-cols-1 md:grid-cols-2 gap-4">{"".join(cards)}</div>')
    except Exception as e:
        logger.error(f"Account summary all error: {e}")
        return HTMLResponse(f'<div class="text-red-400 text-sm">Error: {str(e)[:100]}</div>')
