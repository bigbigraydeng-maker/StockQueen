#!/usr/bin/env python3
"""
Check stored events in database
"""

import asyncio
from app.services.db_service import EventService

async def main():
    """Main function"""
    print("=" * 60)
    print("Checking Stored Events")
    print("=" * 60)
    
    db_service = EventService()
    
    # Get pending events
    pending_events = await db_service.get_pending_events()
    print(f"\nPending events: {len(pending_events)}")
    
    for i, event in enumerate(pending_events, 1):
        print(f"\n{'=' * 60}")
        print(f"Event {i}")
        print(f"{'=' * 60}")
        print(f"Title: {event.title}")
        print(f"Ticker: {event.ticker}")
        print(f"Source: {event.source}")
        print(f"URL: {event.url}")
        print(f"Status: {event.status}")
        
        if event.summary:
            print(f"Summary: {event.summary[:200]}...")

if __name__ == "__main__":
    asyncio.run(main())
