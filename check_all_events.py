#!/usr/bin/env python3
"""
Check all events in database
"""

import asyncio
from app.database import get_db

async def main():
    """Main function"""
    print("=" * 60)
    print("Checking All Events")
    print("=" * 60)
    
    db = get_db()
    
    # Get all events
    result = db.table("events").select("*").order("created_at", desc=True).limit(10).execute()
    
    if result.data:
        print(f"\nTotal events: {len(result.data)}")
        
        for i, event in enumerate(result.data, 1):
            print(f"\n{'=' * 60}")
            print(f"Event {i}")
            print(f"{'=' * 60}")
            print(f"Title: {event.get('title', 'N/A')}")
            print(f"Ticker: {event.get('ticker', 'N/A')}")
            print(f"Source: {event.get('source', 'N/A')}")
            print(f"Status: {event.get('status', 'N/A')}")
            print(f"URL: {event.get('url', 'N/A')}")
            
            if event.get('summary'):
                summary = event['summary'][:200]
                print(f"Summary: {summary}...")
    else:
        print("No events found in database")

if __name__ == "__main__":
    asyncio.run(main())
