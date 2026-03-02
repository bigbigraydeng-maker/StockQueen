#!/usr/bin/env python3
"""
Test script for signal generation and notification modules
"""

import asyncio
from app.services.signal_service import run_signal_generation
from app.services.notification_service import notify_signals_ready
from app.models import Signal

async def test_signal_generation():
    print("Testing signal generation...")
    
    # Run signal generation
    signals = await run_signal_generation()
    
    print(f"\nSignal generation results:")
    print(f"Total signals generated: {len(signals)}")
    
    for signal in signals:
        print(f"- {signal.ticker}: {signal.direction} at ${signal.entry_price}")
    
    # Test notification
    if signals:
        print("\nTesting notification service...")
        success = await notify_signals_ready(signals)
        print(f"Notification sent: {success}")
    else:
        print("\nNo signals to notify about")

if __name__ == "__main__":
    asyncio.run(test_signal_generation())
