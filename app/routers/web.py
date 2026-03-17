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
from fastapi import APIRouter, Request, Query, Form
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

    # Sector aggregation (pure computation)
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


@router.get("/rotation/sector/{sector_name}", response_class=HTMLResponse)
async def rotation_sector_detail(request: Request, sector_name: str):
    """板块详情页 — 趋势图 + 个股列表，优先 sector_snapshots，回退到 cache_store"""
    # Normalize sector name to lowercase for DB matching
    sector_key = sector_name.lower()
    try:
        from app.database import get_db
        db = get_db()

        # Fetch last 30 snapshots for trend chart
        trend_result = db.table("sector_snapshots").select(
            "snapshot_date, avg_score, avg_ret_1w, stock_count, regime"
        ).eq("sector", sector_key).order(
            "snapshot_date", desc=True
        ).limit(30).execute()

        trend_data = list(reversed(trend_result.data)) if trend_result.data else []

        # Latest snapshot for stock list
        latest_result = db.table("sector_snapshots").select(
            "snapshot_date, avg_score, avg_ret_1w, stock_count, top_tickers, regime"
        ).eq("sector", sector_key).order(
            "snapshot_date", desc=True
        ).limit(1).execute()

        latest = latest_result.data[0] if latest_result.data else None
        stocks = latest.get("top_tickers", []) if latest else []

        # Fallback: if sector_snapshots empty, reconstruct from cache_store
        if not stocks:
            logger.info(f"Sector detail: no sector_snapshots for '{sector_key}', trying cache_store fallback")
            try:
                cache_result = db.table("cache_store").select("value").eq(
                    "key", "rotation_scores"
                ).limit(1).execute()
                if cache_result.data:
                    cached = cache_result.data[0].get("value", {})
                    all_scores = cached.get("scores", [])
                    regime = cached.get("regime", "unknown")
                    # Filter scores matching this sector
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
                        avg_sc = sum(s.get("score", 0) for s in sector_scores) / n
                        avg_ret = sum(s.get("return_1w", 0) for s in sector_scores) / n
                        latest = {
                            "snapshot_date": "cache",
                            "avg_score": round(avg_sc, 4),
                            "avg_ret_1w": round(avg_ret, 4),
                            "stock_count": n,
                            "top_tickers": stocks,
                            "regime": regime,
                        }
                        logger.info(f"Sector detail fallback from cache: {sector_key} → {n} stocks")
            except Exception as fallback_err:
                logger.warning(f"Sector detail cache fallback failed: {fallback_err}")

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
    # Fast: only fetch DB data (positions, signals, risk) — no external API calls
    positions = []
    signal_dicts = []
    risk = {"status": "normal", "max_drawdown_pct": 0}

    try:
        from app.services.order_service import get_active_positions
        positions = await get_active_positions()
    except Exception as e:
        logger.error(f"Dashboard positions error: {e}")

    try:
        from app.services.db_service import SignalService
        signals = await SignalService.get_observe_signals()
        for sig in (signals or []):
            if hasattr(sig, "model_dump"):
                signal_dicts.append(sig.model_dump())
            elif hasattr(sig, "dict"):
                signal_dicts.append(sig.dict())
            elif isinstance(sig, dict):
                signal_dicts.append(sig)
    except Exception as e:
        logger.error(f"Dashboard signals error: {e}")

    try:
        from app.services.risk_service import RiskEngine
        risk = await RiskEngine().get_current_risk_summary()
    except Exception as e:
        logger.error(f"Dashboard risk error: {e}")

    # 每日语录 + 盈利目标
    quote = _get_daily_quote()
    total_profit = await _get_total_profit()
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
    """大盘行情卡片 SPY/QQQ/TLT/GLD"""
    from app.services.alphavantage_client import get_av_client

    benchmarks = ["SPY", "QQQ", "TLT", "GLD"]
    av = get_av_client()
    quotes_raw = await av.batch_get_quotes(benchmarks)

    cards = []
    for ticker in benchmarks:
        quote = quotes_raw.get(ticker)
        if quote:
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


