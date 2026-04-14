"""Check if Render has new code by looking at exit_passes behavior.
If old code: exits only fire once per ticker (partial_done blocks re-fire).
If new code: full_profit_exit should work.

Instead, let's check: the scheduler handler returns no value, so summary is always empty.
Let's modify the handler to RETURN a result so summary captures it."""
import os, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

# Check scoring results - do they show entries?
since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=30)).isoformat()
res = sb.table('scheduler_runs').select('job_id,started_at,duration_sec,status,summary,error').in_('job_id', ['intraday_scoring', 'intraday_exit_passes']).gte('started_at', since).order('started_at', desc=True).limit(20).execute()

print(f"Scoring + Exit records (last 30 min):")
for r in res.data:
    ts = r['started_at'][11:19]
    dur = r.get('duration_sec', '?')
    summary = r.get('summary') or '(empty)'
    error = r.get('error') or ''
    print(f"  [{ts}] {r['job_id']:<25} dur={dur}s  status={r['status']}  summary={summary[:200]}")
    if error:
        print(f"    ERROR: {error[:200]}")
