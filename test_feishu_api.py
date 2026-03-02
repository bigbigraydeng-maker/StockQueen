"""
测试飞书API
"""

import asyncio
import httpx
from dotenv import load_dotenv
import os

load_dotenv()

app_id = os.getenv("FEISHU_APP_ID")
app_secret = os.getenv("FEISHU_APP_SECRET")

if not app_id or not app_secret:
    print("❌ 飞书应用凭证未配置")
    print("请在.env文件中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
    exit(1)

print(f"应用ID: {app_id}")
print(f"应用密钥: {app_secret[:10]}...")
print()


async def test_feishu_api():
    """测试飞书API"""
    base_url = "https://open.feishu.cn/open-apis"
    
    # 步骤1: 获取访问令牌
    print("📡 步骤1: 获取访问令牌...")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": app_id,
                    "app_secret": app_secret
                },
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            access_token = data.get("tenant_access_token")
            print(f"✅ 访问令牌获取成功: {access_token[:20]}...")
            print()
    except Exception as e:
        print(f"❌ 获取访问令牌失败: {e}")
        return
    
    # 步骤2: 获取机器人信息
    print("📡 步骤2: 获取机器人信息...")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/bot/v3/info",
                headers={
                    "Authorization": f"Bearer {access_token}"
                },
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            bot_info = data.get("bot", {})
            print(f"✅ 机器人名称: {bot_info.get('app_name')}")
            print(f"✅ 机器人ID: {bot_info.get('open_id')}")
            print()
    except Exception as e:
        print(f"❌ 获取机器人信息失败: {e}")
        return
    
    # 步骤3: 发送测试消息（需要提供接收者ID）
    print("📡 步骤3: 发送测试消息...")
    print("⚠️  需要提供接收者ID（用户ID、群组ID或邮件）")
    print()
    print("如何获取接收者ID:")
    print("1. 在飞书中@机器人，机器人会收到消息事件")
    print("2. 从消息事件中获取sender_id或chat_id")
    print("3. 或者使用飞书开放平台的API查询")
    print()
    print("当前StockQueen使用长连接模式，需要先配置事件订阅")
    print("请参考: FEISHU_EVENT_SUBSCRIPTION_GUIDE.md")
    print()
    print("或者，你可以手动提供接收者ID进行测试:")
    print()
    
    receive_id = input("请输入接收者ID（留空跳过）: ").strip()
    
    if receive_id:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{base_url}/im/v1/messages?receive_id_type=open_id",
                    headers={
                        "Authorization": f"Bearer {access_token}"
                    },
                    json={
                        "receive_id": receive_id,
                        "msg_type": "text",
                        "content": "{\"text\":\"StockQueen API测试成功 ✅\"}"
                    },
                    timeout=10
                )
                response.raise_for_status()
                
                print(f"✅ 消息发送成功！")
                print(f"状态码: {response.status_code}")
                print(f"响应: {response.text}")
        except Exception as e:
            print(f"❌ 发送消息失败: {e}")
    else:
        print("⏭️  跳过消息发送测试")


if __name__ == "__main__":
    print("=" * 60)
    print("StockQueen - 飞书API测试")
    print("=" * 60)
    print()
    
    try:
        asyncio.run(test_feishu_api())
    except KeyboardInterrupt:
        print("\n\n👋 测试已停止")
