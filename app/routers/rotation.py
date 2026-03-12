"""
StockQueen V2 - Rotation Router
API endpoints for momentum rotation strategy.
"""

import logging
from fastapi import APIRouter, Query

from app.services.rotation_service import (
    run_rotation,
    run_daily_entry_check,
    run_daily_exit_check,
    run_rotation_backtest,
    get_current_scores,
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


@router.post("/trigger")
async def trigger_rotation():
    """Manually trigger weekly rotation scoring."""
    result = await run_rotation()

    # Send notification
    if result.get("selected"):
        await notify_rotation_summary(result)

    return {"success": True, "data": result}


@router.post("/trigger-daily")
async def trigger_daily_check():
    """Manually trigger daily entry + exit checks."""
    entry_signals = await run_daily_entry_check()
    exit_signals = await run_daily_exit_check()

    # Send notifications
    for sig in entry_signals:
        await notify_rotation_entry(sig)
    for sig in exit_signals:
        await notify_rotation_exit(sig)

    return {
        "success": True,
        "entry_signals": [s.model_dump() for s in entry_signals],
        "exit_signals": [s.model_dump() for s in exit_signals],
    }


@router.get("/scores")
async def get_scores():
    """Get current rotation scores for all tickers."""
    result = await get_current_scores()
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


@router.post("/backtest")
async def trigger_backtest(
    start: str = Query("2024-01-01", description="Start date YYYY-MM-DD"),
    end: str = Query("2026-03-01", description="End date YYYY-MM-DD"),
    top_n: int = Query(3, ge=1, le=10),
):
    """Run historical rotation backtest."""
    result = await run_rotation_backtest(
        start_date=start, end_date=end, top_n=top_n
    )
    return {"success": True, "data": result}
