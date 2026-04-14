import os, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

# Check for any 'running' status records
res = sb.table('scheduler_runs').select('id,job_id,started_at,status').eq('status', 'running').order('started_at', desc=True).limit(20).execute()
rows = res.data

print(f"Records with status='running': {len(rows)}")
for r in rows:
    print(f"  [{r['started_at'][11:19]}] {r['job_id']}")

# Also check recent intraday records including all statuses
since = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat()
res2 = sb.table('scheduler_runs').select('job_id,started_at,status').like('job_id', 'intraday%').gte('started_at', since).order('started_at', desc=True).limit(30).execute()
rows2 = res2.data
print(f"\nAll intraday* records in last 1h: {len(rows2)}")
for r in rows2:
    print(f"  [{r['started_at'][11:19]}] {r['job_id']:<40} {r['status']}")
