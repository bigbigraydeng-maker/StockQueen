#!/usr/bin/env python
"""Intraday test: Daily Entry Check with Massive interface"""

import asyncio
import time
import sys
import os
from datetime import datetime
import pytz
import logging

# 加载 .env 文件（必须在导入 app 前）
from dotenv import load_dotenv
load_dotenv()

# 确保自动下单被启用
os.environ.setdefault("AUTO_EXECUTE_ORDERS", "true")

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

async def main():
    nzt = pytz.timezone('Pacific/Auckland')
    edt = pytz.timezone('US/Eastern')
    now_nzt = datetime.now(nzt)
    now_edt = now_nzt.astimezone(edt)

    print("\n" + "="*70)
    print("Intraday Real-Time Test: Daily Entry Check")
    print(f"Time: {now_nzt.strftime('%Y-%m-%d %H:%M:%S %Z')} / {now_edt.strftime('%H:%M EDT')}")
    print("Data Source: Massive API (OHLCV cache)")
    print("="*70 + "\n")

    start_time = time.time()

    try:
        print("[1/4] Querying pending_entry signals...")
        from app.database import get_db

        db = get_db()
        res = db.table("rotation_positions").select("*").eq("status", "pending_entry").execute()
        positions = res.data or []

        print(f"      Found {len(positions)} pending signals")
        for pos in positions:
            print(f"        - {pos['ticker']} (created: {pos['created_at'][:10]})")

        if not positions:
            print("\n      No pending signals, exiting")
            return

        print("\n[2/4] Running Entry Check...")
        from app.services.rotation_service import run_daily_entry_check

        entry_start = time.time()
        signals = await asyncio.wait_for(run_daily_entry_check(), timeout=120.0)
        entry_time = time.time() - entry_start

        print(f"      Completed in {entry_time:.1f}s")

        print(f"\n[3/4] Signal results...")
        if signals:
            print(f"      Activated {len(signals)} signal(s):")
            for sig in signals:
                print(f"        {sig.ticker}: ${sig.entry_price:.2f} SL/TP: {sig.stop_loss:.2f}/{sig.take_profit:.2f}")
        else:
            print(f"      No signals (conditions not met)")

        total_time = time.time() - start_time
        print(f"\n[4/4] Performance: {total_time:.1f}s total ({entry_time:.1f}s Entry Check)")

        print("\n" + "="*70)
        if entry_time < 60:
            print(f"SUCCESS: Entry Check in {entry_time:.1f}s - optimization effective!")
        else:
            print(f"WARNING: Entry Check took {entry_time:.1f}s - approaching timeout")
        print("="*70 + "\n")

        return True

    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        print(f"\nFAILED: Timeout after {elapsed:.1f}s")
        return False

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
