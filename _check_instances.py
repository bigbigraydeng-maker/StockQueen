import os, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

# Check last 60 min, count trailing_stop per time slot
since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=60)).isoformat()
res = sb.table('scheduler_runs').select('job_id,started_at,status').gte('started_at', since).order('started_at', desc=True).limit(100).execute()
rows = res.data

# Count trailing_stop occurrences per minute
from collections import Counter
ts_times = [r['started_at'][11:16] for r in rows if r['job_id'] == 'intraday_trailing_stop']
counts = Counter(ts_times)
print("trailing_stop counts per 5-min slot (should be 2 if 2 instances, 3 if new deployed):")
for t in sorted(counts.keys(), reverse=True)[:10]:
    print(f"  {t} UTC -> x{counts[t]}")

# Any exit_passes?
ep = [r for r in rows if 'exit_pass' in r.get('job_id','').lower()]
print(f"\nintraday_exit_passes total: {len(ep)}")

# Scoring after 16:30
sc_recent = [r for r in rows if r.get('job_id') == 'intraday_scoring' and r['started_at'][11:19] > '16:30:00']
print(f"intraday_scoring after 16:30 UTC: {len(sc_recent)}")
if sc_recent:
    for r in sc_recent:
        print(f"  {r['started_at'][11:19]}")
