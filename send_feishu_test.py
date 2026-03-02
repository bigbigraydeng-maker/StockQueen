#!/usr/bin/env python3
"""
发送测试消息到飞书
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.notification_service import FeishuClient

async def send_test_message():
    """发送测试消息"""
    print("=" * 80)
    print("发送测试消息到飞书")
    print("=" * 80)
    print()
    
    client = FeishuClient()
    
    # 构建消息内容
    title = "🎉 StockQueen 系统测试"
    content_text = """✅ 新闻抓取优化完成
- 优先匹配医药股关注列表
- 过滤效果：75条 → 40条高质量新闻

✅ 数据源降级完成
- Tiger API (主) + Yahoo Finance (备用)
- 测试通过：MRNA, PFE, LLY

系统运行正常！🚀"""
    
    # 使用正确的JSON格式
    message_content = json.dumps({"text": f"{title}\n\n{content_text}"}, ensure_ascii=False)
    
    # 获取token
    token = await client._get_access_token()
    
    print(f"Token获取成功: {token[:20]}...")
    print(f"Receive ID: {client.receive_id}")
    print()
    
    # 发送消息
    import httpx
    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers={
                    "Authorization": f"Bearer {token}"
                },
                json={
                    "receive_id": client.receive_id,
                    "msg_type": "text",
                    "content": message_content
                },
                timeout=10
            )
            
            print(f"响应状态: {response.status_code}")
            print(f"响应内容: {response.text}")
            
            if response.status_code == 200:
                print()
                print("✅ 消息发送成功！请查看飞书")
            else:
                print()
                print("❌ 消息发送失败")
                
    except Exception as e:
        print(f"❌ 发送错误: {e}")

if __name__ == "__main__":
    asyncio.run(send_test_message())
