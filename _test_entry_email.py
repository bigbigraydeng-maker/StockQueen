#!/usr/bin/env python
"""
Test script for entry notification emails.
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app.models import DailyTimingSignal
from app.services.notification_service import notify_rotation_entry, notify_rotation_entry_batch


async def test_single_entry():
    """Test single entry notification."""
    signal = DailyTimingSignal(
        ticker="VIAV",
        signal_type="entry",
        trigger_conditions=["close $41.48 > MA5 $41.19", "drift=+0.29 (0.05ATR)"],
        current_price=41.48,
        entry_price=41.48,
        stop_loss=39.98,
        take_profit=43.48,
    )

    quantity = 500
    strategy = "宝典V5"

    print("[TEST 1] Single Entry Signal: VIAV")
    print(f"  Entry: ${signal.entry_price:.2f}")
    print(f"  Quantity: {quantity} shares")
    print(f"  Position value: ${signal.entry_price * quantity:,.0f}")

    result = await notify_rotation_entry(signal, quantity=quantity, strategy=strategy)
    return result


async def test_batch_entry():
    """Test batch entry notification for multiple signals."""
    signals = [
        DailyTimingSignal(
            ticker="VIAV",
            signal_type="entry",
            trigger_conditions=["close > MA5", "volume confirmed"],
            current_price=41.48,
            entry_price=41.48,
            stop_loss=39.98,
            take_profit=43.48,
        ),
        DailyTimingSignal(
            ticker="GLW",
            signal_type="entry",
            trigger_conditions=["close > MA5", "volume confirmed"],
            current_price=175.17,
            entry_price=175.17,
            stop_loss=170.50,
            take_profit=180.00,
        ),
        DailyTimingSignal(
            ticker="MRVL",
            signal_type="entry",
            trigger_conditions=["close > MA5", "volume confirmed"],
            current_price=88.92,
            entry_price=88.92,
            stop_loss=85.20,
            take_profit=92.64,
        ),
    ]

    print("\n[TEST 2] Batch Entry Signals: VIAV, GLW, MRVL")
    print(f"  Total signals: {len(signals)}")

    result = await notify_rotation_entry_batch(signals, strategy="宝典V5")
    return result


async def main():
    print("=" * 60)
    print("Testing Entry Notification System")
    print("=" * 60)

    result1 = await test_single_entry()
    if result1:
        print("[OK] Single entry email sent")
    else:
        print("[FAILED] Single entry email failed")

    result2 = await test_batch_entry()
    if result2:
        print("[OK] Batch entry email sent")
    else:
        print("[FAILED] Batch entry email failed")

    return result1 and result2


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
