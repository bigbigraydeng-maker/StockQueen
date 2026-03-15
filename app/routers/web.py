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
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")

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
_PERSISTENT_PREFIXES = ("adaptive_v1:", "bt_v2:", "opt:", "rotation_scores")


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
    return templates.TemplateResponse("rotation.html", {
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

    return templates.TemplateResponse("partials/_rotation_full.html", {
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
    """板块详情页 — 趋势图 + 个股列表，数据全部从 sector_snapshots DB读取"""
    try:
        from app.database import get_db
        db = get_db()

        # Fetch last 30 snapshots for trend chart
        trend_result = db.table("sector_snapshots").select(
            "snapshot_date, avg_score, avg_ret_1w, stock_count, regime"
        ).eq("sector", sector_name).order(
            "snapshot_date", desc=True
        ).limit(30).execute()

        trend_data = list(reversed(trend_result.data)) if trend_result.data else []

        # Latest snapshot for stock list
        latest_result = db.table("sector_snapshots").select(
            "snapshot_date, avg_score, avg_ret_1w, stock_count, top_tickers, regime"
        ).eq("sector", sector_name).order(
            "snapshot_date", desc=True
        ).limit(1).execute()

        latest = latest_result.data[0] if latest_result.data else None
        stocks = latest.get("top_tickers", []) if latest else []

        return templates.TemplateResponse("sector_detail.html", {
            "request": request,
            "sector_name": sector_name,
            "trend_data": trend_data,
            "stocks": stocks,
            "latest": latest,
        })
    except Exception as e:
        logger.error(f"Sector detail error for {sector_name}: {e}", exc_info=True)
        return templates.TemplateResponse("sector_detail.html", {
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
        from app.services.rotation_service import get_current_positions
        all_positions = await get_current_positions() or []
        positions = [p for p in all_positions if p.get("status") == "active"]
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

    return templates.TemplateResponse("dashboard.html", {
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

        return templates.TemplateResponse("knowledge.html", {
            "request": request,
            "entries": recent or [],
            "stats": stats_dict,
        })

    except Exception as e:
        logger.error(f"Knowledge page error: {e}")
        return templates.TemplateResponse("knowledge.html", {
            "request": request,
            "entries": [],
            "stats": {"total_entries": 0, "by_source_type": {}, "by_category": {}},
        })


# ==================== HTMX PARTIAL ROUTES ====================

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

        return templates.TemplateResponse("partials/_rotation_table.html", {
            "request": request,
            "scores": score_dicts,
        })

    except Exception as e:
        logger.error(f"Rotation table error: {e}")
        return HTMLResponse('<tr><td colspan="10" class="px-3 py-4 text-center text-sq-red">加载失败</td></tr>')


@router.get("/htmx/positions", response_class=HTMLResponse)
async def htmx_positions(request: Request):
    """持仓列表（HTMX局部）— 只返回 active 状态，Tiger 实时行情"""
    try:
        from app.services.rotation_service import get_current_positions
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") == "active"]

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

        return templates.TemplateResponse("partials/_positions.html", {
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

        return templates.TemplateResponse("partials/_pending_entries.html", {
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
                    <span class="text-[10px] text-gray-500 ml-1">({s}{upnl_pct:.1f}%)</span>
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

    # Find active positions without tiger_order_id
    try:
        pos_result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, stop_loss, take_profit, status, tiger_order_id, quantity")
            .in_("status", ["active", "pending_entry"])
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
            '暂无需要下单的仓位</div>'
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

        # Calculate position size
        try:
            qty = await calculate_position_size(tiger, entry_price)
            if qty <= 0:
                results.append({"ticker": ticker, "success": False, "msg": "计算仓位为0"})
                continue
        except Exception as e:
            results.append({"ticker": ticker, "success": False, "msg": f"仓位计算失败: {e}"})
            continue

        # Place bracket order (only for stocks NOT already held in Tiger)
        try:
            sl = round(stop_loss, 2) if stop_loss else None
            tp = round(take_profit, 2) if take_profit else None
            result = await tiger.place_buy_order(
                ticker=ticker,
                quantity=qty,
                limit_price=round(entry_price, 2),
                stop_loss=sl,
                take_profit=tp,
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
                    "msg": f"✅ 买入 {qty}股 @ ${entry_price:.2f} | SL=${sl} TP=${tp} | 订单ID: {order_id[:8]}..."
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
        return templates.TemplateResponse("partials/_signals.html", {
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
        return templates.TemplateResponse("partials/_risk_badge.html", {
            "request": request,
            "risk": risk,
        })
    except Exception as e:
        logger.error(f"Risk badge error: {e}")
        return templates.TemplateResponse("partials/_risk_badge.html", {
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
        return templates.TemplateResponse("partials/_knowledge_list.html", {
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

        return templates.TemplateResponse("partials/_search_results.html", {
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
        return templates.TemplateResponse("partials/_knowledge_stats.html", {
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
            return templates.TemplateResponse("partials/_knowledge_list.html", {
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

        return templates.TemplateResponse("partials/_knowledge_list.html", {
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
            return templates.TemplateResponse("partials/_knowledge_list.html", {
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

        return templates.TemplateResponse("partials/_knowledge_list.html", {
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
    }


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    """策略回测 — 轻量页面加载，数据按需通过API获取"""
    return templates.TemplateResponse("backtest.html", {"request": request})


@router.post("/htmx/backtest-run", response_class=HTMLResponse)
async def htmx_backtest_run(request: Request):
    """运行回测并返回结果 partial（HTMX），结果会缓存6小时"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2022-07-01")
        end_date = form.get("end_date", "2026-03-15")
        top_n = int(form.get("top_n", 3))
        holding_bonus = float(form.get("holding_bonus", 1.0))

        # Check cache first (v2 = alpha enhancement engine)
        cache_key = f"bt_v2:{start_date}:{end_date}:{top_n}:{holding_bonus}"
        result = _cache_get(cache_key)

        if result is None:
            from app.services.rotation_service import run_rotation_backtest
            result = await run_rotation_backtest(
                start_date=start_date,
                end_date=end_date,
                top_n=top_n,
                holding_bonus=holding_bonus,
            )
            # Only cache successful results
            if "error" not in result:
                _cache_set(cache_key, result, _BACKTEST_TTL)
                logger.info(f"Backtest cached: {cache_key}")

        if "error" in result:
            return templates.TemplateResponse("partials/_backtest_results.html", {
                "request": request,
                "error": result["error"],
            })

        return templates.TemplateResponse("partials/_backtest_results.html", {
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
        return templates.TemplateResponse("partials/_backtest_results.html", {
            "request": request,
            "error": f"回测出错: {e}",
        })


@router.get("/api/backtest-combo")
async def api_backtest_combo(
    start_date: str = "2022-07-01",
    end_date: str = "2026-03-15",
    top_n: int = 6,
    holding_bonus: float = 0,
):
    """单个组合查询：先查缓存，命中秒返回；未命中则实时计算"""
    cache_key = f"bt_v2:{start_date}:{end_date}:{top_n}:{holding_bonus}"
    result = _cache_get(cache_key)

    if result is None:
        # Cache miss — compute on the fly
        from app.services.rotation_service import run_rotation_backtest
        result = await run_rotation_backtest(
            start_date=start_date, end_date=end_date,
            top_n=top_n, holding_bonus=holding_bonus,
        )
        if "error" not in result:
            _cache_set(cache_key, _make_json_safe(result), _BACKTEST_TTL)

    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=500)

    return JSONResponse(_make_json_safe(_extract_combo_fields(result)))


@router.post("/htmx/backtest-optimize", response_class=HTMLResponse)
async def htmx_backtest_optimize(request: Request):
    """AI参数优化 — 网格搜索最优 top_n × holding_bonus 组合"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2022-07-01")
        end_date = form.get("end_date", "2026-03-15")

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

        return templates.TemplateResponse("partials/_optimize_results.html", {
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


# ==================== SCHEDULER LOGS ====================

@router.get("/htmx/scheduler-logs", response_class=HTMLResponse)
async def htmx_scheduler_logs(request: Request):
    """调度器活动日志（HTMX局部，每60秒刷新）"""
    try:
        from app.scheduler import get_scheduler_logs
        logs = get_scheduler_logs(limit=30)
        return templates.TemplateResponse("partials/_scheduler_logs.html", {
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
    """历史交易 — 显示所有已平仓交易记录"""
    trades = []
    summary = {"total_trades": 0, "win_rate": 0, "avg_return": 0, "avg_hold_days": 0}

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
    except Exception as e:
        logger.error(f"Trades page error: {e}")

    return templates.TemplateResponse("trades.html", {
        "request": request,
        "trades": trades,
        "summary": summary,
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

    return templates.TemplateResponse("partials/_trade_history.html", {
        "request": request,
        "trades": trades,
    })


# ==================================================================
# Strategy Parameters Page (策略锁定)
# ==================================================================

@router.get("/strategy", response_class=HTMLResponse)
async def strategy_page(request: Request):
    """策略锁定 — 显示 V4 Walk-Forward 验证后的锁定参数"""
    strategy_data = {}
    try:
        config_path = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
            "app", "config", "key2goldenmine.json"
        )
        with open(config_path, "r", encoding="utf-8") as f:
            strategy_data = json.load(f)
    except Exception as e:
        logger.error(f"Strategy page error loading config: {e}")

    return templates.TemplateResponse("strategy.html", {
        "request": request,
        "strategy": strategy_data,
    })


# ==================================================================
# Public API — for stockqueen.co (real-time signals + prices)
# ==================================================================

@router.get("/api/public/signals", response_class=JSONResponse)
async def api_public_signals():
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
async def api_public_signal_history():
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
