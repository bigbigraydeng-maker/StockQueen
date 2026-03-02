#!/usr/bin/env python3
"""
Test Feishu configuration
"""

import asyncio
import logging
from app.config import settings
from app.services.feishu_event_service import get_feishu_event_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

async def main():
    """Main function"""
    print("=" * 60)
    print("Testing Feishu Configuration")
    print("=" * 60)
    
    # Check configuration
    print(f"\nFeishu App ID: {settings.feishu_app_id}")
    print(f"Feishu App Secret: {settings.feishu_app_secret[:10]}...")
    
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        print("\n❌ Feishu credentials not configured!")
        return
    
    print("\n✅ Feishu credentials configured")
    
    # Test Feishu event service
    print("\n" + "=" * 60)
    print("Testing Feishu Event Service")
    print("=" * 60)
    
    service = get_feishu_event_service()
    
    try:
        print("\nInitializing Feishu Event Service...")
        success = await service.initialize()
        
        if success:
            print("\n✅ Feishu Event Service initialized successfully!")
            
            # Keep running for a while to test connection
            print("\nWaiting 10 seconds to test connection...")
            await asyncio.sleep(10)
            
            # Check connection status
            if service.client.is_connected:
                print("\n✅ Feishu WebSocket is connected!")
            else:
                print("\n❌ Feishu WebSocket is not connected")
            
            # Shutdown
            await service.shutdown()
            print("\n✅ Feishu Event Service shutdown complete")
        else:
            print("\n❌ Failed to initialize Feishu Event Service")
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
