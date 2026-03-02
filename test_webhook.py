#!/usr/bin/env python3
"""
Test script to verify Feishu webhook connection
"""

import httpx
import asyncio

async def test_webhook_connection():
    """Test Feishu webhook connection"""
    print("=" * 60)
    print("Feishu Webhook Connection Test")
    print("=" * 60)
    
    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/cli_a92adfa4a478dbc2"
    
    try:
        # Test GET request (should return 400 since it expects POST)
        print("\nTesting GET request...")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(webhook_url)
            print(f"GET Status: {response.status_code}")
            print(f"GET Content: {response.text[:200]}...")
        
        # Test POST request with proper format
        print("\nTesting POST request...")
        test_payload = {
            "msg_type": "text",
            "content": {
                "text": "Test connection from StockQueen"
            }
        }
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(webhook_url, json=test_payload)
            print(f"POST Status: {response.status_code}")
            print(f"POST Content: {response.text[:200]}...")
        
        print("\n" + "=" * 60)
        print("Connection test completed")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_webhook_connection())
