#!/usr/bin/env python3
"""
Test script to verify Feishu long connection
"""

import asyncio
import time
from app.services.feishu_long_connection import start_feishu_long_connection, stop_feishu_long_connection, get_feishu_long_connection

async def test_feishu_long_connection():
    """Test Feishu long connection"""
    print("=" * 60)
    print("Feishu Long Connection Test")
    print("=" * 60)
    
    try:
        # Start long connection
        print("Starting Feishu long connection...")
        success = await start_feishu_long_connection()
        
        if success:
            print("✅ Long connection started successfully")
            
            # Check connection status
            connection = get_feishu_long_connection()
            print(f"Connection status: {connection.is_connected()}")
            
            # Keep connection alive for testing
            print("\nKeeping connection alive for 30 seconds...")
            print("Check Feishu backend for long connection events")
            
            for i in range(30):
                print(f"Connection active for {i+1} seconds...", end="\r")
                await asyncio.sleep(1)
            
        else:
            print("❌ Failed to start long connection")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Stop connection
        print("\nStopping Feishu long connection...")
        await stop_feishu_long_connection()
        print("Connection stopped")
    
    print("\n" + "=" * 60)
    print("Long connection test completed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_feishu_long_connection())
