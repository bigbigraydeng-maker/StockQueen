"""
Test Twilio HIGH signal notification
"""
import asyncio
from app.services.notification_service import NotificationService, TwilioClient
from app.models import Signal, DirectionBias, SignalRating
from datetime import datetime


async def test_twilio_call():
    """Test Twilio voice call for HIGH signal"""
    print("=" * 60)
    print("📞 Testing Twilio Voice Call for HIGH Signal")
    print("=" * 60)
    
    # Create a mock HIGH signal
    mock_signal = Signal(
        id="test-signal-001",
        ticker="XYZ",
        event_id="test-event-001",
        market_snapshot_id="test-snapshot-001",
        status="observe",
        direction=DirectionBias.LONG,
        rating=SignalRating.HIGH,
        entry_price=12.50,
        stop_loss=11.88,
        target_price=13.75,
        confidence_score=85.0,
        ma20=10.20,
        price_above_ma20=True,
        day_change_pct=45.2,
        volume_multiplier=5.3,
        human_confirmed=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    
    print(f"\n📊 Mock Signal:")
    print(f"   Ticker: {mock_signal.ticker}")
    print(f"   Rating: {mock_signal.rating}")
    print(f"   Entry: ${mock_signal.entry_price}")
    print(f"   Day Change: {mock_signal.day_change_pct}%")
    
    # Test notification service
    service = NotificationService()
    
    print(f"\n📞 Sending HIGH signal alert...")
    print(f"   From: +1 314 271 3760")
    print(f"   To: +64 27 752 0888")
    
    result = await service.send_high_signal_alert(mock_signal)
    
    if result:
        print("\n✅ HIGH signal alert sent successfully!")
        print("   You should receive:")
        print("   1. An SMS message")
        print("   2. A voice call with TTS message")
    else:
        print("\n❌ Failed to send HIGH signal alert")
    
    return result


async def test_sms_only():
    """Test SMS only"""
    print("\n" + "=" * 60)
    print("📱 Testing SMS Only")
    print("=" * 60)
    
    client = TwilioClient()
    
    result = await client.send_sms(
        "StockQueen Test: This is a test message from StockQueen system."
    )
    
    if result:
        print("✅ SMS sent successfully!")
    else:
        print("❌ Failed to send SMS")
    
    return result


async def test_call_only():
    """Test voice call only"""
    print("\n" + "=" * 60)
    print("📞 Testing Voice Call Only")
    print("=" * 60)
    
    client = TwilioClient()
    
    result = await client.make_call(
        "Test signal for XYZ stock. Entry price 12.50 dollars. This is a test call."
    )
    
    if result:
        print("✅ Voice call initiated successfully!")
    else:
        print("❌ Failed to initiate voice call")
    
    return result


if __name__ == "__main__":
    print("\n🚀 Starting Twilio Notification Tests\n")
    
    # Run all tests
    asyncio.run(test_twilio_call())