@router.get("/htmx/quotes-table", response_class=HTMLResponse)
async def htmx_quotes_table(request: Request, pool: str = Query("all")):
    """实时行情表格"""
    from app.config.rotation_watchlist import (
        OFFENSIVE_ETFS, DEFENSIVE_ETFS, INVERSE_ETFS,
        LARGECAP_STOCKS, MIDCAP_STOCKS,
    )
    from app.services.alphavantage_client import get_av_client

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

    # Get rotation scores from cache — primary data source (no API calls)
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

    # Load active/pending positions for stop-loss / take-profit context
    position_map = {}
    try:
        from app.database import get_db as _get_db
        _db = _get_db()
        pos_r = _db.table("rotation_positions").select("*").neq("status", "closed").execute()
        for p in (pos_r.data or []):
            position_map[p["ticker"]] = p
    except Exception:
        pass

    # Fetch real-time AV quotes:
    # - Small pools (≤50 tickers): fetch ALL for full real-time coverage
    # - Large pools: only held positions + benchmarks (API rate limit)
    benchmarks = ["SPY", "QQQ", "TLT", "GLD"]
    if len(unique_tickers) <= 50:
        realtime_tickers = list(set(unique_tickers + list(position_map.keys()) + benchmarks))
    else:
        realtime_tickers = list(set(list(position_map.keys()) + benchmarks))
    realtime_quotes = {}
    if realtime_tickers:
        av = get_av_client()
        realtime_quotes = await av.batch_get_quotes(realtime_tickers)

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
        rt = realtime_quotes.get(ticker)  # real-time quote (only for held + benchmarks)

        # Price: prefer real-time quote, fallback to rotation score's cached price
        has_realtime = rt is not None
        if rt:
            price = float(rt.get("latest_price") or 0)
            change_percent = rt.get("change_percent", 0)
            volume = rt.get("volume", 0)
        else:
            price = float(score_data.get("current_price") or 0)
            # Use 1W return as change indicator when real-time data unavailable
            change_percent = score_data.get("return_1w", 0) or 0
            volume = None  # None = unavailable, distinct from 0

        if price == 0 and not score_data:
            continue  # Skip tickers with no data at all

        # Position enrichment
        pos = position_map.get(ticker)
        is_held = pos is not None
        stop_loss_breach = False
        take_profit_breach = False
        pnl_pct = None
        entry_price = None
        stop_loss = None
        take_profit = None
        pos_status = None

        if pos:
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
            "name": score_data.get("name", "") or info.get("name", ""),
            "sector": score_data.get("sector", "") or info.get("sector", ""),
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
        -(1 if x["stop_loss_breach"] or x["take_profit_breach"] else 0),
        -x["is_held"],
        -(x["change_percent"] or 0),
    ))

    return _tpl("partials/_quotes_table.html", {
        "request": request,
        "quotes": quotes,
        "alerts": alerts,
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
    """持仓列表（HTMX局部）— 返回 active + pending_exit 状态，Tiger 实时行情"""
    try:
        from app.services.rotation_service import get_current_positions
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") in ("active", "pending_exit")]

        # Enrich with Tiger real-time prices (positions API > quote API > DB fallback)
        if active:
            try:
                from app.services.order_service import get_tiger_trade_client
                tiger_client = get_tiger_trade_client()
                tiger_positions = await tiger_client.get_positions()
                # Build ticker->price map from Tiger positions
                tiger_prices = {}
                for tp in tiger_positions:
                    tk = tp.get("ticker", "")
                    price = tp.get("latest_price", 0)
                    if tk and price > 0:
                        tiger_prices[tk] = price
                if tiger_prices:
                    logger.info(f"[POSITIONS] Tiger持仓价格: {tiger_prices}")
                # If Tiger positions didn't cover all, try QuoteClient
                missing = [p["ticker"] for p in active if p.get("ticker") and p["ticker"] not in tiger_prices]
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
                # Apply prices to positions
                for p in active:
                    tk = p.get("ticker")
                    if tk and tk in tiger_prices:
                        p["current_price"] = tiger_prices[tk]
                        entry = p.get("entry_price") or 0
                        if entry > 0:
                            p["unrealized_pnl_pct"] = (p["current_price"] - entry) / entry
            except Exception as e:
                logger.warning(f"[POSITIONS] Tiger价格获取失败，使用DB快照: {e}")

        return _tpl("partials/_positions.html", {
            "request": request,
            "positions": active,
        })
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


@router.get("/htmx/pending-entries", response_class=HTMLResponse)
async def htmx_pending_entries(request: Request):
    """待进场列表（HTMX局部）— pending_entry 状态，含入场条件检测"""
    try:
        from app.services.rotation_service import (
            get_current_positions, _fetch_history, _compute_ma, _compute_atr, RC,
        )
        import numpy as np

        all_positions = await get_current_positions() or []
        pending = [p for p in all_positions if p.get("status") == "pending_entry"]

        # Enrich with current price and entry conditions
        for p in pending:
            ticker = p.get("ticker", "")
            try:
                data = await _fetch_history(ticker, days=30)
                if data and len(data["close"]) >= 20:
                    closes = data["close"]
                    price = float(closes[-1])
                    atr = _compute_atr(data["high"], data["low"], closes)
                    ma5 = _compute_ma(closes, RC.ENTRY_MA_PERIOD)
                    avg_vol = float(np.mean(data["volume"][-RC.ENTRY_VOL_PERIOD:])) if len(data["volume"]) >= RC.ENTRY_VOL_PERIOD else 0
                    cur_vol = float(data["volume"][-1])

                    p["current_price"] = price
                    p["entry_price"] = round(price, 2)
                    p["stop_loss"] = round(price - RC.ATR_STOP_MULTIPLIER * atr, 2)
                    p["take_profit"] = round(price + RC.ATR_TARGET_MULTIPLIER * atr, 2)
                    p["above_ma5"] = price > ma5
                    p["vol_confirmed"] = cur_vol > avg_vol if avg_vol > 0 else False
                    p["ma5_value"] = round(ma5, 2)
                    p["vol_ratio"] = round(cur_vol / avg_vol, 1) if avg_vol > 0 else 0
            except Exception:
                pass

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
                    update["stop_loss"] = round(fill_price - RC.ATR_STOP_MULTIPLIER * atr14, 2)
                    update["take_profit"] = round(fill_price + RC.ATR_TARGET_MULTIPLIER * atr14, 2)
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
        start_date = form.get("start_date", "2022-07-01")
        end_date = form.get("end_date", "2026-03-15")
        top_n = int(form.get("top_n", 3))
        holding_bonus = float(form.get("holding_bonus", 1.0))

        # Clamp start_date: need ≥6 months lookback from cache start (2021-07-01)
        MIN_START = "2022-01-01"
        if start_date < MIN_START:
            start_date = MIN_START

        # Check cache first (v2 = alpha enhancement engine)
        cache_key = f"bt_v2:{start_date}:{end_date}:{top_n}:{holding_bonus}"
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
    if regime_version == "v1":
        return f"bt_v2:{start_date}:{end_date}:{top_n}:{holding_bonus}"
    return f"bt_v2:{start_date}:{end_date}:{top_n}:{holding_bonus}:{regime_version}"


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
        result = await run_rotation_backtest(
            start_date=start_date, end_date=end_date,
            top_n=top_n, holding_bonus=holding_bonus,
            _prefetched=prefetched,
            regime_version=regime_version,
        )
        if "error" in result:
            _bt_jobs[job_id].update({"status": "error", "error": result["error"]})
        else:
            safe = _make_json_safe(_extract_combo_fields(result))
            _cache_set(cache_key, safe, _BACKTEST_TTL)
            _bt_jobs[job_id].update({"status": "done", "result": safe})
    except Exception as e:
        _bt_jobs[job_id].update({"status": "error", "error": str(e)})


@router.get("/api/backtest-combo")
async def api_backtest_combo(
    start_date: str = "2022-07-01",
    end_date: str = "2026-03-15",
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
    MIN_START = "2022-01-01"
    if start_date < MIN_START:
        start_date = MIN_START
    if regime_version not in ("v1", "v2"):
        regime_version = "v1"

    cache_key = _bt_cache_key(start_date, end_date, top_n, holding_bonus, regime_version)
    result = _cache_get(cache_key)

    # ── Fast path: cache hit ───────────────────────────────────────────────────
    if result is not None:
        if "error" in result:
            return JSONResponse({"error": result["error"]}, status_code=500)
        return JSONResponse(_make_json_safe(_extract_combo_fields(result)))

    # ── Slow path: spawn background job ───────────────────────────────────────
    import uuid, asyncio
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


@router.post("/htmx/backtest-optimize", response_class=HTMLResponse)
async def htmx_backtest_optimize(request: Request):
    """AI参数优化 — 网格搜索最优 top_n × holding_bonus 组合"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2022-07-01")
        end_date = form.get("end_date", "2026-03-15")

        # Clamp start_date
        MIN_START = "2022-01-01"
        if start_date < MIN_START:
            start_date = MIN_START

        # Check cache
        cache_key = f"opt:{start_date}:{end_date}"
        result = _cache_get(cache_key)

        if result is None:
            from app.services.rotation_service import run_parameter_optimization
            result = await run_parameter_optimization(
                start_date=start_date,
                end_date=end_date,
            )
            _cache_set(cache_key, result, _BACKTEST_TTL)

        return _tpl("partials/_optimize_results.html", {
            "request": request,
            "result": result,
        })

    except Exception as e:
        logger.error(f"Optimization error: {e}")
        return HTMLResponse(f'<div class="text-sq-red text-center py-4">优化出错: {e}</div>')


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

        # Compute entry/stop/target for all selected tickers
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
                    stop = round(price - RC.ATR_STOP_MULTIPLIER * atr, 2)
                    target = round(price + RC.ATR_TARGET_MULTIPLIER * atr, 2)
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


@router.get("/api/public/rotation-history", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_rotation_history(request: Request):
    """公开API：返回周度轮动快照历史 (从DB读取，自动新增)"""
    try:
        db = get_db()
        result = (
            db.table("rotation_snapshots")
            .select("snapshot_date, regime, selected_tickers, scores, created_at")
            .order("snapshot_date", desc=True)
            .limit(52)  # 最近一年
            .execute()
        )
        snapshots = result.data or []

        # 同时获取已平仓交易用于 track record 合并展示
        closed_result = (
            db.table("rotation_positions")
            .select("ticker, entry_price, exit_price, entry_date, exit_date, exit_reason, status")
            .eq("status", "closed")
            .order("exit_date", desc=True)
            .execute()
        )
        closed_trades = closed_result.data or []

        history = []
        for snap in snapshots:
            tickers = snap.get("selected_tickers") or []
            # 从 scores 中提取周收益（如果有）
            scores_data = snap.get("scores") or []
            weekly_return = None
            if scores_data and isinstance(scores_data, list):
                # scores 中每个 ticker 的 weekly return 取平均
                rets = [s.get("weekly_return", 0) for s in scores_data if s.get("ticker") in tickers and s.get("weekly_return") is not None]
                if rets:
                    weekly_return = round(sum(rets) / len(rets), 4)

            history.append({
                "week": snap.get("snapshot_date", ""),
                "regime": (snap.get("regime") or "unknown").upper(),
                "holdings": tickers,
                "weekly_return": weekly_return,
                "snapshot_date": snap.get("snapshot_date", ""),
            })

        # 计算累积收益 (从最早到最新)
        sorted_history = sorted(history, key=lambda x: x["week"])
        cumulative = 1.0
        for item in sorted_history:
            if item["weekly_return"] is not None:
                cumulative *= (1 + item["weekly_return"])
            item["cumulative"] = round(cumulative, 4)

        # 恢复倒序
        history = sorted(history, key=lambda x: x["week"], reverse=True)

        # 标记最新一周
        if history:
            history[0]["is_latest"] = True

        # 已平仓交易汇总
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


@router.get("/api/public/yearly-performance", response_class=JSONResponse)
@_limiter.limit("30/minute")
async def api_public_yearly_performance(request: Request):
    """公开API：从rotation_snapshots自动计算年度业绩表"""
    try:
        db = get_db()
        # 获取所有快照
        result = (
            db.table("rotation_snapshots")
            .select("snapshot_date, regime, scores, selected_tickers")
            .order("snapshot_date", desc=False)
            .execute()
        )
        snapshots = result.data or []

        if not snapshots:
            # 降级到静态JSON
            return JSONResponse({"source": "static", "fallback": True})

        # 按年分组计算
        from collections import defaultdict
        import math
        yearly_returns = defaultdict(list)  # year -> [weekly_returns]

        for snap in snapshots:
            sd = snap.get("snapshot_date", "")
            if not sd:
                continue
            year = sd[:4]
            scores_data = snap.get("scores") or []
            tickers = snap.get("selected_tickers") or []
            if scores_data and isinstance(scores_data, list):
                rets = [s.get("weekly_return", 0) for s in scores_data
                        if s.get("ticker") in tickers and s.get("weekly_return") is not None]
                if rets:
                    avg_ret = sum(rets) / len(rets)
                    yearly_returns[year].append(avg_ret)

        # 获取SPY/QQQ基准数据
        spy_qqq = {}
        try:
            from app.services.rotation_service import _fetch_history
            for ticker in ["SPY", "QQQ"]:
                data = await _fetch_history(ticker, days=1300)  # ~5年
                if data and len(data["close"]) > 0:
                    spy_qqq[ticker] = data
        except Exception as e:
            logger.warning(f"[YEARLY-PERF] Failed to fetch benchmark data: {e}")

        # 构建年度数据
        years = []
        current_year = str(date.today().year)

        for year in sorted(yearly_returns.keys()):
            weekly_rets = yearly_returns[year]
            # 复利计算年度总收益
            cumulative = 1.0
            for r in weekly_rets:
                cumulative *= (1 + r)
            strategy_return = round(cumulative - 1, 4)

            # 年化收益 & 夏普 (对非当前年)
            n_weeks = len(weekly_rets)
            annualized = None
            sharpe = None
            if year != current_year and n_weeks >= 20:
                annualized = round(strategy_return, 4)  # 已经是整年
                import numpy as np
                mean_w = sum(weekly_rets) / len(weekly_rets)
                std_w = float(np.std(weekly_rets)) if len(weekly_rets) > 1 else 0.001
                sharpe = round((mean_w / std_w) * math.sqrt(52), 2) if std_w > 0 else None

            # SPY/QQQ 年度收益
            spy_return = None
            qqq_return = None
            for ticker, key in [("SPY", "spy_return"), ("QQQ", "qqq_return")]:
                if ticker in spy_qqq:
                    closes = spy_qqq[ticker]["close"]
                    dates = spy_qqq[ticker].get("dates", [])
                    if dates:
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
            # Max drawdown
            peak = 1.0
            max_dd = 0.0
            cum = 1.0
            for r in all_rets:
                cum *= (1 + r)
                peak = max(peak, cum)
                dd = (cum - peak) / peak
                max_dd = min(max_dd, dd)
            total["max_drawdown"] = round(max_dd, 4)
            # Win rate
            wins = sum(1 for r in all_rets if r > 0)
            total["win_rate"] = round(wins / len(all_rets), 3)

        return JSONResponse({
            "years": years,
            "total": total,
            "last_updated": date.today().isoformat(),
            "source": "database",
        })
    except Exception as e:
        logger.error(f"[PUBLIC-API] yearly-performance error: {e}", exc_info=True)
        return JSONResponse({"source": "static", "fallback": True, "error": str(e)}, status_code=200)


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
