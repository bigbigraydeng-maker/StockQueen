#!/usr/bin/env python3
"""
Debug script to check Fierce Pharma news
"""

import asyncio
import feedparser
import httpx
from app.config import KeywordConfig
from app.config.pharma_watchlist import PHARMA_WATCHLIST, PHARMA_KEYWORDS

async def main():
    """Main function"""
    print("=" * 60)
    print("Debug Fierce Pharma News")
    print("=" * 60)
    
    # Test Fierce Pharma feed
    url = "https://www.fiercepharma.com/rss/xml"
    print(f"\nTesting feed: {url}")
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            
            feed = feedparser.parse(response.text)
            
            print(f"Fetched {len(feed.entries)} entries")
            
            # Show first 5 entries
            for i, entry in enumerate(feed.entries[:5], 1):
                print(f"\n{'=' * 60}")
                print(f"Entry {i}")
                print(f"{'=' * 60}")
                print(f"Title: {entry.title}")
                
                if entry.get("description"):
                    description = entry.description[:200]
                    print(f"Description: {description}...")
                
                # Check keyword match
                title = entry.title
                description = entry.get("description", "")
                text = f"{title} {description}".lower()
                
                matched_keywords = []
                for keyword in KeywordConfig.KEYWORDS:
                    if keyword.lower() in text:
                        matched_keywords.append(keyword)
                
                if matched_keywords:
                    print(f"✅ Keywords matched: {matched_keywords}")
                else:
                    print(f"❌ No keywords matched")
                
                # Check ticker extraction
                import re
                text_upper = f"{title} {description}".upper()
                
                # Direct ticker match
                direct = re.findall(r'\$([A-Z]{2,5})\b|\(([A-Z]{2,5})\)', text_upper)
                if direct:
                    print(f"Found direct ticker patterns: {direct}")
                
                # Keyword match
                for keyword, ticker in PHARMA_KEYWORDS.items():
                    if keyword.upper() in text_upper:
                        print(f"✅ Found ticker via keyword '{keyword}': {ticker}")
                        break
                else:
                    # Company name match
                    for ticker, name in PHARMA_WATCHLIST.items():
                        if name.upper() in text_upper:
                            print(f"✅ Found ticker via company name '{name}': {ticker}")
                            break
                    else:
                        print(f"❌ No ticker found")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Debug completed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
