from dotenv import load_dotenv
load_dotenv()
from app.database import Database
import datetime

db = Database.get_client()

# 1. 最近30分钟所有任务（不过滤）
since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=35)).isoformat()
res = db.table("scheduler_runs") \
    .select("job_id,started_at,status,error") \
    .gte("started_at", since) \
    .order("started_at", desc=True) \
    .limit(60) \
    .execute()

rows = res.data or []
print(f"最近35分钟所有任务 ({len(rows)} 条):\n")

# 按 job_id 统计出现次数
from collections import Counter
counts = Counter(r["job_id"] for r in rows)
for job_id, cnt in sorted(counts.items()):
    errors = [r for r in rows if r["job_id"] == job_id and r.get("status") == "error"]
    err_str = f"  [!ERROR: {errors[0].get('error','?')[:80]}]" if errors else ""
    print(f"  {job_id:40s} x{cnt}{err_str}")

print()
# 2. 专门搜 exit_passes 有没有 error 记录（历史所有）
res2 = db.table("scheduler_runs") \
    .select("job_id,started_at,status,error") \
    .eq("status", "error") \
    .gte("started_at", "2026-04-10T00:00:00") \
    .order("started_at", desc=True) \
    .limit(10) \
    .execute()
errors = res2.data or []
print(f"今日 error 记录 ({len(errors)} 条):")
for r in errors:
    print(f"  [{r['started_at'][11:19]}] {r['job_id']:35s} {r.get('error','')[:100]}")

# 3. 检查 intraday_scoring 最近几条，看 trigger 是否是15min
res3 = db.table("scheduler_runs") \
    .select("job_id,started_at,status") \
    .eq("job_id", "intraday_scoring") \
    .order("started_at", desc=True) \
    .limit(6) \
    .execute()
print(f"\nintraday_scoring 最近运行时间:")
for r in (res3.data or []):
    print(f"  {r['started_at'][11:19]} UTC")
