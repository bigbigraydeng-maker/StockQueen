#!/usr/bin/env python3
"""
Manual data fetch script for StockQueen
"""

import asyncio
import sys
from datetime import datetime

async def test_news_fetch():
    """Test news fetch"""
    print("=" * 60)
    print("Testing News Fetch")
    print("=" * 60)
    
    try:
        from app.services.news_service import run_news_fetcher
        result = await run_news_fetcher()
        print(f"News fetch result: {result}")
        return result
    except Exception as e:
        print(f"Error in news fetch: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_ai_classification():
    """Test AI classification"""
    print("\n" + "=" * 60)
    print("Testing AI Classification")
    print("=" * 60)
    
    try:
        from app.services.ai_service import run_ai_classification
        result = await run_ai_classification()
        print(f"AI classification result: {result}")
        return result
    except Exception as e:
        print(f"Error in AI classification: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_market_data_fetch():
    """Test market data fetch"""
    print("\n" + "=" * 60)
    print("Testing Market Data Fetch")
    print("=" * 60)
    
    try:
        from app.services.market_service import run_market_data_fetch
        result = await run_market_data_fetch()
        print(f"Market data fetch result: {result}")
        return result
    except Exception as e:
        print(f"Error in market data fetch: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_signal_generation():
    """Test signal generation"""
    print("\n" + "=" * 60)
    print("Testing Signal Generation")
    print("=" * 60)
    
    try:
        from app.services.signal_service import run_signal_generation
        signals = await run_signal_generation()
        print(f"Signal generation result: {len(signals)} signals generated")
        for i, signal in enumerate(signals, 1):
            print(f"{i}. {signal.ticker} - {signal.direction} @ ${signal.entry_price}")
        return signals
    except Exception as e:
        print(f"Error in signal generation: {e}")
        import traceback
        traceback.print_exc()
        return None

async def test_notification():
    """Test notification"""
    print("\n" + "=" * 60)
    print("Testing Notification")
    print("=" * 60)
    
    try:
        from app.services.notification_service import NotificationService
        service = NotificationService()
        
        # Test simple notification
        result = await service.feishu.send_feishu_message(
            title="StockQueen Test",
            content="This is a test notification from StockQueen"
        )
        print(f"Notification result: {result}")
        return result
    except Exception as e:
        print(f"Error in notification: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    """Main function"""
    print(f"Current time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Current NZ time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S NZ')}")
    
    # Test news fetch
    news_result = await test_news_fetch()
    
    # Test AI classification
    ai_result = await test_ai_classification()
    
    # Test market data fetch
    market_result = await test_market_data_fetch()
    
    # Test signal generation
    signals = await test_signal_generation()
    
    # Test notification
    if signals:
        notification_result = await test_notification()
    
    print("\n" + "=" * 60)
    print("All tests completed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
