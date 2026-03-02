"""
StockQueen V1 - WebSocket Connection Test
Test script for Tiger API WebSocket long connection
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.websocket_service import (
    TigerWebSocketClient,
    get_realtime_service,
    subscribe_ticker
)


async def test_websocket_connection():
    """Test WebSocket connection and real-time data streaming"""
    print("🚀 Testing StockQueen WebSocket Long Connection\n")
    
    # Create client
    client = TigerWebSocketClient()
    
    print(f"🔗 Connecting to: {client.ws_url}")
    print(f"🆔 Tiger ID: {client.tiger_id[:10]}...")
    print(f"🔑 Token: {client.access_token[:10]}...\n")
    
    # Connect
    connected = await client.connect()
    
    if not connected:
        print("❌ Connection failed!")
        return False
    
    print("✅ Connected successfully!\n")
    
    # Test subscriptions
    test_tickers = ["AAPL", "TSLA", "MSFT"]
    
    print("📈 Subscribing to test tickers:")
    for ticker in test_tickers:
        success = await client.subscribe_quote(ticker)
        if success:
            print(f"   ✅ {ticker}")
        else:
            print(f"   ❌ {ticker}")
    
    print("\n⏳ Waiting for real-time data (30 seconds)...")
    print("   Press Ctrl+C to stop\n")
    
    # Define callback to print updates
    def on_price_update(data):
        ticker = data.get("ticker", "UNKNOWN")
        price = data.get("price", 0)
        change = data.get("change", 0)
        print(f"💰 [{ticker}] ${price:,.2f} ({change:+.2f}%)")
    
    # Register callbacks
    for ticker in test_tickers:
        client.on_quote_update(ticker, on_price_update)
    
    try:
        # Keep running for 30 seconds
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        print("\n⏹️  Stopped by user")
    
    # Disconnect
    print("\n🔌 Disconnecting...")
    await client.disconnect()
    print("✅ Test complete!")
    
    return True


async def test_realtime_service():
    """Test the high-level RealtimeMarketDataService"""
    print("\n🚀 Testing RealtimeMarketDataService\n")
    
    service = get_realtime_service()
    
    try:
        # Initialize
        print("🔌 Initializing service...")
        await service.initialize()
        print("✅ Service initialized!\n")
        
        # Add tickers to watchlist
        tickers = ["AAPL", "GOOGL", "AMZN"]
        print("📈 Adding tickers to watchlist:")
        for ticker in tickers:
            await service.add_to_watchlist(ticker)
            print(f"   ✅ {ticker}")
        
        print("\n⏳ Streaming real-time data for 30 seconds...")
        print("   Watch the logs for price updates\n")
        
        await asyncio.sleep(30)
        
        # Get cached prices
        prices = service.get_watchlist_prices()
        print(f"\n📊 Cached prices ({len(prices)} tickers):")
        for ticker, data in prices.items():
            print(f"   {ticker}: ${data.get('price', 0):,.2f}")
        
        # Shutdown
        print("\n🔌 Shutting down...")
        await service.shutdown()
        print("✅ Service test complete!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True


async def main():
    """Main test runner"""
    print("="*60)
    print("StockQueen WebSocket Long Connection Test")
    print("="*60)
    
    # Test 1: Direct WebSocket client
    print("\n📋 Test 1: Direct WebSocket Client")
    print("-"*60)
    success1 = await test_websocket_connection()
    
    # Test 2: High-level service
    print("\n" + "="*60)
    print("📋 Test 2: RealtimeMarketDataService")
    print("-"*60)
    success2 = await test_realtime_service()
    
    # Summary
    print("\n" + "="*60)
    print("📋 Test Summary")
    print("="*60)
    print(f"Direct WebSocket Client: {'✅ PASSED' if success1 else '❌ FAILED'}")
    print(f"RealtimeMarketDataService: {'✅ PASSED' if success2 else '❌ FAILED'}")
    
    if success1 and success2:
        print("\n🎉 All tests passed! WebSocket long connection is working.")
    else:
        print("\n⚠️ Some tests failed. Check the logs for details.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")