import os, datetime
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

url = os.environ['SUPABASE_URL']
key = os.environ['SUPABASE_SERVICE_KEY']
sb = create_client(url, key)

since = (datetime.datetime.utcnow() - datetime.timedelta(minutes=60)).isoformat()
res = sb.table('scheduler_runs').select('job_id,started_at,status,duration_sec').gte('started_at', since).order('started_at', desc=True).limit(50).execute()
rows = res.data

print(f'--- 过去60分钟所有记录 ({len(rows)} 条) ---')
for r in rows:
    t = r['started_at'][11:19]
    jid = r['job_id']
    print(f'  [{t}] {jid:<38} {r["status"]}')

ep = [r for r in rows if 'exit_pass' in r.get('job_id', '').lower()]
print(f'\n✅ intraday_exit_passes 记录数: {len(ep)}')

sc = [r for r in rows if r.get('job_id') == 'intraday_scoring']
print(f'✅ intraday_scoring 记录数: {len(sc)}')
if sc:
    times = [r['started_at'][11:19] for r in sc]
    print('   时间列表:', times)
