"""Reset partial_tickers in intraday state so next exit pass can re-evaluate all positions."""
import os, json
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
r = sb.table('cache_store').select('key,value').eq('key', 'intraday_strategy_state').limit(1).execute()
if r.data and r.data[0].get('value'):
    state = r.data[0]['value']
    old_partial = state.get('partial_tickers', {})
    print(f"Before: partial_tickers = {json.dumps(old_partial)}")
    state['partial_tickers'] = {}
    sb.table('cache_store').upsert({"key": "intraday_strategy_state", "value": state}).execute()
    print("After: partial_tickers = {} (cleared)")
    print("Next exit_passes run will re-evaluate all positions for profit exit")
else:
    print("No state found")
