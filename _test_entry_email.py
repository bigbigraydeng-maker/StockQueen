#!/usr/bin/env python
"""
Test script for new entry notification email with fundamentals.
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app.models import DailyTimingSignal
from app.services.notification_service import notify_rotation_entry


async def test_entry_email():
    """Test entry notification with sample data."""

    # 创建测试信号（模拟一个来自 VIAV 的进场信号）
    signal = DailyTimingSignal(
        ticker="VIAV",
        signal_type="entry",
        trigger_conditions=["close $41.48 > MA5 $41.19", "drift=+0.29 (0.05ATR)"],
        current_price=41.48,
        entry_price=41.48,
        stop_loss=39.98,
        take_profit=43.48,
    )

    # 测试有仓位信息的情况
    quantity = 500  # 500 股
    strategy = "宝典V5"

    print(f"Testing entry email for {signal.ticker}...")
    print(f"  Entry: ${signal.entry_price:.2f}")
    print(f"  Quantity: {quantity} shares")
    print(f"  Position value: ${signal.entry_price * quantity:,.0f}")

    result = await notify_rotation_entry(signal, quantity=quantity, strategy=strategy)

    if result:
        print("\n[OK] Entry notification email sent successfully!")
        print(f"   Check: {os.environ.get('EMAIL_TO', 'bigbigraydeng@gmail.com')}")
    else:
        print("\n[FAILED] Failed to send entry notification email")
        print("   Check email configuration in .env")

    return result


if __name__ == "__main__":
    result = asyncio.run(test_entry_email())
    sys.exit(0 if result else 1)
