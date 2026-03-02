#!/usr/bin/env python3
"""
Script to create a new Feishu webhook for StockQueen
"""

import httpx
import asyncio
import json

async def test_current_webhook():
    """Test current webhook URL"""
    current_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/cli_a92adfa4a478dbc2"
    
    print("Testing current webhook URL...")
    
    try:
        payload = {
            "msg_type": "text",
            "content": {
                "text": "Testing StockQueen webhook"
            }
        }
        
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(current_webhook, json=payload)
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 0:
                    print("✅ Current webhook is working!")
                    return True
                else:
                    print("❌ Current webhook failed:", data.get("msg"))
                    return False
            else:
                print("❌ Current webhook failed with status:", response.status_code)
                return False
                
    except Exception as e:
        print(f"❌ Error testing webhook: {e}")
        return False

async def main():
    """Main function"""
    print("=" * 60)
    print("StockQueen Feishu Webhook Setup")
    print("=" * 60)
    
    # Test current webhook
    current_working = await test_current_webhook()
    
    if current_working:
        print("\n✅ Current webhook is working. No need to create a new one.")
        print(f"Webhook URL: https://open.feishu.cn/open-apis/bot/v2/hook/cli_a92adfa4a478dbc2")
    else:
        print("\n❌ Current webhook is not working. Please create a new Feishu robot.")
        print("\nSteps to create a new Feishu robot:")
        print("1. Open Feishu (飞书)")
        print("2. Go to a chat group or create a new one")
        print("3. Click on group settings → Bots → Add Bot")
        print("4. Select 'Custom Bot'")
        print("5. Name it 'StockQueen'")
        print("6. Get the webhook URL")
        print("7. Update the FEISHU_WEBHOOK_URL in .env file")
        print("\nExample webhook URL format:")
        print("https://open.feishu.cn/open-apis/bot/v2/hook/{webhook_id}")
    
    print("\n" + "=" * 60)
    print("Webhook setup completed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
