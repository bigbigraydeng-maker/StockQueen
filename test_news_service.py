#!/usr/bin/env python3
"""
Test script for news analysis module
"""

import asyncio
from app.services.news_service import run_news_fetcher

async def test_news_analysis():
    print("Testing news analysis module...")
    
    # Run news fetcher
    results = await run_news_fetcher()
    
    print("\nNews analysis results:")
    print(f"Total fetched: {results['total_fetched']}")
    print(f"Total filtered: {results['total_filtered']}")
    print(f"Total stored: {results['total_stored']}")
    
    if results['errors']:
        print("\nErrors:")
        for error in results['errors']:
            print(f"- {error}")
    else:
        print("\nNo errors occurred.")

if __name__ == "__main__":
    asyncio.run(test_news_analysis())
