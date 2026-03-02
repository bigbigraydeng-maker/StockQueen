#!/usr/bin/env python3
"""
查看数据库中的新闻和AI分类结果
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.db_service import EventService, AIEventService

async def check_database():
    """查看数据库数据"""
    print("=" * 80)
    print("数据库内容检查")
    print("=" * 80)
    print()
    
    # 查看新闻事件
    event_service = EventService()
    events = await event_service.get_pending_events()
    
    print(f"📰 待处理新闻事件: {len(events)} 条")
    print("-" * 80)
    
    for i, event in enumerate(events[:5]):
        print(f"{i+1}. {event.ticker or 'N/A'} - {event.title[:60]}...")
        print(f"   来源: {event.source}")
        print(f"   状态: {event.status}")
        print()
    
    # 查看AI分类结果
    ai_service = AIEventService()
    valid_events = await ai_service.get_valid_events()
    
    print(f"🤖 有效AI事件: {len(valid_events)} 条")
    print("-" * 80)
    
    for i, event in enumerate(valid_events[:5]):
        print(f"{i+1}. {event.ticker} - {event.event_type}")
        print(f"   方向: {event.direction_bias}")
        print()

if __name__ == "__main__":
    asyncio.run(check_database())
