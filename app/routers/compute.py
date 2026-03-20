"""
StockQueen 破浪 - 算力工作站 Router

GET  /admin/compute                  → 主页面
POST /admin/compute/trigger/{job_id} → 触发 GitHub Actions，HTMX fragment
GET  /admin/compute/runs             → 最近运行列表，HTMX 轮询 fragment
GET  /admin/compute/run/{run_id}     → 单个运行状态 badge，HTMX 细粒度轮询
"""

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.middleware.auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=["compute"])
templates = Jinja2Templates(directory="app/templates")


# ──────────────────────────────────────────────────────────────────────────────
# 主页面
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/admin/compute", response_class=HTMLResponse)
async def compute_page(
    request: Request,
    _auth=Depends(require_admin),
):
    from app.services.github_actions_service import COMPUTE_JOBS, list_recent_runs
    runs = await list_recent_runs(limit=20)
    active_workflows = {
        r["workflow_file"] for r in runs
        if r["status"] in ("in_progress", "queued")
    }
    return templates.TemplateResponse("compute.html", {
        "request":          request,
        "is_guest":         False,
        "jobs":             COMPUTE_JOBS,
        "runs":             runs,
        "active_workflows": active_workflows,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 触发任务
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/admin/compute/trigger/{job_id}", response_class=HTMLResponse)
async def trigger_job(
    job_id: str,
    request: Request,
    _auth=Depends(require_admin),
):
    from app.services.github_actions_service import COMPUTE_JOBS, trigger_workflow

    job = next((j for j in COMPUTE_JOBS if j["id"] == job_id), None)
    if not job:
        return HTMLResponse('<span class="text-red-400 text-xs">任务不存在</span>', status_code=404)
    if not job.get("ready"):
        return HTMLResponse('<span class="text-yellow-400 text-xs">⚠️ 未就绪，请先完成前置条件</span>', status_code=400)

    result = await trigger_workflow(job["workflow"], job["inputs"])

    if result.get("ok"):
        html = (
            '<span class="inline-flex items-center gap-1 px-2 py-1 rounded text-xs '
            'bg-green-900/30 text-green-400 border border-green-700/30">'
            '✓ 已触发 — 约30秒后可在运行记录中看到</span>'
        )
    else:
        err = result.get("error", "未知错误")
        html = (
            f'<span class="inline-flex items-center gap-1 px-2 py-1 rounded text-xs '
            f'bg-red-900/30 text-red-400 border border-red-700/30">'
            f'触发失败: {err}</span>'
        )
    return HTMLResponse(html)


# ──────────────────────────────────────────────────────────────────────────────
# 最近运行列表（30s 轮询）
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/admin/compute/runs", response_class=HTMLResponse)
async def compute_runs(
    request: Request,
    _auth=Depends(require_admin),
):
    from app.services.github_actions_service import list_recent_runs
    try:
        runs = await list_recent_runs(limit=20)
    except Exception as e:
        logger.error(f"compute_runs error: {e}")
        runs = []
    return templates.TemplateResponse("partials/_compute_runs.html", {
        "request": request,
        "runs":    runs,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 单个运行状态 badge（in_progress 时每 10s 细粒度轮询）
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/admin/compute/run/{run_id}", response_class=HTMLResponse)
async def compute_run_badge(
    run_id: int,
    request: Request,
    _auth=Depends(require_admin),
):
    from app.services.github_actions_service import get_run_status
    run = await get_run_status(run_id)
    if not run:
        return HTMLResponse('<span class="text-gray-500 text-xs">--</span>')
    return templates.TemplateResponse("partials/_compute_run_badge.html", {
        "request": request,
        "run":     run,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 结果展示（下载 artifact JSON 并解析）
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/admin/compute/run/{run_id}/results", response_class=HTMLResponse)
async def run_results(
    run_id: int,
    request: Request,
    _auth=Depends(require_admin),
):
    from app.services.github_actions_service import get_run_artifacts, download_artifact_json

    artifacts = await get_run_artifacts(run_id)
    if not artifacts:
        return HTMLResponse('<p class="text-gray-500 text-sm p-4 text-center">暂无结果文件</p>')

    artifact = artifacts[0]
    data = await download_artifact_json(artifact["id"])
    if not data:
        return HTMLResponse(
            f'<p class="text-gray-500 text-sm p-4 text-center">'
            f'无法解析结果 — <a href="https://github.com/bigbigraydeng-maker/StockQueen/actions/runs/{run_id}" '
            f'target="_blank" class="text-sq-accent underline">在 GitHub 查看</a></p>'
        )

    return templates.TemplateResponse("partials/_compute_result.html", {
        "request":       request,
        "data":          data,
        "artifact_name": artifact["name"],
        "run_id":        run_id,
    })
