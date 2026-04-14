from dotenv import load_dotenv
load_dotenv()
from app.database import Database
import datetime

db = Database.get_client()
since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=20)).isoformat()

res = db.table("scheduler_runs") \
    .select("job_id,started_at,status,duration_sec") \
    .in_("job_id", ["intraday_exit_passes","intraday_scoring","intraday_trailing_stop"]) \
    .gte("started_at", since) \
    .order("started_at", desc=True) \
    .limit(20) \
    .execute()

rows = res.data or []
if not rows:
    print("最近20分钟 无铃铛任务记录（Render 仍在部署中）")
else:
    print(f"最近20分钟 铃铛任务记录 ({len(rows)} 条):")
    seen = set()
    for r in rows:
        key = r["job_id"]
        tag = " <<< NEW" if key == "intraday_exit_passes" and key not in seen else ""
        seen.add(key)
        print(f"  [{r['started_at'][11:19]}] {r['job_id']:30s} {r['status']}  {r['duration_sec']}s{tag}")
