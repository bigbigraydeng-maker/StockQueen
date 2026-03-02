#!/usr/bin/env python3
"""
测试新闻抓取 - 查看实际内容
"""

import asyncio
import feedparser
import httpx

async def test_news_fetch():
    """测试新闻抓取"""
    
    feeds = [
        "https://www.biopharmadive.com/feeds/news/",
        "https://www.statnews.com/feed/",
        "https://www.fiercepharma.com/rss/xml",
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    keywords = [
        "phase 2", "phase 3", "phase2", "phase3", "topline",
        "fda approval", "crl", "clinical trial result",
        "endpoint", "complete response letter",
    ]
    
    print("=" * 80)
    print("新闻抓取测试 - 查看实际内容")
    print("=" * 80)
    print()
    
    for feed_url in feeds:
        print(f"抓取: {feed_url}")
        print("-" * 80)
        
        try:
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                response = await client.get(feed_url, follow_redirects=True)
                feed = feedparser.parse(response.text)
            
            print(f"抓取到 {len(feed.entries)} 条新闻")
            print()
            
            # 显示前5条新闻
            for i, entry in enumerate(feed.entries[:5]):
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))[:200]
                
                # 检查关键词匹配
                text = (title + " " + summary).lower()
                matched_keywords = [kw for kw in keywords if kw in text]
                
                print(f"{i+1}. {title[:80]}")
                print(f"   摘要: {summary[:100]}...")
                if matched_keywords:
                    print(f"   ✅ 匹配关键词: {matched_keywords}")
                else:
                    print(f"   ❌ 无匹配关键词")
                print()
                
        except Exception as e:
            print(f"❌ 错误: {e}")
        
        print()

if __name__ == "__main__":
    asyncio.run(test_news_fetch())
