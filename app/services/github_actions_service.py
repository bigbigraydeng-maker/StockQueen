"""
StockQueen 破浪 - GitHub Actions 服务
触发和查询 GitHub Actions 工作流（Walk-Forward 回测等算力任务）
"""

import logging
import os
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OWNER = "bigbigraydeng-maker"
_REPO  = "StockQueen"

# ============================================================
# 算力任务注册表
# ============================================================

COMPUTE_JOBS = [
    # ── 🔴 P1：影响生产决策，必须完成 ─────────────────────────────────
    {
        "id": "wf_v4_hb",
        "priority": "🔴",
        "name": "宝典V4 HB 二维验证（top_n=3 × HB=[0,0.5,1.0]）",
        "est": "~6小时",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "v4"},
        "prereq": "需先修改 walk_forward_v5_full.py 加入 HB=[0, 0.5, 1.0] 搜索维度",
        "ready": False,
    },
    {
        "id": "wf_ed_wf",
        "priority": "🔴",
        "name": "ED Walk-Forward 修复重跑（regime_series bug 修复后）",
        "est": "~2小时",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "ed"},
        "prereq": "需先修复 event_driven_service.py regime_series 传参 Bug（当前 WF 结果 MARGINAL 可能因 Bug 失真）",
        "ready": False,
    },
    # ── 🟡 P2：验证稳健性，可并行跑 ──────────────────────────────────
    {
        "id": "wf_mr_sensitivity",
        "priority": "🟡",
        "name": "MR 敏感性测试（RSI 阈值 ± 稳健性）",
        "est": "~30分钟",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "mr"},
        "prereq": None,
        "ready": True,
    },
    {
        "id": "wf_ed_sensitivity",
        "priority": "🟡",
        "name": "ED 敏感性测试（当前参数，regime_series 修复前的基线）",
        "est": "~30分钟",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "ed"},
        "prereq": None,
        "ready": True,
    },
    {
        "id": "wf_allocation_revalidate",
        "priority": "🟡",
        "name": "ALLOCATION_MATRIX 重验证（ED WF 修复后，重新确认分配比例）",
        "est": "~1小时",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "all"},
        "prereq": "依赖 wf_ed_wf 完成 —— ED WF 结果若改善，V5.1 分配比例需重新评估",
        "ready": False,
    },
    # ── 🟢 P3：方法论修复 ─────────────────────────────────────────────
    {
        "id": "wf_monte_carlo",
        "priority": "🟢",
        "name": "Monte Carlo 修复重跑（MR + ED，随机入场日期方法论）",
        "est": "~1小时",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "all"},
        "prereq": "需先修复 monte_carlo_test.py 方法论（随机入场日期 vs 随机 PnL 顺序）",
        "ready": False,
    },
    # ── 🔵 P4：Phase 2，需基础设施支撑 ───────────────────────────────
    {
        "id": "wf_dynamic_universe",
        "priority": "🔵",
        "name": "动态选股池 WF（全市场 ~1578只，超 GitHub 6h 上限需 Modal）",
        "est": "~10小时",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "v4"},
        "prereq": "需 Universe Scheduler 上线 + 迁移至 Modal.com",
        "ready": False,
    },
    {
        "id": "wf_survivor_bias",
        "priority": "🔵",
        "name": "幸存者偏差修复 WF（含退市股历史，需 Modal）",
        "est": "~12小时",
        "workflow": "walk-forward.yml",
        "inputs": {"strategy": "v4"},
        "prereq": "需 FMP 历史退市数据迁移完成 + Modal.com",
        "ready": False,
    },
]


# ============================================================
# GitHub API 辅助
# ============================================================

def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _base() -> str:
    return f"https://api.github.com/repos/{_OWNER}/{_REPO}"


# ============================================================
# 公开接口
# ============================================================

async def trigger_workflow(workflow_file: str, inputs: dict) -> dict:
    """触发 GitHub Actions workflow_dispatch。返回 {"ok": True} 或 {"ok": False, "error": ...}"""
    url = f"{_base()}/actions/workflows/{workflow_file}/dispatches"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json={"ref": "main", "inputs": inputs}, headers=_headers())
        if resp.status_code == 204:
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        logger.error(f"[GH] trigger_workflow error: {e}")
        return {"ok": False, "error": str(e)}


async def list_recent_runs(limit: int = 20) -> list:
    """获取最近 N 条 workflow runs，返回格式化列表。"""
    url = f"{_base()}/actions/runs"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params={"per_page": limit}, headers=_headers())
            resp.raise_for_status()
        return [_fmt(r) for r in resp.json().get("workflow_runs", [])]
    except Exception as e:
        logger.error(f"[GH] list_recent_runs error: {e}")
        return []


async def get_run_status(run_id: int) -> Optional[dict]:
    """获取单个 run 状态。"""
    url = f"{_base()}/actions/runs/{run_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
        return _fmt(resp.json())
    except Exception as e:
        logger.error(f"[GH] get_run_status({run_id}) error: {e}")
        return None


# ============================================================
# 内部格式化
# ============================================================

def _fmt(run: dict) -> dict:
    """将 GitHub API run 对象精简为模板所需字段。"""
    created = run.get("created_at", "")
    updated = run.get("updated_at", "")
    duration = None
    if created and updated:
        try:
            t0 = datetime.fromisoformat(created.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            duration = int((t1 - t0).total_seconds())
        except Exception:
            pass

    status     = run.get("status", "unknown")
    conclusion = run.get("conclusion")
    display    = conclusion if status == "completed" else status

    return {
        "id":           run.get("id"),
        "name":         run.get("name", ""),
        "status":       status,
        "conclusion":   conclusion,
        "display":      display,   # success / failure / cancelled / in_progress / queued
        "created_at":   created,
        "duration_s":   duration,
        "html_url":     run.get("html_url", ""),
        "head_branch":  run.get("head_branch", "main"),
    }
