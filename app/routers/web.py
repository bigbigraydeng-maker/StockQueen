"""
StockQueen V2.2 - Web Dashboard Router
Server-rendered pages using Jinja2 + TailwindCSS + HTMX.
Calls service layer directly (no HTTP round-trip to API).
"""

import json
import logging
import hashlib
import time
from datetime import date
from typing import Optional, Dict, Any, Tuple
from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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

_BACKTEST_TTL = 3600 * 6     # 6 hours — backtest results change rarely
_ROTATION_TTL = 300           # 5 minutes — rotation scores refresh moderately

import os as _os
_CACHE_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), ".cache")
_os.makedirs(_CACHE_DIR, exist_ok=True)

# Keys that should be persisted to disk (survive server restart)
_PERSISTENT_PREFIXES = ("adaptive_v1:", "bt_v2:", "opt:")


def _disk_cache_path(key: str) -> str:
    """Get file path for a disk-cached key."""
    safe_key = key.replace(":", "_").replace("/", "_").replace(" ", "_")
    return _os.path.join(_CACHE_DIR, f"{safe_key}.json")


def _cache_get(key: str) -> Any:
    """Return cached value: check memory first, then disk."""
    # Memory cache
    entry = _cache.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    if entry:
        del _cache[key]

    # Disk cache fallback for persistent keys
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
    return None


def _cache_set(key: str, value: Any, ttl: int) -> None:
    """Store value in cache with TTL. Persist to disk for important keys."""
    _cache[key] = (time.time() + ttl, value)

    # Also persist to disk for expensive computations
    if any(key.startswith(p) for p in _PERSISTENT_PREFIXES):
        try:
            path = _disk_cache_path(key)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
            logger.info(f"Disk cache saved: {key}")
        except Exception as e:
            logger.warning(f"Disk cache write error for {key}: {e}")


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
        positions = await get_current_positions() or []
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

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "scores": [],       # Empty — loaded via HTMX async
        "positions": positions,
        "signals": signal_dicts,
        "risk": risk,
        "regime": None,      # Loaded with scores via HTMX
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
    """持仓列表（HTMX局部）"""
    try:
        from app.services.rotation_service import get_current_positions
        positions = await get_current_positions()
        return templates.TemplateResponse("partials/_positions.html", {
            "request": request,
            "positions": positions or [],
        })
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return HTMLResponse('<div class="text-sq-red text-center py-4">加载失败</div>')


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
    # Check if default params have cached results
    default_cache_key = "bt:2023-01-01:2026-03-01:3:1.5"
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
    """AI月度自适应最优组合分析 — Walk-Forward Optimization"""
    try:
        form = await request.form()
        start_date = form.get("start_date", "2023-01-01")
        end_date = form.get("end_date", "2026-03-01")

        # Check cache (long TTL since this is expensive)
        cache_key = f"adaptive_v1:{start_date}:{end_date}"
        result = _cache_get(cache_key)

        if result is None:
            from app.services.rotation_service import run_adaptive_backtest
            result = await run_adaptive_backtest(
                start_date=start_date,
                end_date=end_date,
            )
            if "error" not in result:
                _cache_set(cache_key, result, _BACKTEST_TTL)

        if "error" in result:
            return HTMLResponse(
                f'<div class="text-sq-red text-center py-4">'
                f'分析出错: {result["error"]}</div>'
            )

        return templates.TemplateResponse("partials/_adaptive_results.html", {
            "request": request,
            "result": result,
            "equity_curve_json": json.dumps(result.get("equity_curve", [])),
        })

    except Exception as e:
        logger.error(f"Adaptive backtest error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return HTMLResponse(f'<div class="text-sq-red text-center py-4">分析出错: {e}</div>')


# ==================== WEEKLY REPORT ====================

@router.get("/htmx/weekly-report", response_class=HTMLResponse)
async def htmx_weekly_report(request: Request):
    """生成本周调仓建议周报"""
    try:
        from app.services.rotation_service import run_rotation, get_current_positions
        from app.config.rotation_watchlist import get_ticker_info

        result = await run_rotation()
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

        if added:
            html += '<div class="space-y-2"><div class="text-xs text-sq-green font-semibold">🟢 买入</div>'
            for t in added:
                info = get_ticker_info(t)
                name = info.get("name", "") if info else ""
                html += f'<div class="flex items-center gap-2 text-sm"><span class="bg-green-900/40 text-sq-green px-2 py-0.5 rounded font-mono">{t}</span><span class="text-gray-400 text-xs">{name}</span></div>'
            html += '</div>'

        if removed:
            html += '<div class="space-y-2"><div class="text-xs text-sq-red font-semibold">🔴 卖出</div>'
            for t in removed:
                info = get_ticker_info(t)
                name = info.get("name", "") if info else ""
                html += f'<div class="flex items-center gap-2 text-sm"><span class="bg-red-900/40 text-sq-red px-2 py-0.5 rounded font-mono">{t}</span><span class="text-gray-400 text-xs">{name}</span></div>'
            html += '</div>'

        if kept:
            html += '<div class="space-y-2"><div class="text-xs text-gray-400 font-semibold">⚪ 继续持有</div><div class="flex flex-wrap gap-2">'
            for t in kept:
                html += f'<span class="bg-sq-border text-gray-300 px-2 py-0.5 rounded text-xs font-mono">{t}</span>'
            html += '</div></div>'

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

        result = await run_rotation()
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
