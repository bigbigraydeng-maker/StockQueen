"""Apply intraday_signal_audit migration directly to Supabase production."""
import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

# Read migration SQL
with open('supabase/migrations/20260411130000_intraday_signal_audit.sql', 'r', encoding='utf-8') as f:
    sql = f.read()

print("Applying migration: 20260411130000_intraday_signal_audit.sql")
try:
    result = sb.rpc('exec_sql', {'query': sql}).execute()
    print("Migration applied successfully!")
except Exception as e:
    print(f"RPC method failed, trying direct query: {e}")
    # Try checking if table already exists
    try:
        test = sb.table('intraday_signal_audit').select('id').limit(1).execute()
        print("Table already exists! Migration already applied.")
    except Exception as e2:
        print(f"Table does not exist: {e2}")
        print("\nSQL to run manually in Supabase SQL editor:")
        print(sql)
