#!/usr/bin/env python3
"""
测试Yahoo Finance获取市场数据
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.market_service import MarketDataFetcher

async def test_market_data():
    """测试市场数据获取"""
    print("=" * 80)
    print("测试Yahoo Finance市场数据获取")
    print("=" * 80)
    print()
    
    fetcher = MarketDataFetcher()
    results = await fetcher.fetch_market_data_for_valid_events()
    
    print("=" * 80)
    print("获取结果")
    print("=" * 80)
    print(f"有效事件: {results['total_valid_events']}")
    print(f"成功获取: {results['total_fetched']}")
    print(f"  - Tiger API: {results['tiger_success']}")
    print(f"  - Yahoo Finance: {results['yahoo_fallback']}")
    
    if results['errors']:
        print()
        print("错误:")
        for error in results['errors'][:5]:
            print(f"  - {error}")

if __name__ == "__main__":
    asyncio.run(test_market_data())
