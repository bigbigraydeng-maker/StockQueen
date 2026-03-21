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
from datetime import date
from typing import Optional, Dict, Any, Tuple
from fastapi import APIRouter, BackgroundTasks, Request, Query, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

_limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


def _tpl(template_name: str, context: dict):
    """Render template with auto-injected is_guest flag from request.state."""
    request = context.get("request")
    if request and "is_guest" not in context:
        context["is_guest"] = getattr(request.state, "is_guest", False)
    return templates.TemplateResponse(template_name, context)

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
_PERSISTENT_PREFIXES = ("adaptive_v1:", "bt_v2:", "bt_fund:", "opt:", "rotation_scores")


def _disk_cache_path(key: str) -> str:
    """Get file path for a disk-cached key."""
    safe_key = key.replace(":", "_").replace("/", "_").replace(" ", "_")
    return _os.path.join(_CACHE_DIR, f"{safe_key}.json")


def _cache_get(key: str) -> Any:
    """Return cached value: three-tier lookup — memory → disk → Supabase cache_store."""
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


@router.get("/quotes", response_class=HTMLResponse)
async def quotes_page(request: Request):
    """实时行情页"""
    return _tpl("quotes.html", {"request": request})


@router.get("/htmx/rotation-data", response_class=HTMLResponse)
async def htmx_rotation_data(request: Request):
    """HTMX endpoint: 异步加载全部rotation数据，避免阻塞页面首屏"""
    import concurrent.futures
    loop = asyncio.get_event_loop()

    def _sync_load_all():
        """在线程池中执行所有同步Supabase调用，不阻塞event loop"""
        from app.database import get_db

        # 1. Read scores from cache (L1 memory → L2 disk → L3 Supabase)
        cached_scores = _cache_get("rotation_scores")
        scores = []
        regime = "unknown"
        has_scores = False

        if cached_scores is not None:
            logger.info(f"rotation-data: cache hit, type={type(cached_scores).__name__}, keys={list(cached_scores.keys()) if isinstance(cached_scores, dict) else 'N/A'}")
            raw = cached_scores.get("scores", []) if isinstance(cached_scores, dict) else cached_scores
            logger.info(f"rotation-data: raw scores count={len(raw)}, first={raw[0] if raw else 'empty'}")
            for s in raw:
                if hasattr(s, "model_dump"):
                    scores.append(s.model_dump())
                elif isinstance(s, dict):
                    scores.append(s)
            scores.sort(key=lambda x: x.get("score", 0), reverse=True)
            regime = cached_scores.get("regime", "unknown") if isinstance(cached_scores, dict) else "unknown"
            has_scores = len(scores) > 0
        else:
            logger.warning("rotation-data: cache MISS for rotation_scores — no cached data available")
            # Fallback: try reading scores directly from latest rotation_snapshot
            try:
                from app.database import get_db
                db_fb = get_db()
                snap_r = db_fb.table("rotation_snapshots").select(
                    "regime, scores"
                ).order("created_at", desc=True).limit(1).execute()
                if snap_r.data and snap_r.data[0].get("scores"):
                    snap = snap_r.data[0]
                    regime = snap.get("regime", "unknown")
                    raw_scores = snap["scores"]
                    if isinstance(raw_scores, list):
                        scores = raw_scores
                    elif isinstance(raw_scores, dict):
                        scores = raw_scores.get("scores", [])
                    scores.sort(key=lambda x: x.get("score", 0), reverse=True)
                    has_scores = len(scores) > 0
                    # Warm up L1 cache for next request
                    _cache_set("rotation_scores", {"regime": regime, "count": len(scores), "scores": scores}, _ROTATION_TTL)
                    logger.info(f"rotation-data: fallback from rotation_snapshots, {len(scores)} scores loaded")
            except Exception as e:
                logger.warning(f"rotation-data: fallback failed: {e}")

        logger.info(f"rotation-data: final scores={len(scores)}, regime={regime}, has_scores={has_scores}")

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

        sectors = []
        cached = _cache_get("rotation_scores")
        if cached:
            raw = cached.get("scores", []) if isinstance(cached, dict) else cached
            sector_map: dict = {}
            for s in raw:
                if hasattr(s, "model_dump"):
                    s = s.model_dump()
                sec = (s.get("sector") or "other")
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
                        sector_scores = [
                            s for s in all_scores
                            if (s.get("sector") or "").lower() == sector_key
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
        _fetch_positions(),
        _fetch_signals(),
        _fetch_risk(),
        _get_total_profit(),
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

    return _tpl("dashboard.html", {
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
    """缓存miss时HTMX lazy load: 获取评分数据 → 重定向到整页刷新"""
    try:
        from app.services.rotation_service import get_current_scores

        # Force fetch scores and cache them
        cache_key = "rotation_scores"
        scores_result = _cache_get(cache_key)
        if scores_result is None:
            scores_result = await get_current_scores()
            _cache_set(cache_key, scores_result, _ROTATION_TTL)
            logger.info("Rotation scores fetched and cached via HTMX lazy load")

        # Return HX-Redirect to reload the page (now with cached data)
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
    """可排序轮动评分表（HTMX局部），评分数据缓存5分钟"""
    try:
        from app.services.rotation_service import get_current_scores

        # Cache raw scores (before sorting) — same data, different sort orders
        cache_key = "rotation_scores"
        scores_result = _cache_get(cache_key)
        if scores_result is None:
            scores_result = await get_current_scores()
            _cache_set(cache_key, scores_result, _ROTATION_TTL)
            logger.info("Rotation scores cached (5min TTL)")

        scores = []
        if isinstance(scores_result, dict):
            scores = scores_result.get("scores", [])
        elif isinstance(scores_result, list):
            scores = scores_result

        score_dicts = []
        for s in scores:
            if hasattr(s, "model_dump"):
                score_dicts.append(s.model_dump())
            elif hasattr(s, "dict"):
                score_dicts.append(s.dict())
            elif isinstance(s, dict):
                score_dicts.append(s)
            else:
                score_dicts.append(vars(s))

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
        from app.services.rotation_service import get_intraday_prices

        benchmarks = ["SPY", "QQQ", "TLT", "GLD"]

        # 优先从后台 intraday_scan 缓存读取（零 API 调用）
        scan_cache = get_intraday_prices()
        scan_map = {}
        if scan_cache and scan_cache.get("results"):
            for r in scan_cache["results"]:
                scan_map[r["ticker"]] = r

        # Fallback: 逐个检查缺失的 benchmark，而非仅在整个缓存为空时才调 API
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
            scan = scan_map.get(ticker)
            quote = quotes_raw.get(ticker)
            if scan:
                price = float(scan.get("price") or 0)
                prev_close = float(scan.get("prev_close") or 0)
                cards.append({
                    "ticker": ticker,
                    "price": price,
                    "change": price - prev_close if prev_close else 0,
                    "change_pct": scan.get("change_pct", 0),
                })
            elif quote:
                cards.append({
                    "ticker": ticker,
                    "price": quote.get("latest_price", 0),
                    "change": quote.get("latest_price", 0) - quote.get("prev_close", 0),
                    "change_pct": quote.get("change_percent", 0),
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


@router.get("/htmx/quotes-table", response_class=HTMLResponse)
async def htmx_quotes_table(request: Request, pool: str = Query("all")):
    """实时行情表格 — 优先读后台 intraday_scan 缓存，零 API 调用"""
    try:
        return await _htmx_quotes_table_inner(request, pool)
    except Exception as e:
        logger.error(f"Quotes table error: {e}", exc_info=True)
        return HTMLResponse(
            '<div class="p-8 text-center">'
            '<p class="text-sq-red mb-3 text-sm">行情加载失败，请稍后重试</p>'
            '<button hx-get="/htmx/quotes-table" hx-target="#quotes-table-container" '
            'hx-swap="innerHTML" hx-indicator="#quotes-refresh-indicator" '
            'class="px-3 py-1.5 rounded bg-sq-accent/20 text-sq-accent text-sm border border-sq-accent/30 cursor-pointer">'
            '重试</button></div>'
        )


async def _htmx_quotes_table_inner(request: Request, pool: str) -> HTMLResponse:
    """实际行情表格逻辑，由 htmx_quotes_table 调用（统一异常由外层捕获）"""
    from app.config.rotation_watchlist import (
        OFFENSIVE_ETFS, DEFENSIVE_ETFS, INVERSE_ETFS,
        LARGECAP_STOCKS, MIDCAP_STOCKS,
    )

    # Build ticker list by pool
    pool_map = {
        "etf_offensive": OFFENSIVE_ETFS,
        "etf_defensive": DEFENSIVE_ETFS,
        "inverse_etf": INVERSE_ETFS,
        "stock": LARGECAP_STOCKS + MIDCAP_STOCKS,
    }

    items = []
    if pool == "all":
        for lst in pool_map.values():
            items.extend(lst)
    else:
        items = pool_map.get(pool, [])

    # Extract tickers, dedup preserving order
    seen = set()
    unique_tickers = []
    for item in items:
        t = item["ticker"] if isinstance(item, dict) else str(item)
        if t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    # ── 数据源1: 后台 intraday_scan 缓存（每20分钟刷新，零 API 调用）──
    from app.services.rotation_service import get_intraday_prices
    scan_cache = get_intraday_prices()  # dict with "results", "scan_time" etc.
    scan_map = {}
    if scan_cache and scan_cache.get("results"):
        for r in scan_cache["results"]:
            scan_map[r["ticker"]] = r

    # ── 数据源2: rotation_scores 缓存（周度评分，零 API 调用）──
    scores_map = {}
    try:
        cached = _cache_get("rotation_scores")
        if cached is not None:
            raw = cached.get("scores", []) if isinstance(cached, dict) else cached
            for s in raw:
                d = s.model_dump() if hasattr(s, "model_dump") else (s.dict() if hasattr(s, "dict") else s)
                scores_map[d.get("ticker", "")] = d
    except Exception:
        pass

    # ── 数据源3: 活跃持仓（数据库）──
    position_map = {}
    try:
        from app.database import get_db as _get_db
        _db = _get_db()
        pos_r = _db.table("rotation_positions").select(
            "ticker, status, entry_price, stop_loss, take_profit"
        ).neq("status", "closed").execute()
        for p in (pos_r.data or []):
            position_map[p["ticker"]] = p
    except Exception:
        pass

    # ── Fallback: scan_cache 为空或缺失重要 ticker 时调 API ──
    # 优先补全持仓 tickers + 基准，最多 ~10 个 API 调用
    realtime_quotes = {}
    benchmarks = ["SPY", "QQQ", "TLT", "GLD"]
    held_tickers = list(position_map.keys())
    important_tickers = list(set(held_tickers + benchmarks))
    if not scan_map:
        # scan_cache 完全为空：获取所有重要 ticker
        fallback_tickers = important_tickers
    else:
        # scan_cache 存在但可能缺失部分 ticker：仅补全缺失的
        fallback_tickers = [t for t in important_tickers if t not in scan_map]
    if fallback_tickers:
        try:
            from app.services.alphavantage_client import get_av_client
            av = get_av_client()
            realtime_quotes = await av.batch_get_quotes(fallback_tickers)
        except Exception as _av_err:
            logger.warning(f"Quotes table AV fallback failed: {_av_err}")

    # Build ticker name/sector lookup from watchlist items
    item_info = {}
    for item in items:
        t = item["ticker"] if isinstance(item, dict) else str(item)
        if isinstance(item, dict):
            item_info[t] = item

    quotes = []
    alerts = []
    for ticker in unique_tickers:
        score_data = scores_map.get(ticker, {})
        info = item_info.get(ticker, {})
        scan = scan_map.get(ticker)       # 后台扫描缓存
        rt = realtime_quotes.get(ticker)  # fallback API 数据

        # Price priority: scan_cache > fallback API > rotation_scores
        if scan:
            price = float(scan.get("price") or 0)
            change_percent = scan.get("change_pct", 0)
            volume = scan.get("volume", 0)
            has_realtime = True
        elif rt:
            price = float(rt.get("latest_price") or 0)
            change_percent = rt.get("change_percent", 0)
            volume = rt.get("volume", 0)
            has_realtime = True
        else:
            price = float(score_data.get("current_price") or 0)
            change_percent = score_data.get("return_1w", 0) or 0
            volume = None
            has_realtime = False

        if price == 0 and not score_data:
            continue

        # Position enrichment (prefer scan_cache data if available)
        pos = position_map.get(ticker)
        is_held = pos is not None or bool(scan and scan.get("is_held"))
        stop_loss_breach = False
        take_profit_breach = False
        pnl_pct = None
        entry_price = None
        stop_loss = None
        take_profit = None
        pos_status = None

        if scan and scan.get("is_held"):
            # Use pre-computed position data from intraday scan
            entry_price = scan.get("entry_price")
            stop_loss = scan.get("stop_loss")
            take_profit = scan.get("take_profit")
            pos_status = scan.get("status")
            pnl_pct = scan.get("pnl_pct")
            stop_loss_breach = scan.get("stop_loss_breach", False)
            take_profit_breach = scan.get("take_profit_breach", False)
        elif pos:
            entry_price = float(pos.get("entry_price") or 0)
            stop_loss = float(pos.get("stop_loss") or 0)
            take_profit = float(pos.get("take_profit") or 0)
            pos_status = pos.get("status")
            if entry_price > 0 and price > 0:
                pnl_pct = round((price / entry_price - 1) * 100, 2)
            if stop_loss > 0 and price < stop_loss:
                stop_loss_breach = True
            if take_profit > 0 and price > take_profit:
                take_profit_breach = True

        row = {
            "ticker": ticker,
            "name": (scan.get("name", "") if scan else "") or score_data.get("name", "") or info.get("name", ""),
            "sector": (scan.get("sector", "") if scan else "") or score_data.get("sector", "") or info.get("sector", ""),
            "latest_price": price,
            "change_percent": change_percent,
            "volume": volume,
            "high": rt.get("high", 0) if rt else None,
            "low": rt.get("low", 0) if rt else None,
            "has_realtime": has_realtime,
            "above_ma20": score_data.get("above_ma20"),
            "score": score_data.get("score"),
            "is_held": is_held,
            "pos_status": pos_status,
            "pnl_pct": pnl_pct,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "stop_loss_breach": stop_loss_breach,
            "take_profit_breach": take_profit_breach,
        }
        quotes.append(row)
        if stop_loss_breach or take_profit_breach:
            alerts.append(row)

    # Sort: alerts first, then held positions, then by change% desc
    quotes.sort(key=lambda x: (
        -(1 if x.get("stop_loss_breach") or x.get("take_profit_breach") else 0),
        -(1 if x.get("is_held") else 0),
        -(x.get("change_percent") or 0),
    ))

    return _tpl("partials/_quotes_table.html", {
        "request": request,
        "quotes": quotes,
        "alerts": alerts,
        "scan_time": scan_cache.get("scan_time") if scan_cache else None,
    })


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


@router.get("/htmx/positions", response_class=HTMLResponse)
async def htmx_positions(request: Request):
    """持仓列表（HTMX局部）— active + pending_exit, Tiger > scan cache > DB fallback"""
    try:
        from app.services.rotation_service import get_current_positions, get_intraday_prices
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") in ("active", "pending_exit")]

        if active:
            # Priority 1: Tiger positions API (single batch call, fast)
            tiger_prices = {}
            try:
                from app.services.order_service import get_tiger_trade_client
                tiger_client = get_tiger_trade_client()
                tiger_positions = await tiger_client.get_positions()
                for tp in tiger_positions:
                    tk = tp.get("ticker", "")
                    price = tp.get("latest_price", 0)
                    if tk and price > 0:
                        tiger_prices[tk] = price
                if tiger_prices:
                    logger.info(f"[POSITIONS] Tiger prices: {tiger_prices}")
            except Exception as e:
                logger.warning(f"[POSITIONS] Tiger unavailable: {e}")

            # Priority 2: Fill gaps from intraday scan cache (zero API calls)
            missing = [p["ticker"] for p in active if p.get("ticker") and p["ticker"] not in tiger_prices]
            if missing:
                scan_cache = get_intraday_prices()
                if scan_cache and scan_cache.get("results"):
                    scan_map = {r["ticker"]: r for r in scan_cache["results"]}
                    for t in missing:
                        scan = scan_map.get(t)
                        if scan and float(scan.get("price") or 0) > 0:
                            tiger_prices[t] = float(scan["price"])

            # Apply prices to positions
            for p in active:
                tk = p.get("ticker")
                if tk and tk in tiger_prices:
                    p["current_price"] = tiger_prices[tk]
                    entry = p.get("entry_price") or 0
                    if entry > 0:
                        p["unrealized_pnl_pct"] = (p["current_price"] - entry) / entry

        return _tpl("partials/_positions.html", {
            "request": request,
            "positions": active,
        })
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


@router.get("/htmx/pending-entries", response_class=HTMLResponse)
async def htmx_pending_entries(request: Request):
    """待进场列表（HTMX局部）— pending_entry 状态，优先用 scan cache 获取价格"""
    try:
        from app.services.rotation_service import (
            get_current_positions, get_intraday_prices, RC,
        )

        all_positions = await get_current_positions() or []
        pending = [p for p in all_positions if p.get("status") == "pending_entry"]

        # Use intraday scan cache for prices (zero API calls)
        scan_cache = get_intraday_prices()
        scan_map = {}
        if scan_cache and scan_cache.get("results"):
            for r in scan_cache["results"]:
                scan_map[r["ticker"]] = r

        for p in pending:
            ticker = p.get("ticker", "")
            scan = scan_map.get(ticker)
            if scan:
                price = float(scan.get("price") or 0)
                if price > 0:
                    p["current_price"] = price
                    p["entry_price"] = round(price, 2)
                    # Use DB stop_loss/take_profit if available, else leave blank
                    if not p.get("stop_loss"):
                        p["stop_loss"] = None
                    if not p.get("take_profit"):
                        p["take_profit"] = None
                    p["above_ma5"] = None  # Not available from scan cache
                    p["vol_confirmed"] = None
                    p["ma5_value"] = None
                    p["vol_ratio"] = None

        return _tpl("partials/_pending_entries.html", {
            "request": request,
            "pending": pending,
        })
    except Exception as e:
        logger.error(f"Pending entries error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


@router.get("/htmx/intraday-scan", response_class=HTMLResponse)
async def htmx_intraday_scan(request: Request):
    """HTMX 端点: 返回盘中全池扫描结果 partial（从内存缓存读取，即时响应）"""
    try:
        from app.services.rotation_service import get_intraday_prices
        data = get_intraday_prices()
        if not data:
            return HTMLResponse(
                '<div class="text-center py-8 text-gray-500">'
                '<p class="mb-3">暂无盘中扫描数据</p>'
                '<button hx-post="/api/rotation/intraday-scan" '
                'hx-target="#intraday-scan-status" '
                'class="px-4 py-2 bg-sq-accent text-black text-sm font-semibold rounded-lg hover:opacity-90">'
                '立即扫描全部标的</button>'
                '<div id="intraday-scan-status" class="mt-2"></div>'
                '</div>'
            )
        return _tpl("partials/_rotation_intraday.html", {
            "request": request,
            **data,
        })
    except Exception as e:
        logger.error(f"HTMX intraday scan error: {e}")
        return HTMLResponse(f'<div class="text-sq-red text-sm py-2">加载失败: {e}</div>')


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
    """Tiger 模拟账户资金概览 + 持仓明细（HTMX局部）"""
    try:
        from app.services.order_service import get_tiger_trade_client
        tiger = get_tiger_trade_client()
        assets = await tiger.get_account_assets()
        if not assets:
            return HTMLResponse(
                '<div class="text-xs text-gray-500 text-center py-2">Tiger 未连接</div>'
            )

        # Paper trading account starts with "214" prefix
        is_paper = str(settings.tiger_account or "").startswith("214")
        mode = "模拟盘" if is_paper else "实盘"
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

        # Get Tiger positions
        positions = await tiger.get_positions()
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
        ur_color = "text-sq-green" if total_unrealized >= 0 else "text-sq-red"
        ur_sign = "+" if total_unrealized >= 0 else ""

        # Build positions rows
        pos_rows = ""
        for p in positions:
            tk = p.get("ticker", "?")
            qty = p.get("quantity", 0)
            avg = p.get("average_cost", 0)
            mv = p.get("market_value", 0)
            upnl = p.get("unrealized_pnl", 0)
            upnl_pct = (upnl / (avg * qty) * 100) if avg > 0 and qty > 0 else 0
            c = "text-sq-green" if upnl >= 0 else "text-sq-red"
            s = "+" if upnl >= 0 else ""
            pos_rows += f"""
            <div class="flex items-center justify-between py-1.5 border-b border-gray-800 last:border-0">
                <div class="flex items-center gap-2">
                    <span class="font-mono font-bold text-white text-xs">{tk}</span>
                    <span class="text-[10px] text-gray-500">{qty}股 @ ${avg:,.2f}</span>
                </div>
                <div class="text-right">
                    <span class="font-mono text-xs {c}">{s}${upnl:,.0f}</span>
                    <span class="text-[10px] text-gray-500 ml-1">({s}{upnl_pct:.2f}%)</span>
                </div>
            </div>"""

        pos_section = ""
        if pos_rows:
            pos_section = f"""
            <div class="mt-3 pt-3 border-t border-gray-700">
                <div class="text-xs text-gray-500 mb-2">Tiger 持仓</div>
                {pos_rows}
                <div class="flex justify-between mt-2 pt-2 border-t border-gray-700">
                    <span class="text-xs text-gray-400">未实现盈亏</span>
                    <span class="font-mono text-xs font-bold {ur_color}">{ur_sign}${total_unrealized:,.0f}</span>
                </div>
            </div>"""

        html = f"""
        <div class="bg-sq-card rounded-xl border border-sq-border p-4">
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-2">
                    <span class="text-lg">🐯</span>
                    <span class="text-sm font-semibold text-white">Tiger {mode}</span>
                    <span class="px-2 py-0.5 rounded text-xs {'bg-yellow-900 text-yellow-300' if is_paper else 'bg-green-900 text-green-300'}">
                        {mode}
                    </span>
                </div>
                <div class="text-right">
                    <span class="font-mono text-sm font-bold {pnl_color}">{pnl_sign}${total_pnl:,.0f}</span>
                    <span class="text-[10px] text-gray-500 ml-1">({pnl_sign}{pnl_pct:.2f}%)</span>
                </div>
            </div>
            <div class="grid grid-cols-4 gap-3 text-center">
                <div>
                    <div class="text-[10px] text-gray-500">净资产</div>
                    <div class="text-sm font-mono text-white">${nlv:,.0f}</div>
                </div>
                <div>
                    <div class="text-[10px] text-gray-500">可用资金</div>
                    <div class="text-sm font-mono text-sq-green">${avail:,.0f}</div>
                </div>
                <div>
                    <div class="text-[10px] text-gray-500">购买力</div>
                    <div class="text-sm font-mono text-gray-300">${buying_power:,.0f}</div>
                </div>
                <div>
                    <div class="text-[10px] text-gray-500">现金</div>
                    <div class="text-sm font-mono text-gray-300">${cash:,.0f}</div>
                </div>
            </div>
            {pos_section}
        </div>
        <!-- v=20260316b -->
        """
        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Account summary error: {e}")
        return HTMLResponse(
            '<div class="text-xs text-gray-500 text-center py-2">Tiger 未连接</div>'
        )


@router.post("/api/tiger/place-orders", response_class=HTMLResponse)
async def api_tiger_place_orders(request: Request):
    """
    手动触发：为所有 active 仓位（没有 tiger_order_id 的）向 Tiger 下限价买单 + bracket止盈止损。
    返回 HTML 格式的执行结果。
    """
    from app.services.order_service import get_tiger_trade_client, calculate_position_size
    from app.database import get_db
    import math

    results = []
    tiger = get_tiger_trade_client()

    # Test connection first
    try:
        assets = await tiger.get_account_assets()
        if not assets:
            return HTMLResponse(
                '<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
                '<span class="text-sq-red font-bold">❌ Tiger 连接失败</span>'
                '<p class="text-gray-400 mt-1">无法连接 Tiger API，请检查凭证配置</p></div>'
            )
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">❌ Tiger 连接错误</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    from app.database import get_db
    db = get_db()

    # Only process pending_entry positions (未下单信号仓位)
    # Active positions are already tracked; re-processing them causes stale/non-signal
    # positions to incorrectly appear in 活跃持仓.
    try:
        pos_result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, stop_loss, take_profit, status, tiger_order_id, quantity")
            .eq("status", "pending_entry")
            .execute()
        )
        positions = pos_result.data if pos_result.data else []
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 数据库查询失败</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    if not positions:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
            '暂无待下单的信号仓位（pending_entry）</div>'
        )

    # Step 1: Get Tiger positions to check what's already held
    tiger_held = {}  # ticker -> {qty, avg_cost, latest_price}
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
        logger.info(f"[PLACE-ORDER] Tiger已持有: {list(tiger_held.keys())}")
    except Exception as e:
        logger.warning(f"[PLACE-ORDER] 获取Tiger持仓失败: {type(e).__name__}: {e}", exc_info=True)

    for pos in positions:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")
        entry_price = pos.get("entry_price", 0)
        stop_loss = pos.get("stop_loss")
        take_profit = pos.get("take_profit")
        existing_order = pos.get("tiger_order_id")

        # Skip if already has order
        if existing_order:
            results.append({
                "ticker": ticker, "success": True, "skipped": True,
                "msg": f"已有订单 ID: {existing_order[:8]}..."
            })
            continue

        # Check if Tiger already holds this stock (manual buy)
        if ticker in tiger_held:
            held = tiger_held[ticker]
            held_qty = held.get("quantity", 0)
            held_cost = held.get("avg_cost", 0)
            held_price = held.get("latest_price", 0)
            if held_qty > 0 and held_cost > 0:
                # Sync Tiger position to DB — activate without placing new order
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
                    "status": "active",
                    "tiger_order_status": "filled",
                }).eq("id", pos_id).execute()
                pnl = round((held_price - held_cost) / held_cost * 100, 1) if held_cost > 0 and held_price > 0 else 0
                results.append({
                    "ticker": ticker, "success": True,
                    "msg": f"✅ 已同步Tiger持仓: {held_qty}股 @ ${held_cost:.2f} (当前 ${held_price:.2f}, {'+' if pnl >= 0 else ''}{pnl}%)"
                })
                logger.info(f"[PLACE-ORDER] {ticker} synced from Tiger: {held_qty}股 @ ${held_cost:.2f}")
                continue

        # If entry_price is NULL (pending_entry), fetch real-time price
        if not entry_price or entry_price <= 0:
            price_source = ""
            try:
                # Try Tiger API first
                from app.services.market_service import TigerAPIClient
                quote_client = TigerAPIClient()
                quote_data = await quote_client.get_stock_quote(ticker)
                if quote_data:
                    entry_price = quote_data.get("latest_price", 0) or quote_data.get("close", 0)
                    price_source = "Tiger"
            except Exception as e:
                logger.warning(f"[PLACE-ORDER] Tiger quote failed for {ticker}: {e}")

            # Fallback to Alpha Vantage if Tiger failed
            if not entry_price or entry_price <= 0:
                try:
                    from app.services.alphavantage_client import get_av_client
                    av = get_av_client()
                    av_quote = await av.get_quote(ticker)
                    if av_quote:
                        entry_price = av_quote.get("latest_price", 0)
                        price_source = "AlphaVantage"
                        logger.info(f"[PLACE-ORDER] {ticker} price from AV: ${entry_price}")
                except Exception as e2:
                    logger.warning(f"[PLACE-ORDER] AV quote also failed for {ticker}: {e2}")

            if not entry_price or entry_price <= 0:
                results.append({"ticker": ticker, "success": False, "msg": "Tiger和AV均无法获取价格"})
                continue

            # Calculate ATR-based stop-loss / take-profit if missing
            if not stop_loss or not take_profit:
                atr = entry_price * 0.03
                stop_loss = round(entry_price - 2 * atr, 2)
                take_profit = round(entry_price + 3 * atr, 2)
            # Update entry_price in DB and activate position
            db.table("rotation_positions").update({
                "entry_price": round(entry_price, 4),
                "entry_date": date.today().isoformat(),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "status": "active",
            }).eq("id", pos_id).execute()
            logger.info(f"[PLACE-ORDER] {ticker} pending→active, price=${entry_price:.2f} (via {price_source})")

        # Calculate position size — use RC.TOP_N for consistent equal-weight sizing
        try:
            from app.config.rotation_watchlist import RotationConfig as RC
            qty = await calculate_position_size(tiger, entry_price, max_positions=RC.TOP_N)
            if qty <= 0:
                results.append({"ticker": ticker, "success": False, "msg": "计算仓位为0"})
                continue
        except Exception as e:
            results.append({"ticker": ticker, "success": False, "msg": f"仓位计算失败: {e}"})
            continue

        # Place MKT buy order (no bracket legs — trailing stop managed by intraday monitor)
        try:
            result = await tiger.place_buy_order(
                ticker=ticker,
                quantity=qty,
                order_type="MKT",
            )
            if result:
                order_id = str(result.get("id") or result.get("order_id", ""))
                # Update DB
                update_data = {
                    "quantity": qty,
                    "tiger_order_id": order_id,
                    "tiger_order_status": "submitted",
                    "status": "active",
                }
                db.table("rotation_positions").update(update_data).eq("id", pos_id).execute()
                results.append({
                    "ticker": ticker, "success": True,
                    "msg": f"✅ MKT买入 {qty}股 | 订单ID: {order_id[:8]}..."
                })
            else:
                results.append({"ticker": ticker, "success": False, "msg": "Tiger API 返回空结果"})
        except Exception as e:
            results.append({"ticker": ticker, "success": False, "msg": f"下单失败: {e}"})

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
    应急端点：当Tiger API不可用时，使用Alpha Vantage价格手动激活所有pending_entry仓位。
    不依赖Tiger SDK。
    """
    from app.services.alphavantage_client import get_av_client
    from app.database import get_db

    db = get_db()
    try:
        pos_result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, stop_loss, take_profit, status")
            .eq("status", "pending_entry")
            .execute()
        )
        positions = pos_result.data if pos_result.data else []
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 数据库查询失败</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    if not positions:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
            '无待进场仓位</div>'
        )

    av = get_av_client()
    results = []

    for pos in positions:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")
        entry_price = pos.get("entry_price", 0)
        stop_loss = pos.get("stop_loss")
        take_profit = pos.get("take_profit")

        # Fetch price from Alpha Vantage if entry_price missing
        if not entry_price or entry_price <= 0:
            try:
                av_quote = await av.get_quote(ticker)
                if av_quote:
                    entry_price = av_quote.get("latest_price", 0)
            except Exception as e:
                results.append({"ticker": ticker, "success": False, "msg": f"AV价格获取失败: {e}"})
                continue

        if not entry_price or entry_price <= 0:
            results.append({"ticker": ticker, "success": False, "msg": "无法获取价格"})
            continue

        # Calculate SL/TP
        if not stop_loss or not take_profit:
            atr = entry_price * 0.03
            stop_loss = round(entry_price - 2 * atr, 2)
            take_profit = round(entry_price + 3 * atr, 2)

        # Activate in DB
        db.table("rotation_positions").update({
            "entry_price": round(entry_price, 4),
            "entry_date": date.today().isoformat(),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "active",
        }).eq("id", pos_id).execute()

        results.append({
            "ticker": ticker, "success": True,
            "msg": f"✅ 已激活 @ ${entry_price:.2f} | SL=${stop_loss} TP=${take_profit}"
        })
        logger.info(f"[ACTIVATE] {ticker} pending→active, price=${entry_price:.2f} (via AV)")

    # Build result HTML
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
            <span class="text-sm font-bold text-white">⚡ 手动激活结果</span>
            <span class="text-xs text-gray-400">成功 {ok} | 失败 {fail}</span>
        </div>
        <div class="divide-y divide-gray-800">{rows_html}</div>
    </div>
    """
    return HTMLResponse(html)


@router.post("/api/tiger/deactivate-positions", response_class=HTMLResponse)
async def api_tiger_deactivate_positions(request: Request):
    """
    撤回手动激活：将所有今天激活的active仓位恢复为pending_entry，
    清除entry_price、entry_date、stop_loss、take_profit。
    """
    from app.database import get_db

    db = get_db()
    today = date.today().isoformat()

    try:
        pos_result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, entry_date, status")
            .eq("status", "active")
            .eq("entry_date", today)
            .execute()
        )
        positions = pos_result.data if pos_result.data else []
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 数据库查询失败</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    if not positions:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
            '无今日激活的仓位可撤回</div>'
        )

    results = []
    for pos in positions:
        ticker = pos.get("ticker", "?")
        pos_id = pos.get("id")
        try:
            db.table("rotation_positions").update({
                "entry_price": None,
                "entry_date": None,
                "stop_loss": None,
                "take_profit": None,
                "status": "pending_entry",
            }).eq("id", pos_id).execute()
            results.append({"ticker": ticker, "success": True, "msg": "✅ 已撤回，恢复为待进场"})
            logger.info(f"[DEACTIVATE] {ticker} active→pending_entry (manual rollback)")
        except Exception as e:
            results.append({"ticker": ticker, "success": False, "msg": f"撤回失败: {e}"})

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
        result = db.table("rotation_positions").select("ticker, status").eq("id", position_id).execute()
        if not result.data:
            return HTMLResponse(
                '<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm">'
                '<span class="text-sq-red">❌ 持仓记录不存在</span></div>'
            )
        pos = result.data[0]
        ticker = pos.get("ticker", "?")
        db.table("rotation_positions").update({
            "status": "closed",
            "exit_date": date.today().isoformat(),
            "exit_reason": "manual_close",
        }).eq("id", position_id).execute()
        logger.info(f"[CLOSE-POS] {ticker} (id={position_id}) manually closed")
        return HTMLResponse(
            f'<div class="bg-gray-800 rounded-lg p-3 text-sm">'
            f'<span class="text-gray-400">✅ {ticker} 持仓记录已关闭（DB标记为 closed）。'
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
    from app.database import get_db
    import math

    db = get_db()
    tiger = get_tiger_trade_client()

    # 1. 获取账户权益
    try:
        assets = await tiger.get_account_assets()
        equity = assets.get("net_liquidation", 0) if assets else 0
        if equity <= 0:
            return HTMLResponse('<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm"><span class="text-sq-red">❌ 无法获取账户权益</span></div>')
    except Exception as e:
        return HTMLResponse(f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm"><span class="text-sq-red">❌ {e}</span></div>')

    target_per_pos = equity / RC.TOP_N

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

        # 重新下 MKT 单 — 重新计算正确数量（使用 RC.TOP_N 等权分配）
        try:
            from app.config.rotation_watchlist import RotationConfig as RC
            entry_price = pos.get("entry_price") or 0
            if entry_price <= 0:
                # 从 Tiger 获取实时价格
                try:
                    quote_data = await tiger.get_stock_quote(ticker) if hasattr(tiger, 'get_stock_quote') else {}
                    entry_price = (quote_data or {}).get("latest_price", 0)
                except Exception:
                    pass
            if entry_price > 0:
                qty = await calculate_position_size(tiger, entry_price, max_positions=RC.TOP_N)
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

def _extract_combo_fields(result: dict) -> dict:
    """Extract the fields needed for frontend combo display."""
    return {
        "cumulative_return": result["cumulative_return"],
        "spy_cumulative_return": result["spy_cumulative_return"],
        "qqq_cumulative_return": result.get("qqq_cumulative_return", 0),
        "annualized_return": result["annualized_return"],
        "annualized_vol": result["annualized_vol"],
        "sharpe_ratio": result["sharpe_ratio"],
        "max_drawdown": result["max_drawdown"],
        "win_rate": result["win_rate"],
        "alpha_vs_spy": result["alpha_vs_spy"],
        "alpha_vs_qqq": result.get("alpha_vs_qqq", 0),
        "weeks": result["weeks"],
        "top_n": result["top_n"],
        "equity_curve": result.get("equity_curve", []),
        "trades": result.get("trades", []),
        "weekly_details": result.get("weekly_details", []),
        "alpha_enhancements": result.get("alpha_enhancements"),
        "regime_version": result.get("regime_version", "v1"),
    }


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    """策略回测 — 轻量页面加载，数据按需通过API获取"""
    return _tpl("backtest.html", {"request": request})


@router.post("/htmx/backtest-run", response_class=HTMLResponse)
async def htmx_backtest_run(request: Request):
    """运行回测并返回结果 partial（HTMX），结果会缓存6小时"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2018-01-01")
        end_date = form.get("end_date", "") or _last_friday()
        top_n = int(form.get("top_n", 3))
        holding_bonus = float(form.get("holding_bonus", 1.0))

        # Clamp start_date: need ≥6 months lookback from cache start (2017-01-01)
        MIN_START = "2018-01-01"
        if start_date < MIN_START:
            start_date = MIN_START

        # Check cache first — 使用统一的 _bt_cache_key 保证 holding_bonus 格式一致
        cache_key = _bt_cache_key(start_date, end_date, top_n, holding_bonus, "v1")
        result = _cache_get(cache_key)

        if result is None:
            from app.services.rotation_service import run_rotation_backtest, _slice_prefetched
            prefetched = _slice_prefetched(start_date, end_date)
            if prefetched is None:
                return _tpl("partials/_backtest_results.html", {
                    "request": request,
                    "error": "数据预热中，请稍后再试（约3-5分钟）。首次部署或重启后需要预加载历史数据。",
                })
            result = await run_rotation_backtest(
                start_date=start_date,
                end_date=end_date,
                top_n=top_n,
                holding_bonus=holding_bonus,
                _prefetched=prefetched,
            )
            # Only cache successful results
            if "error" not in result:
                _cache_set(cache_key, result, _BACKTEST_TTL)
                logger.info(f"Backtest cached: {cache_key}")

        if "error" in result:
            return _tpl("partials/_backtest_results.html", {
                "request": request,
                "error": result["error"],
            })

        return _tpl("partials/_backtest_results.html", {
            "request": request,
            "error": None,
            "cumulative_return": result["cumulative_return"],
            "spy_cumulative_return": result["spy_cumulative_return"],
            "qqq_cumulative_return": result.get("qqq_cumulative_return", 0),
            "annualized_return": result["annualized_return"],
            "annualized_vol": result["annualized_vol"],
            "sharpe_ratio": result["sharpe_ratio"],
            "max_drawdown": result["max_drawdown"],
            "win_rate": result["win_rate"],
            "alpha_vs_spy": result["alpha_vs_spy"],
            "alpha_vs_qqq": result.get("alpha_vs_qqq", 0),
            "weeks": result["weeks"],
            "top_n": result["top_n"],
            "equity_curve_json": json.dumps(result.get("equity_curve", [])),
            "trades": result.get("trades", []),
            "weekly_details": result.get("weekly_details", []),
            "alpha_enhancements": result.get("alpha_enhancements"),
        })

    except Exception as e:
        logger.error(f"Backtest error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return _tpl("partials/_backtest_results.html", {
            "request": request,
            "error": f"回测出错: {e}",
        })


# ── Async backtest job store ──────────────────────────────────────────────────
# Keyed by job_id; values: {status, result, error, cache_key, started_at}
_bt_jobs: dict = {}


def _bt_cache_key(start_date, end_date, top_n, holding_bonus, regime_version):
    # 规范化：hb=0.0（float URL参数）与 hb=0（precompute脚本int）产生相同的键
    # precompute 用 BONUS_VALUES=[0,...] 写入 "...0"；API 收到 float 0.0 不规范化会写 "...0.0" → 缓存永远 miss
    hb = 0 if holding_bonus == 0 else holding_bonus
    if regime_version == "v1":
        return f"bt_v2:{start_date}:{end_date}:{top_n}:{hb}"
    return f"bt_v2:{start_date}:{end_date}:{top_n}:{hb}:{regime_version}"


async def _run_bt_job(job_id: str, start_date, end_date, top_n, holding_bonus,
                      regime_version, cache_key):
    """Background coroutine — runs backtest and stores result in _bt_jobs."""
    import time as _t
    _bt_jobs[job_id]["started_at"] = _t.time()
    try:
        from app.services.rotation_service import run_rotation_backtest, _slice_prefetched
        prefetched = _slice_prefetched(start_date, end_date)
        if not prefetched:
            _bt_jobs[job_id].update({"status": "error",
                                     "error": "数据预热中，请稍后再试（约3-5分钟）。"})
            return

        # run_rotation_backtest 是 CPU 密集型（pandas 大量计算，无 await 让出点）。
        # 直接 await 会堵死事件循环长达 2 分钟，导致所有其他请求 499。
        # 放到线程池 + 独立 event loop 运行，主事件循环不受影响。
        def _sync_run():
            import asyncio as _aio
            loop = _aio.new_event_loop()
            try:
                return loop.run_until_complete(run_rotation_backtest(
                    start_date=start_date, end_date=end_date,
                    top_n=top_n, holding_bonus=holding_bonus,
                    _prefetched=prefetched,
                    regime_version=regime_version,
                ))
            finally:
                loop.close()

        result = await asyncio.to_thread(_sync_run)
        if "error" in result:
            _bt_jobs[job_id].update({"status": "error", "error": result["error"]})
        else:
            safe = _make_json_safe(_extract_combo_fields(result))
            _cache_set(cache_key, safe, _BACKTEST_TTL)
            _bt_jobs[job_id].update({"status": "done", "result": safe})
    except Exception as e:
        _bt_jobs[job_id].update({"status": "error", "error": str(e)})


def _last_friday() -> str:
    """返回最近一个周五的日期字符串，用作回测默认 end_date"""
    from datetime import datetime, timedelta, timezone as _tz
    today = datetime.now(_tz.utc).date()
    days_since_friday = (today.weekday() - 4) % 7
    return (today - timedelta(days=days_since_friday)).strftime("%Y-%m-%d")


@router.get("/api/backtest-combo")
async def api_backtest_combo(
    start_date: str = "2018-01-01",
    end_date: str = "",
    top_n: int = 6,
    holding_bonus: float = 0,
    regime_version: str = "v1",
):
    """
    单个组合查询。
    - 缓存命中 → 秒返回结果
    - 缓存未命中 → 返回 {status:"computing", job_id} 并在后台计算
    前端应轮询 /api/backtest-job/{job_id} 直到 status=="done"
    """
    MIN_START = "2018-01-01"
    if start_date < MIN_START:
        start_date = MIN_START
    if not end_date:
        end_date = _last_friday()
    if regime_version not in ("v1", "v2"):
        regime_version = "v1"

    cache_key = _bt_cache_key(start_date, end_date, top_n, holding_bonus, regime_version)
    # Run synchronous cache lookup in thread pool with timeout.
    # Without timeout, a slow/hanging Supabase connection blocks the thread indefinitely
    # → Cloudflare 524 timeout → HTML error page → frontend JSON parse crash.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_cache_get, cache_key), timeout=8.0
        )
    except asyncio.TimeoutError:
        logger.warning(f"Cache lookup timeout for {cache_key} — treating as cache miss")
        result = None

    # ── Fast path: cache hit ───────────────────────────────────────────────────
    if result is not None:
        if "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=500)
        return JSONResponse(_make_json_safe(_extract_combo_fields(result)))

    # ── Slow path: spawn background job ───────────────────────────────────────
    import uuid
    job_id = uuid.uuid4().hex[:12]
    _bt_jobs[job_id] = {"status": "computing", "result": None, "error": None}
    asyncio.create_task(_run_bt_job(
        job_id, start_date, end_date, top_n, holding_bonus, regime_version, cache_key
    ))
    return JSONResponse({"status": "computing", "job_id": job_id}, status_code=202)


@router.get("/api/backtest-job/{job_id}")
async def api_backtest_job(job_id: str):
    """轮询异步回测任务状态。返回 status: computing / done / error"""
    job = _bt_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    if job["status"] == "computing":
        return JSONResponse({"status": "computing"})
    if job["status"] == "error":
        return JSONResponse({"status": "error", "error": job["error"]}, status_code=500)
    # done — return result and clean up
    result = job["result"]
    _bt_jobs.pop(job_id, None)
    return JSONResponse({"status": "done", "data": result})


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
        for t in selected:
            try:
                data = await _fetch_history(t, days=30)
                if data and len(data["close"]) >= 20:
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


@router.get("/api/admin/backtest-precompute")
async def api_trigger_backtest_precompute():
    """手动触发回测预计算（预热 2018 年起点的所有 50 个 combo 缓存）"""
    try:
        from app.scheduler import scheduler as _scheduler
        asyncio.create_task(_scheduler._run_backtest_precompute())
        return JSONResponse({"status": "started", "message": "回测预计算已在后台启动，约需 10-20 分钟，完成后缓存到 Supabase"})
    except Exception as e:
        logger.error(f"Backtest precompute trigger error: {e}")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


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

        # ---- 已平仓交易 ----
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", "closed")
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

        # 2) Active positions from DB
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") == "active"]

        # 3) Tiger prices: positions API first (reliable even when market closed), then quote API
        tiger_prices = {}
        if active:
            try:
                tiger_client = get_tiger_trade_client()
                tiger_positions = await tiger_client.get_positions()
                for tp in tiger_positions:
                    tk = tp.get("ticker", "")
                    price = tp.get("latest_price", 0)
                    if tk and price > 0:
                        tiger_prices[tk] = price
            except Exception as e:
                logger.warning(f"[PUBLIC-API] Tiger positions error: {e}")
            # Fallback: QuoteClient for any missing tickers
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

        # 4) Build response
        positions_data = []
        for p in active:
            tk = p.get("ticker", "")
            entry_price = float(p.get("entry_price", 0) or 0)
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
            .order("exit_date", desc=True)
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

    # ── WF 自适应基线（walk-forward-validation.json adaptive 段）──────────────
    WF_BASELINE = {
        "sharpe":            1.76,
        "annualized_return": 0.649,
        "cumulative_return": 3.797,
        "max_drawdown":      -0.253,
        "win_rate":          0.564,
        "avg_hold_days":     7.0,   # 周度轮动，理论持仓周期
        "description":       "Walk-Forward 自适应验证（40窗口 OOS，无后视偏差）",
    }

    try:
        from app.database import get_db
        db = get_db()
        result = (
            db.table("rotation_positions")
            .select("*")
            .eq("status", "closed")
            .order("exit_date", desc=False)
            .execute()
        )
        closed = result.data or []

        # ── 计算每笔交易指标 ───────────────────────────────────────────────────
        trades = []
        for p in closed:
            entry = float(p.get("entry_price") or 0)
            exit_ = float(p.get("exit_price") or 0)
            if entry <= 0 or exit_ <= 0:
                continue

            ret = (exit_ - entry) / entry

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

            trades.append({
                "ticker":      p.get("ticker", ""),
                "return":      round(ret, 4),
                "hold_days":   hold_days,
                "entry_date":  entry_date_str,
                "exit_date":   exit_date_str,
                "exit_reason": p.get("exit_reason", ""),
                "entry_price": round(entry, 2),
                "exit_price":  round(exit_, 2),
            })

        if len(trades) < 3:
            return JSONResponse({
                "status": "INSUFFICIENT_DATA",
                "status_label": "数据不足",
                "status_detail": f"已有 {len(trades)} 笔已平仓交易，至少需要 3 笔",
                "wf_baseline": WF_BASELINE,
                "paper_trading": {"total_trades": len(trades)},
                "comparison": {},
                "trades": trades,
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
            "total_trades":      len(trades),
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
            "trades":        trades,
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
        _source_priority = {"scheduler": 0, "weekly_report": 1, "manual_api": 2}
        date_best: dict = {}
        for snap in snapshots:
            d = snap.get("snapshot_date", "")
            tickers = snap.get("selected_tickers") or []
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
            scores_data = snap.get("scores") or []
            return_1w = None
            if scores_data and isinstance(scores_data, list):
                rets = [s.get("return_1w", 0) for s in scores_data
                        if s.get("ticker") in tickers and s.get("return_1w") is not None]
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

    # 构建 forward returns: snapshot[i] 的 selected_tickers 在 snapshot[i+1] 中的 return_1w
    yearly_returns = defaultdict(list)  # year -> [weekly portfolio returns]

    for i in range(len(snapshots) - 1):
        curr = snapshots[i]
        nxt = snapshots[i + 1]
        selected = set(curr.get("selected_tickers") or [])
        if not selected:
            continue

        # 从下一个快照的 scores 中取这些 ticker 的 return_1w (=实际持仓收益)
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
            avg_ret = sum(rets) / len(rets)
            # 归属到 nxt 的日期所在年 (这是收益实现的时间)
            nxt_date = nxt.get("snapshot_date", "")
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

    # 总计
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
            db_years_set = {y["year"].replace(" YTD", "") for y in db_data["years"]}

            if static_data and static_data.get("years"):
                # 3) 混合：静态历史年份 + DB 覆盖的年份用 DB 数据
                merged_years = []
                for sy in static_data["years"]:
                    sy_key = sy["year"].replace(" YTD", "")
                    if sy_key not in db_years_set:
                        # 静态历史年份（DB 中没有），直接保留
                        merged_years.append(sy)

                # 加入 DB 计算的年份（覆盖静态中相同年份）
                merged_years.extend(db_data["years"])
                # 按年份排序
                merged_years.sort(key=lambda y: y["year"].replace(" YTD", "9999") if "YTD" in y["year"] else y["year"])

                # 用合并后的数据重算 total（静态 total 保留 backtest 特有字段）
                static_total = static_data.get("total", {})
                db_total = db_data.get("total", {})
                # 保留静态中 DB 无法计算的字段
                merged_total = {**static_total, **db_total}

                return JSONResponse({
                    "years": merged_years,
                    "total": merged_total,
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

        # 合并 total
        existing_total = existing.get("total", {})
        db_total = db_data.get("total", {})
        merged_total = {**existing_total, **db_total}

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
        from app.services.supabase_client import get_supabase
        supabase = get_supabase()
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
        from app.services.supabase_client import get_supabase
        supabase = get_supabase()
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
    """读取最新策略矩阵回测结果 JSON 文件"""
    import os
    import glob as _glob

    results_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "scripts", "strategy_matrix_results"
    )

    def _load_latest(prefix: str) -> dict:
        """读取指定前缀的最新文件"""
        pattern = os.path.join(results_dir, f"{prefix}_*.json")
        files = sorted(_glob.glob(pattern))
        if not files:
            return {}
        try:
            with open(files[-1], "r", encoding="utf-8") as f:
                raw = f.read()
            # 替换 JSON 中的 NaN（Python/JS 均不支持）
            raw = raw.replace(": NaN", ": null").replace(":NaN", ":null")
            return json.loads(raw)
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

    return JSONResponse({
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
        },
    })


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
