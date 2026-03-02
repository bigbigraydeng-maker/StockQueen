#!/usr/bin/env python3
"""
Test script to verify Feishu notification service
"""

import asyncio
from app.services.notification_service import NotificationService
from app.models import Signal
from datetime import datetime

async def test_feishu_notification():
    """Test Feishu notification"""
    print("=" * 60)
    print("Feishu Notification Test")
    print("=" * 60)
    
    try:
        # Create notification service
        notification_service = NotificationService()
        
        # Test 1: Test send_feishu_message directly
        print("\nTest 1: Testing send_feishu_message...")
        await notification_service.feishu.send_feishu_message(
            title="Test Notification",
            content="This is a test message from StockQueen"
        )
        print("✅ Test 1 passed: Feishu message sent successfully")
        
        # Test 2: Test signal summary notification
        print("\nTest 2: Testing signal summary notification...")
        test_signals = [
            Signal(
                id="test-1",
                ticker="AAPL",
                event_id="test-event-1",
                market_snapshot_id="test-market-1",
                direction="long",
                entry_price=180.5,
                target_price=200.0,
                stop_loss=175.0,
                confidence_score=0.95
            ),
            Signal(
                id="test-2",
                ticker="MSFT",
                event_id="test-event-2",
                market_snapshot_id="test-market-2",
                direction="short",
                entry_price=400.0,
                target_price=380.0,
                stop_loss=410.0,
                confidence_score=0.85
            )
        ]
        await notification_service.send_signal_summary(test_signals)
        print("✅ Test 2 passed: Signal summary notification sent successfully")
        
        # Test 3: Test trade executed notification
        print("\nTest 3: Testing trade executed notification...")
        await notification_service.send_trade_confirmation(test_signals[0], "test-order-1")
        print("✅ Test 3 passed: Trade executed notification sent successfully")
        
        print("\n" + "=" * 60)
        print("All tests passed! Feishu notification is working.")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_feishu_notification())
