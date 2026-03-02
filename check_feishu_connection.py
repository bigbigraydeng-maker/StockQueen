#!/usr/bin/env python3
"""
Check Feishu long connection status
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
    print("Checking Feishu Long Connection Status")
    print("=" * 60)
    
    # Check configuration
    print(f"\nFeishu App ID: {settings.feishu_app_id}")
    print(f"Feishu App Secret: {settings.feishu_app_secret[:10]}...")
    
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        print("\n❌ Feishu credentials not configured!")
        return
    
    print("\n✅ Feishu credentials configured")
    
    # Get service
    service = get_feishu_event_service()
    
    # Check connection status
    if service.is_connected():
        print("\n✅ Feishu WebSocket is connected")
    else:
        print("\n❌ Feishu WebSocket is not connected")
    
    # Check if initialized
    if service._initialized:
        print("✅ Feishu Event Service is initialized")
    else:
        print("❌ Feishu Event Service is not initialized")
    
    # Check client
    if service.client:
        print("✅ Feishu client exists")
    else:
        print("❌ Feishu client does not exist")
    
    # Check connect task
    if service._connect_task:
        print(f"✅ Connect task exists (done: {service._connect_task.done()})")
    else:
        print("❌ Connect task does not exist")
    
    print("\n" + "=" * 60)
    print("Check completed")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Check Feishu Open Platform backend")
    print("2. Verify event subscription is configured")
    print("3. Send a test message to the bot")

if __name__ == "__main__":
    asyncio.run(main())
