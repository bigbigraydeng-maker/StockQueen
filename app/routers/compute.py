"""
StockQueen 破浪 - 算力工作站 Router

GET  /admin/compute                          → 主页面
POST /admin/compute/trigger/{job_id}         → 触发 GitHub Actions，HTMX fragment
GET  /admin/compute/runs                     → 最近运行列表，HTMX 轮询 fragment
GET  /admin/compute/run/{run_id}             → 单个运行状态 badge，HTMX 细粒度轮询
GET  /admin/compute/run/{run_id}/results     → 结果展示（下载 artifact JSON 并解析）
GET  /admin/compute/run/{run_id}/obsidian-md → 生成 Obsidian Markdown（供前端 JS 推送）
"""

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
    from app.config.settings import settings

    runs = await list_recent_runs(limit=30)
    # 以 (workflow_file, strategy) 为 key，精确判断哪个任务正在跑
    active_workflows = {
        (r["workflow_file"], r["inputs"].get("strategy", ""))
        for r in runs
        if r["status"] in ("in_progress", "queued")
    }
    return templates.TemplateResponse(request, "compute.html", {
        "request":          request,
        "is_guest":         False,
        "jobs":             COMPUTE_JOBS,
        "runs":             runs,
        "active_workflows": active_workflows,
        "obsidian_key":     settings.obsidian_vault_key or "",
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
    return templates.TemplateResponse(request, "partials/_compute_runs.html", {
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
    return templates.TemplateResponse(request, "partials/_compute_run_badge.html", {
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
    from app.config.settings import settings

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

    return templates.TemplateResponse(request, "partials/_compute_result.html", {
        "request":       request,
        "data":          data,
        "artifact_name": artifact["name"],
        "run_id":        run_id,
        "obsidian_key":  settings.obsidian_vault_key or "",
    })


# ──────────────────────────────────────────────────────────────────────────────
# 生成 Obsidian Markdown（供前端 JS 直接 PUT 到本地 Obsidian REST API）
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/admin/compute/run/{run_id}/obsidian-md")
async def run_obsidian_md(
    run_id: int,
    request: Request,
    _auth=Depends(require_admin),
):
    from app.services.github_actions_service import get_run_artifacts, download_artifact_json, list_recent_runs

    runs = await list_recent_runs(limit=50)
    run = next((r for r in runs if r["id"] == run_id), None)

    artifacts = await get_run_artifacts(run_id)
    if not artifacts:
        return JSONResponse({"error": "暂无结果文件"}, status_code=404)

    artifact = artifacts[0]
    data = await download_artifact_json(artifact["id"])
    if not data:
        return JSONResponse({"error": "无法解析 artifact"}, status_code=500)

    md, vault_path = _make_obsidian_md(run_id, run, artifact["name"], data)
    return JSONResponse({"markdown": md, "path": vault_path})


# ──────────────────────────────────────────────────────────────────────────────
# 内部：生成 Obsidian Markdown 内容
# ──────────────────────────────────────────────────────────────────────────────

_STRATEGY_LABELS = {
    "v4": "宝典V4", "mr": "均值回归MR", "ed": "事件驱动ED", "all": "全策略"
}


def _make_obsidian_md(run_id: int, run: dict | None, artifact_name: str, data: dict) -> tuple[str, str]:
    """
    根据 artifact JSON 生成 Obsidian Markdown。
    返回 (markdown_content, vault_relative_path)
    """
    # ── Regime Sharpe 格式 ──────────────────────────────────────────
    if data.get("alpha_verdict") or "regime" in (artifact_name or "").lower():
        return _make_regime_sharpe_md(run_id, run, data)

    meta            = data.get("meta", {})
    window_results  = data.get("window_results", [])
    summary         = data.get("summary", {})
    results         = data.get("results", {})   # sensitivity format

    run_inputs   = (run.get("inputs") or {}) if run else {}
    strategy_raw = meta.get("strategy") or run_inputs.get("strategy") or ""
    slabel       = _STRATEGY_LABELS.get(strategy_raw, strategy_raw or "未知")
    run_date     = ((run.get("created_at") or "")[:10] if run else "") or "unknown"
    html_url     = (run.get("html_url") or "") if run else \
                   f"https://github.com/bigbigraydeng-maker/StockQueen/actions/runs/{run_id}"

    duration_s  = (run.get("duration_s") or 0) if run else 0
    if duration_s >= 3600:
        duration_str = f"{duration_s/3600:.1f}h"
    elif duration_s >= 60:
        duration_str = f"{duration_s//60}m{duration_s%60}s"
    elif duration_s > 0:
        duration_str = f"{duration_s}s"
    else:
        duration_str = "--"

    is_wf          = bool(window_results)
    is_sensitivity = bool(results) and not is_wf
    test_type      = "Walk-Forward验证" if is_wf else ("敏感性测试" if is_sensitivity else "验证")

    filename   = f"{'wf' if is_wf else 'sensitivity'}-{strategy_raw}-{run_date}-run{run_id}.md"
    vault_path = f"docs/Walk-Forward/Results/{filename}"

    run_strategies = meta.get("run_strategies") or \
                     (list(summary.keys()) if is_wf else list(results.keys()))
    tags = ["walkforward" if is_wf else "sensitivity"] + run_strategies + ["github-actions"]

    L = []  # lines

    # ── Frontmatter ──
    L += [
        "---",
        f"name: {test_type} - {slabel} ({run_date})",
        f"run_id: {run_id}",
        f"date: {run_date}",
        f"tags: [{', '.join(tags)}]",
        "---",
        "",
        f"# {test_type}结果 — {slabel}",
        "",
        "## 测试环境",
        "",
        "| 项目 | 详情 |",
        "|------|------|",
        "| 平台 | GitHub Actions（ubuntu-24.04）|",
        "| Python | 3.11 |",
        f"| 运行编号 | [{run_id}]({html_url}) |",
        f"| 日期 | {run_date} |",
        f"| 耗时 | {duration_str} |",
        "| 数据来源 | AV cache（GitHub Release `av-cache-latest`）|",
        "| 股票池 | 静态 502 只（⚠️ 含幸存者偏差，待 Phase 2 修复）|",
        "",
    ]

    # ── Walk-Forward 内容 ──
    if is_wf:
        for skey in run_strategies:
            s       = summary.get(skey, {})
            avg     = s.get("avg_oos_sharpe")
            verdict = s.get("verdict", "--")
            stable  = s.get("param_stability", "")
            oos_list = s.get("oos_sharpes_per_window", [])
            slab    = _STRATEGY_LABELS.get(skey, skey)

            avg_str = f"{avg:.3f}" if avg is not None else "--"
            stable_str = f" | {stable}" if stable else ""
            L += [
                f"## {slab} — {verdict}",
                "",
                f"**平均 OOS Sharpe：{avg_str}**{stable_str}",
                "",
                "| 窗口 | 测试期 | IS Sharpe | OOS Sharpe | 最优参数 |",
                "|------|--------|-----------|-----------|---------|",
            ]
            for wr in window_results:
                sd   = wr.get("strategies", {}).get(skey, {})
                if "error" in sd:
                    L.append(f"| {wr['window']} | {wr.get('test_period','')} | ❌ | ❌ | {sd['error'][:40]} |")
                    continue
                oos  = sd.get("oos_sharpe")
                is_s = sd.get("is_sharpe")
                bp   = sd.get("best_param", {})
                param_str = " ".join(f"{k}={v}" for k, v in bp.items())
                oos_emoji = ("✅" if oos is not None and oos >= 1.0 else
                             "⚠️" if oos is not None and oos >= 0  else "❌")
                is_fmt  = f"{is_s:.2f}" if is_s is not None else "--"
                oos_fmt = f"{oos:.2f}" if oos is not None else "--"
                L.append(
                    f"| {wr['window']} | {wr.get('test_period','')} | "
                    f"{is_fmt} | {oos_emoji} {oos_fmt} | `{param_str}` |"
                )
            L.append("")

    # ── Sensitivity 内容 ──
    elif is_sensitivity:
        period = ""
        if meta.get("start_date"):
            period = f"{meta['start_date'][:7]} ~ {(meta.get('end_date') or '')[:7]}"

        for skey, params in results.items():
            slab = _STRATEGY_LABELS.get(skey, skey)
            L += [
                f"## {slab} 敏感性分析" + (f"（{period}）" if period else ""),
                "",
            ]
            for param_name, rows in params.items():
                if not rows:
                    continue
                best_sharpe = max(r["sharpe_ratio"] for r in rows)
                L += [
                    f"### `{param_name}`",
                    "",
                    "| 参数值 | Sharpe | 累计收益 | 最大回撤 | 胜率 | 交易数 |",
                    "|--------|--------|---------|---------|------|--------|",
                ]
                for row in rows:
                    star = " ★" if row["sharpe_ratio"] == best_sharpe else ""
                    L.append(
                        f"| `{row['param_value']}{star}` | {row['sharpe_ratio']:.3f} | "
                        f"{row['cumulative_return']*100:.1f}% | {row['max_drawdown']*100:.1f}% | "
                        f"{row['win_rate']*100:.1f}% | {row['total_trades']} |"
                    )
                L.append("")

    # ── 尾部链接 ──
    L += [
        "---",
        "",
        "→ [[Walk-Forward/03-V4-Final-Results]]",
        f"→ [GitHub Actions 完整日志]({html_url})",
    ]

    return "\n".join(L), vault_path


def _make_regime_sharpe_md(run_id: int, run: dict | None, data: dict) -> tuple[str, str]:
    """生成 Regime Sharpe 分析的 Obsidian Markdown。"""
    summary   = data.get("summary", {})
    records   = data.get("records", [])
    verdict   = data.get("alpha_verdict", "insufficient_data")
    ratio     = data.get("bull_bear_ratio")
    ts        = data.get("analysis_timestamp", "")[:10]
    source    = data.get("source_file", "")

    run_date  = ts or ((run.get("created_at") or "")[:10] if run else "unknown")
    html_url  = (run.get("html_url") or "") if run else \
                f"https://github.com/bigbigraydeng-maker/StockQueen/actions/runs/{run_id}"

    filename   = f"regime-sharpe-{run_date}-run{run_id}.md"
    vault_path = f"04-StockQueen/Research/Regime-Analysis/{filename}"

    verdict_map = {
        "regime_dependent":     "⚠️ 高度 Regime 依赖 — 主要吃牛市 Beta",
        "moderate_regime_bias": "🔶 中度 Regime 依赖 — 有 Alpha，牛市加成",
        "robust_alpha":         "✅ 策略稳健 — 真实 Alpha",
        "insufficient_data":    "❓ 数据不足",
    }

    L = [
        "---",
        f"name: Regime Sharpe 分析 ({run_date})",
        f"run_id: {run_id}",
        f"date: {run_date}",
        f"alpha_verdict: {verdict}",
        "tags: [regime-sharpe, walkforward, alpha-analysis]",
        "---",
        "",
        "# Regime 分段 Sharpe 分析",
        "",
        "## 核心结论",
        "",
        f"**Alpha 判断：{verdict_map.get(verdict, verdict)}**",
        f"牛/熊 Sharpe 比：**{ratio}x**" if ratio else "",
        "",
        "## 宝典V4 各 Regime 表现",
        "",
        "| Regime | 覆盖窗口 | 均值 OOS Sharpe | 最低 | 最高 | 均值回报 |",
        "|--------|---------|----------------|------|------|---------|",
    ]

    for regime, label in [("bull", "🐂 牛市"), ("bear", "🐻 熊市"), ("bear_recovery", "⚡ 熊转牛")]:
        s = summary.get(f"v4_{regime}", {})
        if s:
            ret = f"{s['avg_oos_return']:+.1%}" if s.get("avg_oos_return") is not None else "N/A"
            L.append(
                f"| {label} | {s.get('windows', [])} | "
                f"{s.get('avg_oos_sharpe', 'N/A'):+.3f} | "
                f"{s.get('min_oos_sharpe', 'N/A'):+.3f} | "
                f"{s.get('max_oos_sharpe', 'N/A'):+.3f} | {ret} |"
            )

    L += [
        "",
        "## 全策略 × Regime 汇总",
        "",
        "| 策略 | Regime | 窗口数 | 均值Sharpe | 均值回报 |",
        "|------|--------|--------|-----------|---------|",
    ]
    for key, s in sorted(summary.items()):
        ret = f"{s['avg_oos_return']:+.1%}" if s.get("avg_oos_return") is not None else "N/A"
        strat_label = {"v4": "宝典V4", "mr": "MR", "ed": "ED", "portfolio": "组合"}.get(s["strategy"], s["strategy"])
        L.append(
            f"| {strat_label} | {s['regime']} | {s['n_windows']} | "
            f"{s.get('avg_oos_sharpe', 'N/A'):+.3f} | {ret} |"
        )

    L += [
        "",
        "## 数据来源",
        "",
        f"- 源文件：`{source}`",
        f"- GHA Run：[{run_id}]({html_url})",
        f"- 分析时间：{ts}",
        "",
        "---",
        "",
        "→ [[Walk-Forward/Results/]] · [[Strategy/01-Current-Strategy-Overview]]",
    ]

    return "\n".join(L), vault_path
