"""
StockQueen V2 - Rotation Router
API endpoints for momentum rotation strategy.
"""

import logging
from fastapi import APIRouter, Body, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from app.middleware.auth import require_api_key

from app.services.rotation_service import (
    run_rotation,
    run_daily_entry_check,
    run_daily_exit_check,
    run_rotation_backtest,
    run_ml_retrain,
    read_cached_scores,
    get_current_positions,
    get_rotation_history,
)
from app.services.notification_service import (
    notify_rotation_summary,
    notify_rotation_entry,
    notify_rotation_exit,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/trigger", response_class=HTMLResponse)
async def trigger_rotation(
    request: Request,
    confirm: Optional[str] = Form(None),
    _key: str = Depends(require_api_key),
):
    """Manually trigger rotation scoring.

    Two-step safety:
    1. First call (no confirm): dry_run — shows what WOULD change, no orders placed.
    2. Second call (confirm="yes"): executes for real, places Tiger orders.
    """
    try:
        is_confirmed = confirm == "yes"
        result = await run_rotation(
            trigger_source="manual_api",
            dry_run=not is_confirmed,
        )

        # Send notification only on real execution
        if is_confirmed and result.get("selected") and not result.get("dry_run"):
            await notify_rotation_summary(result)

        return templates.TemplateResponse("partials/_rotation_exec_result.html", {
            "request": request,
            "regime": result.get("regime", "unknown"),
            "selected": result.get("selected", []),
            "added": result.get("added", []),
            "removed": result.get("removed", []),
            "scores_top10": result.get("scores_top10", []),
            "dry_run": result.get("dry_run", False),
            "cooldown": result.get("cooldown", False),
        })
    except Exception as e:
        logger.error(f"Rotation trigger error: {e}")
        return HTMLResponse(
            f'<div class="text-sq-red text-sm py-2">❌ 轮动执行失败: {e}</div>'
        )


@router.post("/trigger-daily", response_class=HTMLResponse)
async def trigger_daily_check(request: Request, check_type: Optional[str] = Form(None), _key: str = Depends(require_api_key)):
    """Manually trigger daily entry + exit checks.

    Args:
        check_type: Optional filter - "entry" for entry only, "exit" for exit only,
                    None/other for both.
    """
    try:
        entry_signals = []
        exit_signals = []

        if check_type != "exit":
            entry_signals = await run_daily_entry_check()
            for sig in entry_signals:
                await notify_rotation_entry(sig)

        if check_type != "entry":
            exit_signals = await run_daily_exit_check()
            for sig in exit_signals:
                await notify_rotation_exit(sig)

        return templates.TemplateResponse("partials/_daily_check_result.html", {
            "request": request,
            "check_type": check_type or "both",
            "entry_signals": [s.model_dump() for s in entry_signals],
            "exit_signals": [s.model_dump() for s in exit_signals],
        })
    except Exception as e:
        logger.error(f"Daily check error: {e}")
        return HTMLResponse(
            f'<div class="text-sq-red text-sm py-2">❌ 日检执行失败: {e}</div>'
        )



@router.get("/scores")
async def get_scores():
    """Get pre-computed rotation scores (from scheduler, not live)."""
    result = read_cached_scores()
    return {"success": True, "data": result}


@router.get("/positions")
async def get_positions():
    """Get current rotation positions."""
    positions = await get_current_positions()
    return {
        "success": True,
        "count": len(positions),
        "positions": positions,
    }


@router.get("/history")
async def get_history(limit: int = Query(10, ge=1, le=52)):
    """Get recent rotation snapshots."""
    history = await get_rotation_history(limit=limit)
    return {
        "success": True,
        "count": len(history),
        "snapshots": history,
    }



@router.post("/ml/retrain")
async def trigger_ml_retrain(
    months_lookback: int = Query(18, ge=6, le=36, description="训练窗口（月）"),
    _key: str = Depends(require_api_key),
):
    """
    手动触发 ML-V3A 月度重训。
    - 拉取最近 months_lookback 个月数据
    - 非对称 z-score 标签重训 XGBRanker
    - 保存并热更新生产模型
    - 预计耗时 10-20 分钟
    """
    import asyncio
    async def _bg():
        await run_ml_retrain(months_lookback=months_lookback)
    asyncio.create_task(_bg())
    return {
        "success": True,
        "message": f"ML 重训已在后台启动（训练窗口 {months_lookback} 个月），完成后 Feishu 通知",
    }


@router.post("/backtest")
async def trigger_backtest(
    start: str = Query("2023-04-01", description="Start date YYYY-MM-DD"),
    end: str = Query("2026-03-01", description="End date YYYY-MM-DD"),
    top_n: int = Query(3, ge=1, le=10),
):
    """Run historical rotation backtest."""
    result = await run_rotation_backtest(
        start_date=start, end_date=end, top_n=top_n
    )
    return {"success": True, "data": result}
