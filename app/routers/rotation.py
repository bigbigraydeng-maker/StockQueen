"""
StockQueen V2 - Rotation Router
API endpoints for momentum rotation strategy.
"""

import logging
import asyncio
import html
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Body, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from app.middleware.auth import require_api_key
from app.database import get_db

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
_rotation_jobs: dict[str, dict] = {}
_ROTATION_JOB_TTL = timedelta(hours=2)
_MAX_ROTATION_JOBS = 200


def _cleanup_rotation_jobs() -> None:
    """Cleanup completed/failed jobs past retention window."""
    now = datetime.now(timezone.utc)
    stale_ids: list[str] = []
    for job_id, meta in _rotation_jobs.items():
        finished_at = meta.get("finished_at")
        if finished_at and now - finished_at > _ROTATION_JOB_TTL:
            stale_ids.append(job_id)
    for job_id in stale_ids:
        _rotation_jobs.pop(job_id, None)


def _active_rotation_job_id() -> Optional[str]:
    for job_id, meta in _rotation_jobs.items():
        if meta.get("status") in {"queued", "running"}:
            return job_id
    return None


def _enforce_rotation_job_capacity() -> bool:
    """Best-effort cap on in-memory jobs to avoid unbounded growth."""
    if len(_rotation_jobs) < _MAX_ROTATION_JOBS:
        return True
    finished = [
        (job_id, meta.get("finished_at") or datetime.min.replace(tzinfo=timezone.utc))
        for job_id, meta in _rotation_jobs.items()
        if meta.get("status") in {"completed", "failed"}
    ]
    finished.sort(key=lambda x: x[1])
    for job_id, _ in finished[: max(0, len(_rotation_jobs) - _MAX_ROTATION_JOBS + 1)]:
        _rotation_jobs.pop(job_id, None)
    return len(_rotation_jobs) < _MAX_ROTATION_JOBS


def _render_rotation_polling(job_id: str, status: str, mode_label: str) -> HTMLResponse:
    poll_div = (
        f'<div id="rotation-job-{job_id}" '
        f'hx-get="/api/rotation/trigger-status?job_id={job_id}" '
        'hx-trigger="every 2s" '
        'hx-swap="outerHTML" '
        'class="rounded border border-sq-border/50 bg-sq-dark/60 p-3 text-sm text-gray-200">'
        f'⏳ 轮动任务已提交（{mode_label}），当前状态：{status}，正在后台执行...'
        "</div>"
    )
    return HTMLResponse(poll_div)


