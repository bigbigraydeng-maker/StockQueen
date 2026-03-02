#!/usr/bin/env python3
"""
测试飞书API通知 - 详细诊断版
"""

import asyncio
import httpx
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

app_id = os.getenv("FEISHU_APP_ID")
app_secret = os.getenv("FEISHU_APP_SECRET")
receive_id = os.getenv("FEISHU_RECEIVE_ID")

print("=" * 60)
print("飞书API通知测试 - 详细诊断")
print("=" * 60)
print(f"App ID: {app_id}")
print(f"App Secret: {app_secret[:10]}..." if app_secret else "None")
print(f"Receive ID: {receive_id}")
print()

async def test_feishu_api():
    """测试飞书API"""
    
    # Step 1: 获取访问令牌
    print("Step 1: 获取访问令牌...")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": app_id,
                    "app_secret": app_secret
                },
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            token = data.get("tenant_access_token")
            print(f"✅ 访问令牌获取成功: {token[:20]}...")
            print()
    except Exception as e:
        print(f"❌ 获取访问令牌失败: {e}")
        return
    
    # Step 2: 发送消息
    print("Step 2: 发送测试消息...")
    print(f"Receive ID: {receive_id}")
    print(f"Receive ID Type: chat_id")
    print()
    
    try:
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": "{\"text\":\"StockQueen 测试通知 ✅\\n\\n这是一条测试消息，用于验证飞书API通知功能。\"}"
        }
        
        print(f"请求载荷: {payload}")
        print()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )
            
            print(f"响应状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            print()
            
            if response.status_code == 200:
                print("✅ 消息发送成功！")
                print()
                print("请检查飞书是否收到测试消息。")
            else:
                print(f"❌ 消息发送失败！")
                print()
                print("可能的原因：")
                print("1. receive_id格式不正确")
                print("2. 机器人没有发送消息的权限")
                print("3. receive_id对应的会话不存在")
                
    except Exception as e:
        print(f"❌ 发送消息失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_feishu_api())
