import os, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=20)).isoformat()
res = sb.table('scheduler_runs').select('job_id,started_at,status,summary').gte('started_at', since).order('started_at', desc=True).limit(30).execute()
rows = res.data

print(f"Records in last 20 min: {len(rows)}")
for r in rows:
    ts = r['started_at'][11:19]
    summary = (r.get('summary') or '')[:80]
    print(f"  [{ts} UTC] {r['job_id']:<35} {r['status']:<8} {summary}")
