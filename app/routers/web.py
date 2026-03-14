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
# ============================================================
# THREE-TIER CACHE: Memory → Disk → Supabase (persistent)
# ============================================================
# Memory: fastest, lost on restart
# Disk: survives within deploy, lost on new deploy
# Supabase: permanent, survives everything
# ============================================================
_cache: Dict[str, Tuple[float, Any]] = {}  # key -> (expire_ts, data)

_BACKTEST_TTL = 3600 * 24 * 7  # 7 days — backtest results change only when strategy changes
_ROTATION_TTL = 3600 * 8       # 8 hours — scores update daily

import os as _os
_CACHE_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), ".cache")
_os.makedirs(_CACHE_DIR, exist_ok=True)

# Keys that should be persisted (disk + Supabase)
_PERSISTENT_PREFIXES = ("adaptive_v1:", "bt_v2:", "opt:", "rotation_scores")


def _disk_cache_path(key: str) -> str:
    """Get file path for a disk-cached key."""
    safe_key = key.replace(":", "_").replace("/", "_").replace(" ", "_")
    return _os.path.join(_CACHE_DIR, f"{safe_key}.json")


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


_db_cache_available = None  # None = unknown, True/False = tested

def _db_cache_get(key: str) -> Any:
    """Read from Supabase cache_store table. Gracefully no-op if table missing."""
    global _db_cache_available
    if _db_cache_available is False:
        return None
    try:
        from app.database import get_db
        db = get_db()
        result = db.table("cache_store").select("value").eq("key", key).execute()
        _db_cache_available = True
        if result.data and len(result.data) > 0:
            logger.info(f"DB cache hit: {key}")
            return result.data[0]["value"]
    except Exception as e:
        if "cache_store" in str(e):
            _db_cache_available = False
            logger.warning("cache_store table not found — run SQL in Supabase Dashboard: "
                           "CREATE TABLE cache_store (key VARCHAR(255) PRIMARY KEY, value JSONB NOT NULL, "
                           "updated_at TIMESTAMPTZ DEFAULT NOW());")
        else:
            logger.debug(f"DB cache read error for {key}: {e}")
    return None


