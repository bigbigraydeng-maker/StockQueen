"""Check ALL exit_passes records since timezone fix deploy."""
import os, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
since = '2026-04-10T17:55:00'
res = sb.table('scheduler_runs').select('job_id,started_at,finished_at,duration_sec,status,summary,error').eq('job_id', 'intraday_exit_passes').gte('started_at', since).order('started_at', desc=True).limit(20).execute()

print(f"All exit_passes since 17:55 UTC ({len(res.data)} records):")
for r in res.data:
    ts = r['started_at'][11:19]
    dur = r.get('duration_sec', '?')
    summary = r.get('summary') or '(empty)'
    error = r.get('error') or ''
    print(f"  [{ts}] status={r['status']} dur={dur}s summary={summary[:150]}")
    if error:
        print(f"          ERROR: {error[:200]}")
