#!/usr/bin/env python3
"""
测试yfinance数据源
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.market_service import YahooFinanceClient

async def test_yahoo_finance():
    """测试Yahoo Finance数据源"""
    print("=" * 80)
    print("测试Yahoo Finance数据源")
    print("=" * 80)
    print()
    
    client = YahooFinanceClient()
    
    # 测试几个医药股
    test_tickers = ["MRNA", "PFE", "LLY", "BGNE"]
    
    for ticker in test_tickers:
        print(f"测试 {ticker}...")
        quote = await client.get_stock_quote(ticker)
        
        if quote:
            print(f"  ✅ 成功获取数据")
            print(f"     当前价格: ${quote['latest_price']:.2f}")
            print(f"     涨跌幅: {quote['change_percent']:.2f}%")
            print(f"     成交量: {quote['volume']:,}")
            print(f"     市值: ${quote['market_cap']:,.0f}")
            print(f"     数据来源: {quote.get('data_source', 'unknown')}")
        else:
            print(f"  ❌ 获取失败")
        print()

if __name__ == "__main__":
    asyncio.run(test_yahoo_finance())
