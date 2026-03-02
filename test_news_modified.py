#!/usr/bin/env python3
"""
测试修改后的新闻抓取逻辑 - 优先匹配医药股关注列表
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.news_service import NewsService

async def test_news_fetch():
    """测试新闻抓取"""
    print("=" * 80)
    print("测试修改后的新闻抓取逻辑")
    print("=" * 80)
    print()
    
    service = NewsService()
    results = await service.fetch_and_process_all()
    
    print("=" * 80)
    print("抓取结果")
    print("=" * 80)
    print(f"总抓取: {results['total_fetched']}")
    print(f"过滤后: {results['total_filtered']}")
    print(f"存储: {results['total_stored']}")
    
    if results['errors']:
        print()
        print("错误:")
        for error in results['errors']:
            print(f"  - {error}")

if __name__ == "__main__":
    asyncio.run(test_news_fetch())
