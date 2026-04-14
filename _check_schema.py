"""Check scheduler_runs table schema."""
import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

# Try inserting a test record with all fields to see what fails
import datetime
test_insert = {
    "job_id": "test_schema_check",
    "job_name": "Test Schema Check",
    "started_at": datetime.datetime.utcnow().isoformat(),
    "status": "running",
}
print("Testing INSERT with job_name field:")
try:
    res = sb.table('scheduler_runs').insert(test_insert).execute()
    row_id = res.data[0]['id'] if res.data else None
    print(f"  SUCCESS - row_id={row_id}")
    # Clean up
    if row_id:
        sb.table('scheduler_runs').delete().eq('id', row_id).execute()
        print(f"  Cleanup done")
except Exception as e:
    print(f"  FAILED: {e}")

# Check what columns exist
print("\nTrying to read one record to check columns:")
try:
    res = sb.table('scheduler_runs').select('*').limit(1).execute()
    if res.data:
        print(f"  Columns: {list(res.data[0].keys())}")
    else:
        print("  No records to check columns")
except Exception as e:
    print(f"  Error: {e}")
