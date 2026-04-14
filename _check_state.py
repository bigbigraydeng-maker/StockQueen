import os, json
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

r = sb.table("cache_store").select("value").eq("key", "intraday_trading_state").limit(1).execute()
if r.data and r.data[0].get("value"):
    state = r.data[0]["value"]
    if isinstance(state, str):
        state = json.loads(state)
    print(f"trading_date: {state.get('trading_date')}")
    print(f"partial_tickers: {json.dumps(state.get('partial_tickers', {}), indent=2)}")
    print(f"entry_scores keys: {list(state.get('entry_scores', {}).keys())}")
    print(f"entry_times_et keys: {list(state.get('entry_times_et', {}).keys())}")
    wl = state.get('watchlist', [])
    print(f"watchlist ({len(wl)} items): {[w.get('ticker') for w in wl[:10]]}")
else:
    print("No state found")
