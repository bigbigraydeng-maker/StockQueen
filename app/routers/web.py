"""
StockQueen V2.2 - Web Dashboard Router
Server-rendered pages using Jinja2 + TailwindCSS + HTMX.
Calls service layer directly (no HTTP round-trip to API).
"""

import logging
from typing import Optional
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


# ==================== FULL PAGE ROUTES ====================

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """仪表盘 — 评分表 + 持仓 + 信号 + 风险"""
    try:
        from app.services.rotation_service import (
            get_current_scores,
            get_current_positions,
        )
        from app.services.db_service import SignalService
        from app.services.risk_service import RiskEngine

        # Fetch all data
        scores_result = await get_current_scores()
        positions = await get_current_positions()

        # Extract scores list and regime from result
        scores = []
        regime = None
        if isinstance(scores_result, dict):
            scores = scores_result.get("scores", [])
            regime = scores_result.get("regime")
        elif isinstance(scores_result, list):
            scores = scores_result

        # Convert RotationScore objects to dicts if needed
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

        # Sort by score descending by default
        score_dicts.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Get signals
        try:
            signals = await SignalService.get_observe_signals()
            signal_dicts = []
            for sig in (signals or []):
                if hasattr(sig, "model_dump"):
                    signal_dicts.append(sig.model_dump())
                elif hasattr(sig, "dict"):
                    signal_dicts.append(sig.dict())
                elif isinstance(sig, dict):
                    signal_dicts.append(sig)
                else:
                    signal_dicts.append(vars(sig))
        except Exception:
            signal_dicts = []

        # Get risk summary
        try:
            risk = await RiskEngine().get_current_risk_summary()
        except Exception:
            risk = {"status": "normal", "max_drawdown_pct": 0}

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "scores": score_dicts,
            "positions": positions or [],
            "signals": signal_dicts,
            "risk": risk,
            "regime": regime,
        })

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "scores": [],
            "positions": [],
            "signals": [],
            "risk": {},
            "regime": None,
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
    """可排序轮动评分表（HTMX局部）"""
    try:
        from app.services.rotation_service import get_current_scores

        scores_result = await get_current_scores()
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
