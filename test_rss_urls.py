#!/usr/bin/env python3
"""
Test script to verify RSS URL accessibility
"""

import httpx
import feedparser
import asyncio

async def test_rss_url(url: str, source: str):
    """Test a single RSS URL"""
    print(f"\nTesting {source}: {url}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            print(f"  Status Code: {response.status_code}")
            
            if response.status_code == 200:
                # Try to parse RSS
                feed = feedparser.parse(response.text)
                print(f"  Feed Title: {feed.feed.get('title', 'N/A')}")
                print(f"  Entries: {len(feed.entries)}")
                
                if feed.entries:
                    print(f"  Latest Entry: {feed.entries[0].get('title', 'N/A')[:50]}...")
                    return True
                else:
                    print(f"  ⚠️  No entries found")
                    return False
            else:
                print(f"  ❌ Failed to fetch (status: {response.status_code})")
                return False
                
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

async def main():
    """Test all RSS URLs"""
    print("=" * 60)
    print("RSS URL Accessibility Test")
    print("=" * 60)
    
    urls = [
        ("https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", "FDA Press Releases"),
        ("https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml", "FDA Drugs"),
        ("https://www.biopharmadive.com/feeds/news/", "BioPharma Dive"),
    ]
    
    results = []
    for url, source in urls:
        success = await test_rss_url(url, source)
        results.append((source, success))
    
    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    
    for source, success in results:
        status = "✅ Working" if success else "❌ Failed"
        print(f"{source}: {status}")

if __name__ == "__main__":
    asyncio.run(main())
