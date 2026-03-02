#!/usr/bin/env python3
"""
Test script for notification service
"""

import asyncio
from app.services.notification_service import NotificationService
from app.models import Signal

async def test_notification_service():
    print("Testing notification service...")
    
    # Create test signals
    from datetime import datetime
    test_signals = [
        Signal(
            id="1",
            ticker="BTI",
            event_id="1",
            market_snapshot_id="1",
            direction="long",
            entry_price=50.0,
            stop_loss=47.5,
            target_price=55.0,
            confidence_score=85.5,
            status="confirmed",
            created_at=datetime.now(),
            updated_at=datetime.now()
        ),
        Signal(
            id="2",
            ticker="ABBV",
            event_id="2",
            market_snapshot_id="2",
            direction="short",
            entry_price=120.0,
            stop_loss=126.0,
            target_price=108.0,
            confidence_score=75.0,
            status="confirmed",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
    ]
    
    # Test signal summary notification
    service = NotificationService()
    print("\nTesting signal summary notification...")
    success = await service.send_signal_summary(test_signals)
    print(f"Signal summary notification sent: {success}")
    
    # Test trade confirmation notification
    print("\nTesting trade confirmation notification...")
    success = await service.send_trade_confirmation(test_signals[0], "ORDER12345")
    print(f"Trade confirmation notification sent: {success}")
    
    # Test risk alert
    print("\nTesting risk alert...")
    success = await service.send_risk_alert("High Drawdown", "Account drawdown exceeds 10%")
    print(f"Risk alert sent: {success}")

if __name__ == "__main__":
    asyncio.run(test_notification_service())
