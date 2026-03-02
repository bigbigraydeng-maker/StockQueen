#!/usr/bin/env python3
"""
Simple debug script to check news content
"""

import asyncio
import feedparser
import httpx

async def main():
    """Main function"""
    print("=" * 60)
    print("Checking RSS Feed Content")
    print("=" * 60)
    
    # Test FDA RSS feed
    url = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            
            feed = feedparser.parse(response.text)
            
            print(f"Total entries: {len(feed.entries)}")
            
            # Show first 5 entries
            for i, entry in enumerate(feed.entries[:5], 1):
                print(f"\n{'=' * 60}")
                print(f"Entry {i}")
                print(f"{'=' * 60}")
                print(f"Title: {entry.title}")
                print(f"Link: {entry.link}")
                
                if entry.get("summary"):
                    summary = entry.summary[:200]
                    print(f"Summary: {summary}...")
                
                # Check for ticker patterns
                text = f"{entry.title} {entry.get('summary', '')}"
                
                # Pattern 1: Exchange:Ticker format
                import re
                patterns = [
                    r'\(NASDAQ:\s*([A-Z]{1,5})\)',
                    r'\(NYSE:\s*([A-Z]{1,5})\)',
                    r'NASDAQ:\s*([A-Z]{1,5})',
                    r'NYSE:\s*([A-Z]{1,5})',
                ]
                
                found_ticker = False
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        ticker = match.group(1).upper()
                        print(f"Found ticker (pattern 1): {ticker}")
                        found_ticker = True
                        break
                
                # Pattern 2: Ticker in parentheses
                if not found_ticker:
                    match = re.search(r'\(([A-Z]{1,5})\)', text)
                    if match:
                        ticker = match.group(1)
                        print(f"Found ticker (pattern 2): {ticker}")
                        found_ticker = True
                
                if not found_ticker:
                    print("No ticker found in this entry")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Debug completed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
