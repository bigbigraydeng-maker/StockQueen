"""
查 Supabase scheduler_runs 表，确认 Render 端铃铛任务是否在执行
"""
from dotenv import load_dotenv
load_dotenv()

from app.database import Database

db = Database.get_client()

# 最近 50 条铃铛相关任务记录
res = db.table("scheduler_runs") \
    .select("job_id,started_at,status,duration_sec,summary,error") \
    .in_("job_id", ["intraday_exit_passes", "intraday_scoring", "intraday_trailing_stop"]) \
    .order("started_at", desc=True) \
    .limit(30) \
    .execute()

rows = res.data or []
if not rows:
    print("scheduler_runs: 无铃铛任务记录（Render 可能从未运行这些 job）")
else:
    print(f"最近 {len(rows)} 条铃铛任务记录：\n")
    for r in rows:
        err = r.get("error") or ""
        summary = r.get("summary") or ""
        print(f"  [{r['started_at'][:19]}] {r['job_id']:30s} status={r['status']:8s}  "
              f"dur={r.get('duration_sec','?')}s  "
              f"{'ERR: '+err[:60] if err else summary[:60]}")
