import os, json
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
r = sb.table('cache_store').select('value').eq('key', 'intraday_strategy_state').limit(1).execute()
if r.data and r.data[0].get('value'):
    state = r.data[0]['value']
    print(f"et_date: {state.get('et_date')}")
    print(f"partial_tickers: {json.dumps(state.get('partial_tickers', {}), indent=2)}")
    print(f"entry_scores keys: {list(state.get('entry_scores', {}).keys())}")
    wl = state.get('watchlist', [])
    print(f"watchlist ({len(wl)} items): {[w.get('ticker') for w in wl[:10]]}")
else:
    print('No state found for key=intraday_strategy_state')
