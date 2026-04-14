import os, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

# All distinct job_ids in last 2 hours
since = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat()
res = sb.table('scheduler_runs').select('job_id,started_at,status').gte('started_at', since).order('started_at', desc=True).limit(200).execute()
rows = res.data

from collections import Counter
counts = Counter(r['job_id'] for r in rows)
print(f"All job_ids in last 2h ({len(rows)} total records):")
for jid, cnt in sorted(counts.items(), key=lambda x: -x[1]):
    # latest run time
    latest = next(r['started_at'][11:19] for r in rows if r['job_id'] == jid)
    print(f"  {jid:<40} x{cnt:<4}  latest={latest} UTC")

# Check for any error records
errors = [r for r in rows if r.get('status') == 'error']
print(f"\nError records: {len(errors)}")
for e in errors[:5]:
    print(f"  [{e['started_at'][11:19]}] {e['job_id']}")
