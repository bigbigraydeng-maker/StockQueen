"""
只读健康检查：板块快照 sector_snapshots + 定时任务 weekly_rotation（Supabase）

无法代你登录 Render/Supabase 网页；请在项目根目录配置 .env 后本地执行：

  python scripts/check_sector_rotation_health.py

依赖：SUPABASE_URL、SUPABASE_SERVICE_KEY（与 app 相同）
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

SB_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY") or ""


def sb_get(table: str, query: str) -> list:
    if not SB_URL or not SB_KEY:
        print("缺少环境变量：SUPABASE_URL 或 SUPABASE_SERVICE_KEY（请检查 .env）")
        sys.exit(1)
    url = f"{SB_URL}/rest/v1/{table}?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": SB_KEY,
            "Authorization": f"Bearer {SB_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        print(f"HTTP {e.code} {table}: {body}")
        return []


def main() -> None:
    print("=== sector_snapshots：全表最新 snapshot_date（按日期降序 1 条）===")
    rows = sb_get(
        "sector_snapshots",
        "select=snapshot_date&order=snapshot_date.desc&limit=1",
    )
    if rows:
        print(f"  最新日期: {rows[0].get('snapshot_date')}")
    else:
        print("  （无数据或查询失败）")

    print("\n=== sector_snapshots：technology 板块最近 5 条 ===")
    tech = sb_get(
        "sector_snapshots",
        "sector=eq.technology&select=snapshot_date,avg_score,stock_count,regime&order=snapshot_date.desc&limit=5",
    )
    for r in tech:
        print(
            f"  {r.get('snapshot_date')}  score={r.get('avg_score')}  "
            f"n={r.get('stock_count')}  regime={r.get('regime')}"
        )
    if not tech:
        print("  （无数据）")

    print("\n=== scheduler_runs：weekly_rotation 最近 15 条 ===")
    runs = sb_get(
        "scheduler_runs",
        "job_id=eq.weekly_rotation&select=started_at,finished_at,status,duration_sec,summary,error&order=started_at.desc&limit=15",
    )
    for r in runs:
        err = r.get("error")
        err_s = (err[:120] + "…") if err and len(err) > 120 else err
        print(
            f"  {r.get('started_at')}  status={r.get('status')}  "
            f"dur={r.get('duration_sec')}s  err={err_s!r}"
        )
    if not runs:
        print("  （无记录：可能 Worker 未跑过或表为空）")

    print("\n=== scheduler_runs：任意任务最近 5 条（验证表是否有数据）===")
    any_runs = sb_get(
        "scheduler_runs",
        "select=job_id,started_at,status&order=started_at.desc&limit=5",
    )
    for r in any_runs:
        print(f"  {r.get('job_id')}  {r.get('started_at')}  {r.get('status')}")

    print("\n=== rotation_snapshots：最近 12 条 ===")
    snaps = sb_get(
        "rotation_snapshots",
        "select=snapshot_date,regime,trigger_source,created_at&order=created_at.desc&limit=12",
    )
    for r in snaps:
        print(
            f"  {r.get('snapshot_date')}  regime={r.get('regime')}  "
            f"src={r.get('trigger_source')}  at={r.get('created_at')}"
        )

    print("\n--- 说明 ---")
    print("若 sector 最新日 < 当前美股最后交易日，且 weekly_rotation 无 success：")
    print("  请打开 Render → stockqueen-scheduler → Logs，查周六 NZT 前后报错。")
    print(f"检查时间 (UTC): {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
