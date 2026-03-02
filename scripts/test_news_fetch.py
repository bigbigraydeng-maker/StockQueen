"""
StockQueen V1 - News Fetch Test Script
Test RSS news fetching functionality
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.news_service import NewsService
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_news_fetch():
    """Test news fetching"""
    print("\n" + "=" * 60)
    print("  Testing News Fetch Service")
    print("=" * 60)
    
    service = NewsService()
    
    print("\n1. Fetching and processing RSS feeds...")
    results = await service.fetch_and_process_all()
    
    print(f"\n2. Results:")
    print(f"   Total fetched: {results['total_fetched']}")
    print(f"   Total filtered: {results['total_filtered']}")
    print(f"   Total stored: {results['total_stored']}")
    
    if results['errors']:
        print(f"\n3. Errors ({len(results['errors'])}):")
        for error in results['errors']:
            print(f"   - {error}")
    else:
        print("\n3. No errors!")
    
    print("\n" + "=" * 60)
    
    return results['total_stored'] > 0 or results['total_fetched'] > 0


if __name__ == "__main__":
    try:
        success = asyncio.run(test_news_fetch())
        print(f"\n{'✅' if success else '❌'} Test {'passed' if success else 'failed'}")
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