def _db_cache_set(key: str, value: Any) -> None:
    """Write to Supabase cache_store table (upsert). Gracefully no-op if table missing."""
    global _db_cache_available
    if _db_cache_available is False:
        return
    try:
        from app.database import get_db
        db = get_db()
        safe_value = _make_json_safe(value)
        db.table("cache_store").upsert({
            "key": key,
            "value": safe_value,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, on_conflict="key").execute()
        _db_cache_available = True
        logger.info(f"DB cache saved: {key}")
    except Exception as e:
        if "cache_store" in str(e):
            _db_cache_available = False
        logger.warning(f"DB cache write error for {key}: {e}")


def _cache_get(key: str) -> Any:
    """Three-tier cache read: memory → disk → Supabase."""
    # 1. Memory cache (fastest)
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    if entry:
        del _cache[key]

    is_persistent = any(key.startswith(p) for p in _PERSISTENT_PREFIXES)

    # 2. Disk cache fallback
    if is_persistent:
        path = _disk_cache_path(key)
        if _os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _cache[key] = (time.time() + _BACKTEST_TTL, data)
                logger.info(f"Disk cache hit: {key}")
                return data
            except Exception as e:
                logger.warning(f"Disk cache read error for {key}: {e}")

        # 3. Supabase cache fallback (survives deploy)
        data = _db_cache_get(key)
        if data is not None:
            # Restore to memory + disk
            _cache[key] = (time.time() + _BACKTEST_TTL, data)
            try:
                with open(_disk_cache_path(key), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except Exception:
                pass
            return data

    return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    """Three-tier cache write: memory + disk + Supabase."""
    _cache[key] = (time.time() + ttl, value)

    if any(key.startswith(p) for p in _PERSISTENT_PREFIXES):
        # Disk cache
        try:
            safe_value = _make_json_safe(value)
            path = _disk_cache_path(key)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(safe_value, f, ensure_ascii=False)
            size_kb = _os.path.getsize(path) / 1024
            logger.info(f"Disk cache saved: {key} ({size_kb:.0f}KB)")
        except Exception as e:
            logger.warning(f"Disk cache write error for {key}: {e}")

        # Supabase cache (permanent, survives deploy)
        _db_cache_set(key, value)


# ==================== BACKGROUND TASKS ====================
# Track long-running background tasks (adaptive analysis etc.)
_bg_tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> {"status": "running"|"done"|"error", "progress": str, "result": ...}


async def _run_adaptive_background(task_id: str, cache_key: str, start_date: str, end_date: str):
    """Run adaptive backtest in background, store result when done."""
    try:
        _bg_tasks[task_id] = {"status": "running", "progress": "正在预加载市场数据..."}

        def _update_progress(msg: str):
            if task_id in _bg_tasks:
                _bg_tasks[task_id]["progress"] = msg

        from app.services.rotation_service import run_adaptive_backtest
        result = await run_adaptive_backtest(
            start_date=start_date,
            end_date=end_date,
            progress_callback=_update_progress,
        )
        if "error" not in result:
            _cache_set(cache_key, result, _BACKTEST_TTL)
            _bg_tasks[task_id] = {"status": "done", "progress": "分析完成"}
            logger.info(f"Background adaptive task {task_id} completed successfully")
        else:
            _bg_tasks[task_id] = {"status": "error", "progress": result["error"]}
            logger.warning(f"Background adaptive task {task_id} returned error: {result['error']}")
    except Exception as e:
        logger.error(f"Background adaptive task {task_id} failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        _bg_tasks[task_id] = {"status": "error", "progress": f"分析出错: {e}"}


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


@router.get("/rotation", response_class=HTMLResponse)
async def rotation_page(request: Request):
    """轮动策略可视化页面"""
    try:
        from app.services.rotation_service import (
            get_current_positions, _detect_regime, RC,
        )
        from app.config.rotation_watchlist import get_ticker_info

        # 1. Get cached scores
        cached_scores = _cache_get("rotation_scores")
        scores = []
        regime = "unknown"
        if cached_scores is not None:
            raw = cached_scores.get("scores", []) if isinstance(cached_scores, dict) else cached_scores
            for s in raw:
                if hasattr(s, "model_dump"):
                    scores.append(s.model_dump())
                elif isinstance(s, dict):
                    scores.append(s)
            scores.sort(key=lambda x: x.get("score", 0), reverse=True)
            regime = cached_scores.get("regime", "unknown") if isinstance(cached_scores, dict) else "unknown"

        if not regime or regime == "unknown":
            try:
                regime = await _detect_regime()
            except Exception:
                regime = "unknown"

        # 2. Get current positions
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") == "active"]
        pending = [p for p in all_positions if p.get("status") == "pending_entry"]

        # 3. Top 3 selected (from scores)
        top3 = scores[:3] if scores else []

        # 4. Sector aggregation for heatmap
        sector_map = {}
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

        # 5. Rotation history (from DB)
        history = []
        try:
            from app.database import get_db
            db = get_db()
            hist_result = db.table("rotation_snapshots").select(
                "snapshot_date, regime, selected_tickers, previous_tickers, changes"
            ).order("snapshot_date", desc=True).limit(26).execute()
            history = hist_result.data if hist_result.data else []
        except Exception:
            pass

        return templates.TemplateResponse("rotation.html", {
            "request": request,
            "regime": regime,
            "scores": scores,
            "top3": top3,
            "active_positions": active,
            "pending_positions": pending,
            "sectors": sectors,
            "history": history,
        })

    except Exception as e:
        logger.error(f"Rotation page error: {e}", exc_info=True)
        return templates.TemplateResponse("rotation.html", {
            "request": request,
            "regime": "unknown",
            "scores": [],
            "top3": [],
            "active_positions": [],
            "pending_positions": [],
            "sectors": [],
            "history": [],
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
                # If Tiger positions didn't cover all, use Alpha Vantage
                missing = [p["ticker"] for p in active if p.get("ticker") and p["ticker"] not in tiger_prices]
                if missing:
                    try:
                        from app.services.alphavantage_client import get_av_client
                        av = get_av_client()
                        av_quotes = await av.batch_get_quotes(missing)
                        for t, q in av_quotes.items():
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
    """待进场列表（HTMX局部）— pending_entry 状态，含入场条件检测 + 推荐买入数量"""
    try:
        from app.services.rotation_service import (
            get_current_positions, _fetch_history, _compute_ma, _compute_atr, RC,
        )
        from app.services.order_service import calc_recommended_qty, get_tiger_trade_client
        import numpy as np

        all_positions = await get_current_positions() or []
        pending = [p for p in all_positions if p.get("status") == "pending_entry"]

        # Get account equity for position sizing (capped by config)
        account_equity = RC.POSITION_EQUITY_CAP

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

                    # Position sizing recommendation
                    qty = calc_recommended_qty(price, account_equity, RC.TOP_N)
                    p["recommended_qty"] = qty
                    p["recommended_amount"] = round(qty * price, 0) if qty > 0 else 0
                    p["account_equity"] = round(account_equity, 0)
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


@router.get("/htmx/tiger-diagnostics", response_class=HTMLResponse)
async def htmx_tiger_diagnostics(request: Request):
    """Tiger SDK 连接诊断 — 检查凭证和连接状态"""
    from app.config import settings
    lines = []

    # 1) Check env vars
    tid = settings.tiger_id
    tacc = settings.tiger_account
    tpk = settings.tiger_private_key

    lines.append(f"TIGER_ID: {'✅ ' + tid[:4] + '...' if tid else '❌ 未配置'}")
    lines.append(f"TIGER_ACCOUNT: {'✅ ' + tacc if tacc else '❌ 未配置'}")
    if tpk:
        has_begin = "-----BEGIN" in tpk
        has_newlines = "\n" in tpk
        lines.append(f"TIGER_PRIVATE_KEY: ✅ {len(tpk)}字符 | PEM头: {'是' if has_begin else '否'} | 含换行: {'是' if has_newlines else '否'}")
    else:
        lines.append("TIGER_PRIVATE_KEY: ❌ 未配置")

    # 2) Try init TradeClient
    try:
        from app.services.order_service import get_tiger_trade_client
        tiger = get_tiger_trade_client()
        assets = await tiger.get_account_assets()
        if assets:
            nlv = assets.get("net_liquidation", 0)
            lines.append(f"TradeClient: ✅ 连接成功 | NLV=${nlv:,.0f}")
        else:
            lines.append("TradeClient: ⚠️ 初始化成功但获取资产失败")
    except Exception as e:
        lines.append(f"TradeClient: ❌ {type(e).__name__}: {e}")

    # 3) Test Alpha Vantage (sole market data source)
    try:
        from app.services.alphavantage_client import get_av_client
        av = get_av_client()
        quote = await av.get_quote("SPY")
        if quote:
            lines.append(f"Alpha Vantage: ✅ SPY=${quote.get('latest_price', 0):.2f}")
        else:
            lines.append("Alpha Vantage: ⚠️ 无数据返回")
    except Exception as e:
        lines.append(f"Alpha Vantage: ❌ {type(e).__name__}: {e}")

    rows = "".join(f'<div class="text-xs font-mono py-0.5">{l}</div>' for l in lines)
    html = f"""
    <div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-1">
        <div class="text-sm font-bold text-white mb-2">🔧 Tiger SDK 诊断</div>
        {rows}
    </div>
    """
    return HTMLResponse(html)


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
            # Fetch price from Alpha Vantage
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
    应急端点：手动激活pending_entry仓位。
    安全机制：
    1. 不会覆盖已有的active仓位
    2. 会检查Tiger实际持仓，恢复被误删的仓位
    3. 使用Alpha Vantage价格作为fallback
    """
    from app.services.alphavantage_client import get_av_client
    from app.database import get_db

    db = get_db()
    results = []

    # === Step 0: 获取当前所有仓位状态 ===
    try:
        all_pos_result = (
            db.table("rotation_positions")
            .select("id, ticker, entry_price, stop_loss, take_profit, status, entry_date, quantity")
            .neq("status", "closed")
            .execute()
        )
        all_positions = all_pos_result.data if all_pos_result.data else []
    except Exception as e:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">❌ 数据库查询失败</span>'
            f'<p class="text-gray-400 mt-1">{e}</p></div>'
        )

    active_tickers = {p["ticker"] for p in all_positions if p.get("status") == "active"}
    pending_positions = [p for p in all_positions if p.get("status") == "pending_entry"]
    pending_exit_positions = [p for p in all_positions if p.get("status") == "pending_exit"]

    # === Step 1: 尝试从Tiger获取真实持仓，恢复被误标的仓位 ===
    tiger_held = {}
    try:
        from app.services.order_service import get_tiger_trade_client
        tiger = get_tiger_trade_client()
        tiger_positions = await tiger.get_positions()
        if tiger_positions:
            for tp in tiger_positions:
                t = tp.get("ticker", tp.get("symbol", ""))
                if t:
                    tiger_held[t] = tp
            logger.info(f"[ACTIVATE] Tiger实际持仓: {list(tiger_held.keys())}")
    except Exception as te:
        logger.warning(f"[ACTIVATE] Tiger获取持仓失败（将使用AV价格）: {te}")

    # === Step 2: 恢复Tiger持有但DB中被误标为pending_exit/closed的仓位 ===
    for tp_ticker, tp_data in tiger_held.items():
        if tp_ticker in active_tickers:
            continue  # 已经是active，无需处理

        # 检查是否有pending_exit记录（被rotation误标）
        mismarked = [p for p in pending_exit_positions if p["ticker"] == tp_ticker]
        if mismarked:
            pos = mismarked[0]
            db.table("rotation_positions").update({
                "status": "active",
            }).eq("id", pos["id"]).execute()
            active_tickers.add(tp_ticker)
            results.append({
                "ticker": tp_ticker, "success": True,
                "msg": f"🔄 从pending_exit恢复为active（Tiger实际持有）"
            })
            logger.info(f"[ACTIVATE] Restored {tp_ticker} from pending_exit→active (Tiger holds it)")
            continue

        # Tiger持有但DB中完全没有记录 → 创建新的active记录
        if tp_ticker not in {p["ticker"] for p in all_positions}:
            avg_cost = tp_data.get("average_cost", 0) or tp_data.get("avg_cost", 0)
            qty = tp_data.get("quantity", 0)
            if avg_cost > 0:
                atr = avg_cost * 0.03
                db.table("rotation_positions").insert({
                    "ticker": tp_ticker,
                    "status": "active",
                    "entry_price": round(avg_cost, 4),
                    "entry_date": date.today().isoformat(),
                    "stop_loss": round(avg_cost - 2 * atr, 2),
                    "take_profit": round(avg_cost + 3 * atr, 2),
                    "current_price": avg_cost,
                    "quantity": qty,
                }).execute()
                active_tickers.add(tp_ticker)
                results.append({
                    "ticker": tp_ticker, "success": True,
                    "msg": f"🆕 从Tiger同步 @ ${avg_cost:.2f} × {qty}股"
                })
                logger.info(f"[ACTIVATE] Synced {tp_ticker} from Tiger: {qty}x @ ${avg_cost:.2f}")

    # === Step 3: 激活剩余的pending_entry（排除已经active的ticker） ===
    if not pending_positions:
        if not results:
            return HTMLResponse(
                '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
                '无待进场仓位</div>'
            )
    else:
        av = get_av_client()

        for pos in pending_positions:
            ticker = pos.get("ticker", "?")
            pos_id = pos.get("id")

            # 如果这个ticker已经有active记录，跳过（防止重复激活）
            if ticker in active_tickers:
                # 关闭这个重复的pending_entry
                db.table("rotation_positions").update({
                    "status": "closed",
                    "exit_reason": "duplicate_active_exists",
                }).eq("id", pos_id).execute()
                results.append({
                    "ticker": ticker, "success": True,
                    "msg": f"⏭️ 已有active仓位，跳过并关闭重复记录"
                })
                continue

            entry_price = pos.get("entry_price", 0)
            stop_loss = pos.get("stop_loss")
            take_profit = pos.get("take_profit")

            # 优先用Tiger持仓的成本价
            if ticker in tiger_held:
                avg_cost = tiger_held[ticker].get("average_cost", 0) or tiger_held[ticker].get("avg_cost", 0)
                if avg_cost > 0:
                    entry_price = avg_cost

            # Fallback: Alpha Vantage
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

            # Calculate SL/TP if missing
            if not stop_loss or not take_profit:
                atr = entry_price * 0.03
                stop_loss = round(entry_price - 2 * atr, 2)
                take_profit = round(entry_price + 3 * atr, 2)

            # Activate in DB
            update_data = {
                "entry_price": round(entry_price, 4),
                "entry_date": pos.get("entry_date") or date.today().isoformat(),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "status": "active",
            }
            # 如果Tiger有持仓数量，同步过来
            if ticker in tiger_held:
                qty = tiger_held[ticker].get("quantity", 0)
                if qty > 0:
                    update_data["quantity"] = qty

            db.table("rotation_positions").update(update_data).eq("id", pos_id).execute()
            active_tickers.add(ticker)

            results.append({
                "ticker": ticker, "success": True,
                "msg": f"✅ 已激活 @ ${entry_price:.2f} | SL=${stop_loss} TP=${take_profit}"
            })
            logger.info(f"[ACTIVATE] {ticker} pending→active, price=${entry_price:.2f}")

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


@router.post("/api/tiger/sync-positions", response_class=HTMLResponse)
async def api_tiger_sync_positions(request: Request):
    """
    从Tiger同步真实持仓到DB。
    功能：
    1. Tiger有持仓但DB没有 → 创建active记录
    2. Tiger有持仓但DB标记为closed/pending_exit → 恢复为active
    3. DB有active但Tiger没有 → 标记提醒（不自动关闭）
    """
    from app.database import get_db

    db = get_db()
    results = []

    # 获取Tiger持仓
    tiger_held = {}
    try:
        from app.services.order_service import get_tiger_trade_client
        tiger = get_tiger_trade_client()
        tiger_positions = await tiger.get_positions()
        if tiger_positions:
            for tp in tiger_positions:
                t = tp.get("ticker", tp.get("symbol", ""))
                if t:
                    tiger_held[t] = tp
    except Exception as te:
        return HTMLResponse(
            f'<div class="bg-red-900/30 border border-red-700 rounded-lg p-4 text-sm">'
            f'<span class="text-sq-red font-bold">❌ Tiger连接失败</span>'
            f'<p class="text-gray-400 mt-1">{te}</p></div>'
        )

    if not tiger_held:
        return HTMLResponse(
            '<div class="bg-gray-800 rounded-lg p-4 text-sm text-gray-400 text-center">'
            'Tiger无持仓</div>'
        )

    # 获取DB中所有非closed仓位
    try:
        db_result = db.table("rotation_positions").select("*").neq("status", "closed").execute()
        db_positions = db_result.data if db_result.data else []
    except Exception:
        db_positions = []

    db_active = {p["ticker"]: p for p in db_positions if p.get("status") == "active"}
    db_other = {}
    for p in db_positions:
        if p.get("status") != "active":
            db_other.setdefault(p["ticker"], []).append(p)

    for ticker, tp in tiger_held.items():
        avg_cost = tp.get("average_cost", 0) or tp.get("avg_cost", 0)
        qty = tp.get("quantity", 0)

        if ticker in db_active:
            # 已经是active，更新数量
            if qty > 0 and db_active[ticker].get("quantity") != qty:
                db.table("rotation_positions").update({"quantity": qty}).eq("id", db_active[ticker]["id"]).execute()
                results.append({"ticker": ticker, "success": True, "msg": f"✅ 同步数量 {qty}股"})
            else:
                results.append({"ticker": ticker, "success": True, "msg": f"✅ 已同步（active）"})
        elif ticker in db_other:
            # 有记录但不是active → 恢复
            pos = db_other[ticker][0]
            update_data = {"status": "active"}
            if avg_cost > 0 and not pos.get("entry_price"):
                update_data["entry_price"] = round(avg_cost, 4)
            if qty > 0:
                update_data["quantity"] = qty
            db.table("rotation_positions").update(update_data).eq("id", pos["id"]).execute()
            results.append({"ticker": ticker, "success": True,
                            "msg": f"🔄 {pos.get('status')}→active @ ${avg_cost:.2f} × {qty}股"})
        else:
            # DB中完全没有 → 创建
            atr = avg_cost * 0.03 if avg_cost > 0 else 1.0
            db.table("rotation_positions").insert({
                "ticker": ticker,
                "status": "active",
                "entry_price": round(avg_cost, 4) if avg_cost else None,
                "entry_date": date.today().isoformat(),
                "stop_loss": round(avg_cost - 2 * atr, 2) if avg_cost else None,
                "take_profit": round(avg_cost + 3 * atr, 2) if avg_cost else None,
                "quantity": qty,
            }).execute()
            results.append({"ticker": ticker, "success": True,
                            "msg": f"🆕 新建 @ ${avg_cost:.2f} × {qty}股"})

    # Build HTML
    rows_html = ""
    for r in results:
        color = "text-sq-green" if r["success"] else "text-sq-red"
        rows_html += (
            f'<div class="flex items-center gap-2 py-1.5 text-xs">'
            f'<span class="font-mono font-bold text-white">{r["ticker"]}</span>'
            f'<span class="{color}">{r["msg"]}</span></div>'
        )

    html = f"""
    <div class="bg-sq-card rounded-xl border border-sq-border p-4 space-y-2">
        <div class="flex items-center justify-between">
            <span class="text-sm font-bold text-white">🔄 Tiger持仓同步结果</span>
            <span class="text-xs text-gray-400">共 {len(results)} 只</span>
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

@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    """策略回测 — 参数设置 + 结果展示（自动加载缓存结果）"""
    # Check if default params have cached results (must match key used in htmx_backtest_run)
    default_cache_key = "bt_v2:2023-01-01:2026-03-01:3:1.5"
    cached = _cache_get(default_cache_key)
    has_cache = cached is not None and "error" not in cached

    # Check if adaptive analysis has cached results
    adaptive_cache_key = "adaptive_v1:2023-01-01:2026-03-01"
    adaptive_cached = _cache_get(adaptive_cache_key)
    has_adaptive_cache = adaptive_cached is not None and "error" not in adaptive_cached

    return templates.TemplateResponse("backtest.html", {
        "request": request,
        "has_cache": has_cache,
        "has_adaptive_cache": has_adaptive_cache,
    })


@router.post("/htmx/backtest-run", response_class=HTMLResponse)
async def htmx_backtest_run(request: Request):
    """运行回测并返回结果 partial（HTMX），结果会缓存6小时"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2023-01-01")
        end_date = form.get("end_date", "2026-03-01")
        top_n = int(form.get("top_n", 3))
        holding_bonus = float(form.get("holding_bonus", 1.5))

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


@router.post("/htmx/backtest-optimize", response_class=HTMLResponse)
async def htmx_backtest_optimize(request: Request):
    """AI参数优化 — 网格搜索最优 top_n × holding_bonus 组合"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2023-01-01")
        end_date = form.get("end_date", "2026-03-01")

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


@router.post("/htmx/adaptive-run", response_class=HTMLResponse)
async def htmx_adaptive_run(request: Request):
    """AI月度自适应最优组合分析 — Walk-Forward Optimization (后台任务模式)"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2023-01-01")
        end_date = form.get("end_date", "2026-03-01")

        # Check cache first (long TTL since this is expensive)
        cache_key = f"adaptive_v1:{start_date}:{end_date}"
        result = _cache_get(cache_key)

        if result is not None and "error" not in result:
            # Cache hit — return results immediately
            return templates.TemplateResponse("partials/_adaptive_results.html", {
                "request": request,
                "result": result,
                "equity_curve_json": json.dumps(result.get("equity_curve", [])),
            })

        # No cache — launch background task
        task_id = f"adaptive_{start_date}_{end_date}"

        # Check if already running
        existing = _bg_tasks.get(task_id)
        if existing and existing["status"] == "running":
            # Already running, return polling UI
            return HTMLResponse(f'''
                <div id="adaptive-polling"
                     hx-get="/htmx/adaptive-status?task_id={task_id}&start_date={start_date}&end_date={end_date}"
                     hx-trigger="every 5s"
                     hx-swap="outerHTML"
                     class="text-center py-10">
                    <svg class="animate-spin h-8 w-8 mx-auto mb-3 text-sq-gold" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <p class="text-sq-gold font-semibold">AI 正在后台分析24种策略组合...</p>
                    <p class="text-gray-500 text-sm mt-1">{existing.get("progress", "计算中")} · 约需3-5分钟，请勿关闭页面</p>
                </div>
            ''')

        # Start new background task
        logger.info(f"Starting adaptive background task: {task_id}")
        asyncio.create_task(_run_adaptive_background(task_id, cache_key, start_date, end_date))

        # Return polling UI immediately
        return HTMLResponse(f'''
            <div id="adaptive-polling"
                 hx-get="/htmx/adaptive-status?task_id={task_id}&start_date={start_date}&end_date={end_date}"
                 hx-trigger="every 5s"
                 hx-swap="outerHTML"
                 class="text-center py-10">
                <svg class="animate-spin h-8 w-8 mx-auto mb-3 text-sq-gold" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="text-sq-gold font-semibold">AI 正在后台分析24种策略组合...</p>
                <p class="text-gray-500 text-sm mt-1">正在预加载市场数据... · 约需3-5分钟，请勿关闭页面</p>
            </div>
        ''')

    except Exception as e:
        logger.error(f"Adaptive backtest error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return HTMLResponse(f'<div class="text-sq-red text-center py-4">分析出错: {e}</div>')


@router.get("/htmx/adaptive-status", response_class=HTMLResponse)
async def htmx_adaptive_status(request: Request, task_id: str = "", start_date: str = "2023-01-01", end_date: str = "2026-03-01"):
    """轮询自适应分析后台任务状态"""
    task = _bg_tasks.get(task_id)

    if task is None:
        # Task not found — check cache in case it completed in a previous session
        cache_key = f"adaptive_v1:{start_date}:{end_date}"
        result = _cache_get(cache_key)
        if result and "error" not in result:
            return templates.TemplateResponse("partials/_adaptive_results.html", {
                "request": request,
                "result": result,
                "equity_curve_json": json.dumps(result.get("equity_curve", [])),
            })
        return HTMLResponse(f'''
            <div id="adaptive-polling" class="text-center py-8">
                <p class="text-gray-400 mb-3">上次分析结果因服务重启已丢失</p>
                <form hx-post="/htmx/adaptive-run"
                      hx-target="#adaptive-polling"
                      hx-swap="outerHTML"
                      hx-vals='{{"start_date":"{start_date}","end_date":"{end_date}"}}'>
                    <button type="submit"
                            class="bg-sq-gold hover:bg-yellow-500 text-black font-semibold px-6 py-2 rounded-lg transition-colors text-sm">
                        🔄 重新开始分析
                    </button>
                </form>
            </div>
        ''')

    if task["status"] == "running":
        # Still running — continue polling
        progress = task.get("progress", "计算中")
        return HTMLResponse(f'''
            <div id="adaptive-polling"
                 hx-get="/htmx/adaptive-status?task_id={task_id}&start_date={start_date}&end_date={end_date}"
                 hx-trigger="every 5s"
                 hx-swap="outerHTML"
                 class="text-center py-10">
                <svg class="animate-spin h-8 w-8 mx-auto mb-3 text-sq-gold" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p class="text-sq-gold font-semibold">AI 正在后台分析24种策略组合...</p>
                <p class="text-gray-500 text-sm mt-1">{progress} · 约需3-5分钟，请勿关闭页面</p>
            </div>
        ''')

    if task["status"] == "error":
        error_msg = task.get("progress", "未知错误")
        # Clean up task
        _bg_tasks.pop(task_id, None)
        return HTMLResponse(f'''
            <div id="adaptive-polling" class="text-center py-8">
                <div class="text-sq-red mb-3">❌ 分析失败: {error_msg}</div>
                <button hx-post="/htmx/adaptive-run"
                        hx-target="#adaptive-results"
                        hx-swap="innerHTML"
                        hx-vals='{{"start_date":"{start_date}","end_date":"{end_date}"}}'
                        class="bg-sq-gold/90 hover:bg-sq-gold text-black font-semibold px-6 py-2 rounded-lg transition-colors text-sm">
                    重试分析
                </button>
            </div>
        ''')

    # Status == "done" — load from cache and render
    _bg_tasks.pop(task_id, None)  # Clean up
    cache_key = f"adaptive_v1:{start_date}:{end_date}"
    result = _cache_get(cache_key)
    if result and "error" not in result:
        return templates.TemplateResponse("partials/_adaptive_results.html", {
            "request": request,
            "result": result,
            "equity_curve_json": json.dumps(result.get("equity_curve", [])),
        })
    return HTMLResponse('''
        <div id="adaptive-polling" class="text-center text-sq-red py-8">
            分析完成但结果读取失败，请重试
        </div>
    ''')


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

        # dry_run=True: 只计算评分，不修改DB中的仓位！
        # 之前每次生成周报都会调用_manage_positions_on_rotation()，导致仓位被覆盖
        result = await run_rotation(dry_run=True)
        if not result or "error" in result:
            return HTMLResponse('<div class="text-sq-red py-4">无法生成周报，请检查系统状态</div>')

        regime = result.get("regime", "unknown")
        selected = result.get("selected", [])
        scores_top = result.get("scores_top10", [])

        # Current positions — only ACTIVE count as held (not pending_entry)
        positions = await get_current_positions()
        active_holdings = [p.get("ticker") for p in (positions or []) if p.get("status") == "active"]

        # Compute changes vs active holdings
        added = [t for t in selected if t not in active_holdings]
        removed = [t for t in active_holdings if t not in selected]
        kept = [t for t in selected if t in active_holdings]

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

        result = await run_rotation(dry_run=True)
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
# Public API — for stockqueen.co (real-time signals + prices)
# ==================================================================

@router.get("/api/public/signals", response_class=JSONResponse)
async def api_public_signals():
    """公开API：返回当前活跃持仓 + Tiger实时行情，供 stockqueen.co 调用"""
    try:
        from app.services.rotation_service import get_current_positions, _detect_regime, RC
        from app.services.order_service import get_tiger_trade_client, calc_recommended_qty

        # 1) Market regime
        try:
            regime = await _detect_regime()
        except Exception:
            regime = "unknown"

        # 2) Active positions from DB
        all_positions = await get_current_positions() or []
        active = [p for p in all_positions if p.get("status") == "active"]

        # 2b) Account equity for position sizing (capped by config)
        account_equity = RC.POSITION_EQUITY_CAP

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
            # Fallback: Alpha Vantage for any missing tickers
            missing = [p.get("ticker") for p in active if p.get("ticker") and p["ticker"] not in tiger_prices]
            if missing:
                try:
                    from app.services.alphavantage_client import get_av_client
                    av = get_av_client()
                    av_quotes = await av.batch_get_quotes(missing)
                    for t, q in av_quotes.items():
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
            # Position quantity (from DB or recommended)
            db_qty = int(p.get("quantity", 0) or 0)
            rec_qty = calc_recommended_qty(entry_price, account_equity, RC.TOP_N) if entry_price > 0 else 0
            positions_data.append({
                "ticker": tk,
                "entry_price": round(entry_price, 2),
                "current_price": round(current_price, 2),
                "return_pct": return_pct,
                "stop_loss": round(stop_loss, 2) if stop_loss > 0 else None,
                "take_profit": round(take_profit, 2) if take_profit > 0 else None,
                "signal_date": signal_date,
                "quantity": db_qty if db_qty > 0 else rec_qty,
                "recommended_quantity": rec_qty,
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