def _load_latest_manual_snapshot_result() -> Optional[dict]:
    """Cross-worker fallback: fetch latest manual rotation snapshot from DB."""
    try:
        db = get_db()
        r = (
            db.table("rotation_snapshots")
            .select("regime, selected_tickers, changes, scores, trigger_source, created_at")
            .eq("trigger_source", "manual_api")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not r.data:
            return None
        row = r.data[0]
        changes = row.get("changes") or {}
        scores = row.get("scores") or []
        return {
            "regime": row.get("regime", "unknown"),
            "selected": row.get("selected_tickers") or [],
            "added": changes.get("added") or [],
            "removed": changes.get("removed") or [],
            "scores_top10": scores[:10],
            "dry_run": False,
            "cooldown": False,
            "created_at": row.get("created_at"),
        }
    except Exception as e:
        logger.warning(f"load latest manual snapshot fallback failed: {e}")
        return None


async def _run_rotation_job(job_id: str, is_confirmed: bool) -> None:
    meta = _rotation_jobs.get(job_id)
    if not meta:
        return
    meta["status"] = "running"
    meta["started_at"] = datetime.now(timezone.utc)
    try:
        result = await run_rotation(
            trigger_source="manual_api",
            dry_run=not is_confirmed,
        )

        # Send notification only on real execution
        if is_confirmed and result.get("selected") and not result.get("dry_run"):
            await notify_rotation_summary(result)

        meta["status"] = "completed"
        meta["result"] = result
    except Exception as e:
        logger.exception(f"Rotation trigger background error: {e}")
        meta["status"] = "failed"
        meta["error"] = str(e)
    finally:
        meta["finished_at"] = datetime.now(timezone.utc)


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
    _cleanup_rotation_jobs()
    active_job_id = _active_rotation_job_id()
    if active_job_id:
        return HTMLResponse(
            f'<div class="text-amber-300 text-sm py-2">⏳ 已有轮动任务在执行中，请稍候。'
            f'<div id="rotation-job-{active_job_id}" '
            f'hx-get="/api/rotation/trigger-status?job_id={active_job_id}" '
            'hx-trigger="every 2s" hx-swap="outerHTML" class="mt-2"></div>'
            '</div>'
        )
    if not _enforce_rotation_job_capacity():
        return HTMLResponse(
            '<div class="text-sq-red text-sm py-2">❌ 当前任务队列已满，请稍后重试。</div>'
        )

    is_confirmed = confirm == "yes"
    mode_label = "正式执行" if is_confirmed else "dry-run 预演"
    job_id = uuid4().hex
    _rotation_jobs[job_id] = {
        "status": "queued",
        "is_confirmed": is_confirmed,
        "created_at": datetime.now(timezone.utc),
    }
    asyncio.create_task(_run_rotation_job(job_id=job_id, is_confirmed=is_confirmed))
    return _render_rotation_polling(job_id=job_id, status="queued", mode_label=mode_label)


@router.get("/trigger-status", response_class=HTMLResponse)
async def trigger_rotation_status(
    request: Request,
    job_id: str = Query(...),
    _key: str = Depends(require_api_key),
):
    """Poll status for a background manual rotation task."""
    _cleanup_rotation_jobs()
    meta = _rotation_jobs.get(job_id)
    if not meta:
        fallback_result = _load_latest_manual_snapshot_result()
        if fallback_result:
            return templates.TemplateResponse(request, "partials/_rotation_exec_result.html", {
                "request": request,
                "regime": fallback_result.get("regime", "unknown"),
                "selected": fallback_result.get("selected", []),
                "added": fallback_result.get("added", []),
                "removed": fallback_result.get("removed", []),
                "scores_top10": fallback_result.get("scores_top10", []),
                "dry_run": fallback_result.get("dry_run", False),
                "cooldown": fallback_result.get("cooldown", False),
            })

        return HTMLResponse(
            f'<div id="rotation-job-{job_id}" '
            f'hx-get="/api/rotation/trigger-status?job_id={job_id}" '
            'hx-trigger="every 3s" '
            'hx-swap="outerHTML" '
            'class="rounded border border-sq-border/50 bg-sq-dark/60 p-3 text-sm text-amber-300">'
            '⏳ 任务在其他实例执行中，正在等待最新轮动结果同步...'
            '</div>'
        )

    status = meta.get("status", "unknown")
    mode_label = "正式执行" if meta.get("is_confirmed") else "dry-run 预演"
    if status in {"queued", "running"}:
        return _render_rotation_polling(job_id=job_id, status=status, mode_label=mode_label)

    if status == "failed":
        err = html.escape(meta.get("error", "unknown error"))
        return HTMLResponse(
            f'<div class="text-sq-red text-sm py-2">❌ 轮动执行失败: {err}</div>'
        )

    result = meta.get("result") or {}
    return templates.TemplateResponse(request, "partials/_rotation_exec_result.html", {
        "request": request,
        "regime": result.get("regime", "unknown"),
        "selected": result.get("selected", []),
        "added": result.get("added", []),
        "removed": result.get("removed", []),
        "scores_top10": result.get("scores_top10", []),
        "dry_run": result.get("dry_run", False),
        "cooldown": result.get("cooldown", False),
    })


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

        return templates.TemplateResponse(request, "partials/_daily_check_result.html", {
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
