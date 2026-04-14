import os, json, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=30)).isoformat()
res = sb.table('scheduler_runs').select('job_id,started_at,status,summary,error').eq('job_id', 'intraday_exit_passes').gte('started_at', since).order('started_at', desc=True).limit(10).execute()

print(f"=== intraday_exit_passes records (last 30 min) ===")
for r in res.data:
    ts = r['started_at'][11:19]
    print(f"  [{ts} UTC] status={r['status']}")
    if r.get('summary'):
        print(f"    summary: {r['summary'][:200]}")
    if r.get('error'):
        print(f"    error: {r['error'][:200]}")

# Also check intraday state
print(f"\n=== intraday_state (partial_tickers) ===")
try:
    from app.services import intraday_state_store
    state = intraday_state_store.load_state()
    print(f"  trading_date: {state.get('trading_date')}")
    partial = state.get('partial_tickers', {})
    print(f"  partial_done: {json.dumps(partial, indent=2)}")
    entry_scores = state.get('entry_scores', {})
    print(f"  entry_scores: {list(entry_scores.keys())}")
except Exception as e:
    print(f"  Error loading state: {e}")

# Check scoring result too
res2 = sb.table('scheduler_runs').select('job_id,started_at,status,summary').eq('job_id', 'intraday_scoring').gte('started_at', since).order('started_at', desc=True).limit(5).execute()
print(f"\n=== intraday_scoring records (last 30 min) ===")
for r in res2.data:
    ts = r['started_at'][11:19]
    print(f"  [{ts} UTC] status={r['status']}")
    if r.get('summary'):
        print(f"    summary: {r['summary'][:300]}")
