#!/usr/bin/env python
"""Test Entry Check core logic only (skip fallback) to measure data fetch performance"""

import asyncio
import time
import sys
import pytz
from datetime import datetime
import logging

logging.basicConfig(level=logging.WARNING)

async def main():
    nzt = pytz.timezone('Pacific/Auckland')
    edt = pytz.timezone('US/Eastern')
    now_nzt = datetime.now(nzt)
    now_edt = now_nzt.astimezone(edt)

    print("\n" + "="*70)
    print("Entry Check Core Logic Test (no fallback)")
    print(f"Time: {now_nzt.strftime('%Y-%m-%d %H:%M:%S %Z')} / {now_edt.strftime('%H:%M EDT')}")
    print("="*70 + "\n")

    start_time = time.time()

    try:
        print("[1/3] Query pending_entry signals...")
        from app.database import get_db
        from app.services.rotation_service import _get_positions_by_status, _detect_regime
        from app.config.rotation_watchlist import RotationConfig as RC

        db = get_db()
        positions = await _get_positions_by_status("pending_entry")
        print(f"      Found {len(positions)} signals")

        print("\n[2/3] Concurrent data fetch (OPTIMIZED)...")
        from app.services.rotation_service import _fetch_history
        import numpy as np

        # Concurrent fetch all histories
        fetch_start = time.time()
        tasks = [asyncio.wait_for(_fetch_history(pos["ticker"], days=30), timeout=15.0) for pos in positions]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30.0)
        except asyncio.TimeoutError:
            print("      ERROR: Timeout during concurrent fetch")
            return False

        fetch_time = time.time() - fetch_start
        print(f"      Concurrent fetch completed in {fetch_time:.1f}s")

        # Count successful fetches
        success_count = sum(1 for r in results if not isinstance(r, Exception) and r is not None)
        print(f"      Success: {success_count}/{len(positions)} stocks")

        print("\n[3/3] Entry condition check (serial)...")
        regime = await _detect_regime()
        stop_mult = RC.ATR_STOP_BY_REGIME.get(regime, RC.ATR_STOP_MULTIPLIER)
        target_mult = RC.ATR_TARGET_BY_REGIME.get(regime, RC.ATR_TARGET_MULTIPLIER)

        entry_count = 0
        for pos, history_data in zip(positions, results):
            if isinstance(history_data, Exception) or history_data is None:
                continue

            closes = history_data["close"]
            volumes = history_data["volume"]
            current_price = float(closes[-1])
            current_vol = float(volumes[-1])

            ma5 = float(np.mean(closes[-5:]))
            avg_vol = float(np.mean(volumes[-20:]))

            if current_price > ma5 and current_vol > avg_vol:
                entry_count += 1
                print(f"      {pos['ticker']}: MA5 pass, volume pass (would activate)")

        total_time = time.time() - start_time
        print(f"\n      Signals ready for entry: {entry_count}")

        print("\n" + "="*70)
        print(f"RESULT: Core Entry Check in {total_time:.1f}s ({fetch_time:.1f}s fetch)")
        if total_time < 60:
            print("SUCCESS: Within 60s threshold - optimization working!")
        else:
            print(f"WARNING: Still {total_time - 60:.1f}s over threshold")
        print("="*70 + "\n")

        return True

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
