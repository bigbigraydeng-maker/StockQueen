from datetime import datetime
import pytz
et = pytz.timezone('US/Eastern')
now_et = datetime.now(et)
print(f"ET now: {now_et}")
print(f"ET date: {now_et.strftime('%Y-%m-%d')}")
print(f"State et_date: 2026-04-10")
print(f"Same day? {now_et.strftime('%Y-%m-%d') == '2026-04-10'}")
