"""
本地临时守护：每 5 分钟跑一次 exit pass，直到 Render 部署完成
用法：python _local_guard.py
按 Ctrl+C 停止
"""
import asyncio, time, datetime, pytz
from dotenv import load_dotenv
load_dotenv()

ET = pytz.timezone("US/Eastern")
INTERVAL_SEC = 300  # 5 分钟

async def run_once():
    now = datetime.datetime.now(ET)
    print(f"\n[{now.strftime('%H:%M:%S')} ET] ===== exit pass =====")
    from app.services.intraday_service import run_intraday_exits_only
    from app.config.intraday_config import IntradayConfig as cfg
    result = await run_intraday_exits_only(enable_auto_execute=cfg.AUTO_EXECUTE)
    status = result.get("status")
    if status == "skipped":
        print(f"  跳过: {result.get('reason')}")
    elif status == "ok":
        t = result.get("trading") or {}
        exits = t.get("exits") or []
        entries = t.get("entries") or []
        print(f"  exits={len(exits)}  entries={len(entries)}")
        for e in exits:
            print(f"  [EXIT] {e.get('ticker')} {e.get('reason')} pnl={e.get('pnl_pct')}%")
        for e in entries:
            print(f"  [ENTRY] {e.get('ticker')}")
        if not exits and not entries:
            print("  (无动作，持仓正常)")

def is_market_open():
    now = datetime.datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.time()
    import datetime as dt
    return dt.time(9, 30) <= t <= dt.time(16, 5)

async def main():
    print("=== 本地止损守护已启动（每5分钟检查）===")
    print("按 Ctrl+C 停止\n")
    while True:
        if is_market_open():
            try:
                await run_once()
            except Exception as e:
                print(f"  [ERROR] {e}")
        else:
            now = datetime.datetime.now(ET)
            print(f"[{now.strftime('%H:%M:%S')} ET] 盘外，等待...")
        await asyncio.sleep(INTERVAL_SEC)

asyncio.run(main())
