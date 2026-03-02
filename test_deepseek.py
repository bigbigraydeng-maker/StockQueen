#!/usr/bin/env python3
"""
测试DeepSeek AI分类功能
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.ai_service import DeepSeekClient

async def test_deepseek():
    """测试DeepSeek AI分类"""
    print("=" * 80)
    print("测试DeepSeek AI分类功能")
    print("=" * 80)
    print()
    
    client = DeepSeekClient()
    
    # 测试几条新闻
    test_news = [
        {
            "ticker": "MRNA",
            "title": "Moderna Announces Positive Phase 3 Results for COVID-19 Vaccine",
            "summary": "Moderna reported positive topline results from its Phase 3 trial, showing 94.5% efficacy."
        },
        {
            "ticker": "PFE",
            "title": "Pfizer Receives FDA Approval for New Cancer Drug",
            "summary": "FDA grants approval for Pfizer's new oncology treatment."
        },
        {
            "ticker": "LLY",
            "title": "Eli Lilly's Weight Loss Drug Shows Strong Sales Growth",
            "summary": "Eli Lilly reported quarterly earnings with significant revenue increase from GLP-1 drugs."
        }
    ]
    
    for news in test_news:
        print(f"测试: {news['ticker']} - {news['title'][:50]}...")
        
        result = await client.classify_news(
            title=news["title"],
            summary=news["summary"],
            ticker=news["ticker"]
        )
        
        if result:
            print(f"  ✅ 分类成功")
            print(f"     有效事件: {result.is_valid_event}")
            print(f"     事件类型: {result.event_type}")
            print(f"     方向偏好: {result.direction_bias}")
        else:
            print(f"  ❌ 分类失败")
        print()

if __name__ == "__main__":
    asyncio.run(test_deepseek())
