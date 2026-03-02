#!/usr/bin/env python3
"""
Continuous Feishu long connection test
"""

import asyncio
import logging
from app.services.feishu_long_connection import FeishuLongConnectionService

async def main():
    """Main function"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("Continuous Feishu Long Connection Test")
    print("=" * 60)
    print("Starting long connection (will run continuously)...")
    print("Keep this running while configuring Feishu Open Platform")
    print("=" * 60)
    
    # Create and start the long connection service
    service = FeishuLongConnectionService()
    await service.start()
    
    print("\nLong connection started. Waiting for Feishu Open Platform to detect it...")
    print("Please go to Feishu Open Platform and save the event subscription configuration now.")
    print("Press Ctrl+C to stop.")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
            print(f"Long connection still active at {asyncio.get_event_loop().time()}")
    except KeyboardInterrupt:
        print("\nStopping long connection...")
        await service.stop()
        print("Long connection stopped.")

if __name__ == "__main__":
    asyncio.run(main())
