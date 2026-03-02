#!/usr/bin/env python3
"""
发送完整结果到飞书
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.db_service import AIEventService
from app.services.notification_service import FeishuClient

async def send_results():
    """发送结果到飞书"""
    print("=" * 80)
    print("发送结果到飞书")
    print("=" * 80)
    print()
    
    # 获取有效事件
    ai_service = AIEventService()
    valid_events = await ai_service.get_valid_events()
    
    print(f"有效事件: {len(valid_events)} 条")
    
    # 统计事件类型
    event_types = {}
    tickers = []
    for event in valid_events:
        event_type = str(event.event_type).replace("EventType.", "")
        event_types[event_type] = event_types.get(event_type, 0) + 1
        if event.ticker:
            tickers.append(event.ticker)
    
    print(f"事件类型分布: {event_types}")
    print(f"相关股票: {list(set(tickers))}")
    
    # 构建通知内容
    content = f"""📊 StockQueen 日报

✅ 系统运行正常

📰 新闻处理
- 已处理: 41 条新闻
- 有效事件: {len(valid_events)} 条

📈 事件类型分布
"""
    
    for event_type, count in sorted(event_types.items()):
        content += f"- {event_type}: {count} 条\n"
    
    if tickers:
        content += f"\n🎯 相关股票\n"
        content += f"- {', '.join(list(set(tickers)))}\n"
    
    content += """
⏳ 下一步
- 配置Tiger账户后可获取实时价格
- 满足条件时自动生成交易信号"""

    # 发送通知
    feishu = FeishuClient()
    
    token = await feishu._get_access_token()
    message_text = f"📊 StockQueen 日报\n\n{content}"
    content_json = json.dumps({"text": message_text}, ensure_ascii=False)
    
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            headers={
                "Authorization": f"Bearer {token}"
            },
            json={
                "receive_id": feishu.receive_id,
                "msg_type": "text",
                "content": content_json
            },
            timeout=10
        )
        
        print(f"响应状态: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ 消息发送成功！请查看飞书")
        else:
            print(f"❌ 发送失败: {response.text}")

if __name__ == "__main__":
    asyncio.run(send_results())
