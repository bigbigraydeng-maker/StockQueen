"""
StockQueen V1 - Feishu Platform Event Connection Test
Test script for Feishu Open Platform WebSocket long connection
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.feishu_event_service import (
    FeishuEventClient,
    FeishuEventService,
    get_feishu_event_service
)
from app.config import settings


async def test_direct_connection():
    """Test direct Feishu WebSocket connection"""
    print("🚀 Testing Feishu Platform Direct Connection\n")
    
    # Check credentials
    app_id = settings.feishu_app_id
    app_secret = settings.feishu_app_secret
    
    if not app_id or not app_secret:
        print("❌ Error: FEISHU_APP_ID or FEISHU_APP_SECRET not configured")
        print("   Please check your .env file")
        return False
    
    print(f"📱 App ID: {app_id}")
    print(f"🔑 App Secret: {app_secret[:10]}...\n")
    
    # Create client
    client = FeishuEventClient(app_id, app_secret)
    
    # Connect
    print(f"🔗 Connecting to Feishu Platform...")
    connected = await client.connect()
    
    if not connected:
        print("\n❌ Connection failed!")
        print("\nPossible reasons:")
        print("   1. App ID or App Secret is incorrect")
        print("   2. App is not published or in testing mode")
        print("   3. Network connection issue")
        print("   4. Feishu Platform service is down")
        return False
    
    print("\n✅ Connected successfully to Feishu Platform!")
    print("\n📡 Waiting for events (60 seconds)...")
    print("   - Send a message to the bot in Feishu")
    print("   - Or trigger any event in the Feishu app")
    print("   - Press Ctrl+C to stop\n")
    
    # Register a test handler
    def test_handler(event):
        print(f"\n📨 Event received!")
        print(f"   Type: {event.get('header', {}).get('event_type', 'unknown')}")
        print(f"   Content: {str(event)[:200]}...")
    
    client.on_event("*", test_handler)
    
    try:
        # Keep running for 60 seconds
        await asyncio.sleep(60)
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopped by user")
    
    # Disconnect
    print("\n🔌 Disconnecting...")
    await client.disconnect()
    print("✅ Test complete!")
    
    return True


async def test_service():
    """Test Feishu Event Service"""
    print("\n" + "="*60)
    print("🚀 Testing Feishu Event Service")
    print("="*60 + "\n")
    
    service = get_feishu_event_service()
    
    try:
        # Initialize
        print("🔌 Initializing Feishu Event Service...")
        await service.initialize()
        
        if not service._initialized:
            print("❌ Service failed to initialize")
            return False
        
        print("✅ Service initialized!\n")
        
        print("⏳ Listening for events (60 seconds)...")
        print("   Send a message to your bot in Feishu to test\n")
        
        await asyncio.sleep(60)
        
        # Shutdown
        print("\n🔌 Shutting down...")
        await service.shutdown()
        print("✅ Service test complete!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


async def main():
    """Main test runner"""
    print("="*60)
    print("Feishu Platform Event Connection Test")
    print("="*60)
    
    # Check configuration
    print("\n📋 Configuration Check:")
    print(f"   FEISHU_APP_ID: {'✅ Set' if settings.feishu_app_id else '❌ Not set'}")
    print(f"   FEISHU_APP_SECRET: {'✅ Set' if settings.feishu_app_secret else '❌ Not set'}")
    
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        print("\n❌ Error: Missing required configuration")
        print("\nPlease add to your .env file:")
        print("   FEISHU_APP_ID=cli_a92adfa4a478dbc2")
        print("   FEISHU_APP_SECRET=your-app-secret")
        return
    
    # Test 1: Direct connection
    print("\n" + "="*60)
    print("📋 Test 1: Direct WebSocket Connection")
    print("="*60)
    success1 = await test_direct_connection()
    
    # Test 2: Service test
    print("\n" + "="*60)
    print("📋 Test 2: Event Service")
    print("="*60)
    success2 = await test_service()
    
    # Summary
    print("\n" + "="*60)
    print("📋 Test Summary")
    print("="*60)
    print(f"Direct Connection: {'✅ PASSED' if success1 else '❌ FAILED'}")
    print(f"Event Service: {'✅ PASSED' if success2 else '❌ FAILED'}")
    
    if success1 and success2:
        print("\n🎉 All tests passed! Feishu long connection is working.")
        print("\n📖 Next steps:")
        print("   1. Go to Feishu Open Platform")
        print("   2. Check 'Event Configuration' - status should be 'Connected'")
        print("   3. Subscribe to events you want to receive")
        print("   4. Test by sending messages to your bot")
    else:
        print("\n⚠️ Some tests failed. Check the logs for details.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()