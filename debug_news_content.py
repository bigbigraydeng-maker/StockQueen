#!/usr/bin/env python3
"""
Debug script to check news content and ticker extraction
"""

import asyncio
from app.services.news_service import NewsService
from app.services.db_service import EventService

async def main():
    """Main function"""
    print("=" * 60)
    print("Debug News Content and Ticker Extraction")
    print("=" * 60)
    
    # Fetch news
    service = NewsService()
    result = await service.fetch_and_process_all()
    
    print(f"\nNews fetch result: {result}")
    
    # Get stored events from database
    db_service = EventService()
    events = await db_service.get_all_events(limit=10)
    
    print(f"\nStored events in database: {len(events)}")
    
    for i, event in enumerate(events, 1):
        print(f"\n{'=' * 60}")
        print(f"Event {i}")
        print(f"{'=' * 60}")
        print(f"Title: {event.title}")
        print(f"Source: {event.source}")
        print(f"Ticker: {event.ticker}")
        print(f"URL: {event.url}")
        print(f"Published: {event.published_at}")
        
        if event.summary:
            print(f"Summary: {event.summary[:200]}...")
        
        # Test ticker extraction
        ticker = service.ticker_extractor.extract_ticker(event.title, event.summary or "")
        print(f"Extracted ticker: {ticker}")
    
    print("\n" + "=" * 60)
    print("Debug completed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
