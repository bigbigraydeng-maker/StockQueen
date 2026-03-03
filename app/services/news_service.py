"""
StockQueen V1 - News Service
RSS feed fetching and keyword filtering
"""

import feedparser
import httpx
import logging
import re
from typing import List, Optional
from datetime import datetime
from dateutil import parser as date_parser

from app.config import settings, KeywordConfig
from app.config.pharma_watchlist import PHARMA_WATCHLIST, PHARMA_KEYWORDS
from app.config.geopolitical_watchlist import (
    GEOPOLITICAL_ALL_WATCHLIST,
    GEOPOLITICAL_KEYWORDS,
)
from app.models import NewsEventCreate
from app.services.db_service import EventService

logger = logging.getLogger(__name__)


class RSSFetcher:
    """RSS feed fetcher with retry logic"""
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.timeout = 30.0
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
    
    async def fetch_feed(self, url: str) -> Optional[dict]:
        """Fetch RSS feed with retry logic"""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Fetching RSS feed: {url} (attempt {attempt + 1}/{self.max_retries})")
                
                # Use httpx for async HTTP requests
                async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
                    response = await client.get(url, follow_redirects=True)
                    response.raise_for_status()
                    
                    # Parse RSS feed
                    feed = feedparser.parse(response.text)
                    
                    if feed.entries:
                        logger.info(f"Fetched {len(feed.entries)} entries from {url}")
                        return feed
                    else:
                        logger.warning(f"No entries found in feed: {url}")
                        return None
                        
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching {url}: {e.response.status_code}")
                if attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    return None
                    
            except httpx.RequestError as e:
                logger.error(f"Request error fetching {url}: {e}")
                if attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    return None
                    
            except Exception as e:
                logger.error(f"Unexpected error fetching {url}: {e}")
                return None
        
        return None
    
    async def _exponential_backoff(self, attempt: int):
        """Exponential backoff between retries"""
        import asyncio
        wait_time = 2 ** attempt  # 1, 2, 4 seconds
        logger.info(f"Retrying in {wait_time} seconds...")
        await asyncio.sleep(wait_time)


class KeywordFilter:
    """Keyword-based news filter with priority for pharma watchlist"""
    
    EXCLUDE_KEYWORDS = [
        "convertible note",
        "public offering",
        "private placement",
        "at-the-market",
        "ATM offering",
        "shelf registration",
        "equity offering",
        "underwritten offering",
        "common stock offering",
        "share offering",
        "priced offering",
        "sec filing",
        "form s-",
        "form s-1",
        "form s-3",
        "prospectus",
    ]
    
    def __init__(self):
        self.keywords = [kw.lower() for kw in KeywordConfig.KEYWORDS]
        self.geo_keywords = [kw.lower() for kw in KeywordConfig.GEO_KEYWORDS]
        logger.info(f"Keyword filter initialized with {len(self.keywords)} pharma + {len(self.geo_keywords)} geo keywords")
        logger.info(f"Excluded {len(self.EXCLUDE_KEYWORDS)} financing keywords")
    
    def is_financing_event(self, title: str, summary: str = "") -> bool:
        """Check if news is a financing event (should be excluded)"""
        text = (title + " " + summary).lower()
        
        for kw in self.EXCLUDE_KEYWORDS:
            if kw.lower() in text:
                logger.info(f"Financing event excluded: '{kw}' found in '{title[:50]}...'")
                return True
        
        return False
    
    def filter_news(self, title: str, summary: str = "") -> bool:
        """
        Check if news matches pharma watchlist first, then keywords
        Returns True if match found
        """
        if self.is_financing_event(title, summary):
            return False
        
        text = f"{title} {summary}".upper()
        
        for ticker, name in PHARMA_WATCHLIST.items():
            if ticker in text or name.upper() in text:
                logger.debug(f"Watchlist match: {ticker} ({name}) in '{title[:50]}...'")
                return True
        
        for keyword, ticker in PHARMA_KEYWORDS.items():
            if keyword.upper() in text:
                logger.debug(f"Keyword match: '{keyword}' in '{title[:50]}...'")
                return True
        
        text_lower = text.lower()
        for keyword in self.keywords:
            if keyword in text_lower:
                logger.debug(f"General keyword match: '{keyword}' in '{title[:50]}...'")
                return True

        # Geopolitical watchlist match
        for ticker, name in GEOPOLITICAL_ALL_WATCHLIST.items():
            if ticker in text or name.upper() in text:
                logger.debug(f"Geo watchlist match: {ticker} ({name}) in '{title[:50]}...'")
                return True

        # Geopolitical keyword match
        for keyword, ticker in GEOPOLITICAL_KEYWORDS.items():
            if keyword.upper() in text:
                logger.debug(f"Geo keyword match: '{keyword}' in '{title[:50]}...'")
                return True

        # Geopolitical general keywords
        for keyword in self.geo_keywords:
            if keyword in text_lower:
                logger.debug(f"Geo general keyword match: '{keyword}' in '{title[:50]}...'")
                return True

        return False
    
    def get_matching_keywords(self, title: str, summary: str = "") -> List[str]:
        """Get list of matching keywords"""
        text = f"{title} {summary}".upper()
        matches = []
        
        # Check watchlist matches
        for ticker, name in PHARMA_WATCHLIST.items():
            if ticker in text or name.upper() in text:
                matches.append(f"watchlist:{ticker}")
        
        # Check pharma keyword matches
        for keyword, ticker in PHARMA_KEYWORDS.items():
            if keyword.upper() in text:
                matches.append(f"pharma_keyword:{keyword}")
        
        # Check general keyword matches
        text_lower = text.lower()
        for keyword in self.keywords:
            if keyword in text_lower:
                matches.append(f"general:{keyword}")
        
        return matches


def extract_ticker_from_news(title: str, content: str) -> str | None:
    """
    Extract ticker from news using pharma watchlist
    """
    text = (title + " " + content).upper()
    
    # Priority 1: Direct ticker match (e.g., $MRNA or (MRNA))
    direct = re.findall(r'\$([A-Z]{2,5})\b|\(([A-Z]{2,5})\)', text)
    for match in direct:
        ticker = match[0] or match[1]
        if ticker in PHARMA_WATCHLIST:
            logger.info(f"Found ticker via direct match: {ticker}")
            return ticker
        if ticker in GEOPOLITICAL_ALL_WATCHLIST:
            logger.info(f"Found geo ticker via direct match: {ticker}")
            return ticker

    # Priority 2: Keyword match (pharma)
    for keyword, ticker in PHARMA_KEYWORDS.items():
        if keyword.upper() in text:
            logger.info(f"Found ticker via keyword '{keyword}': {ticker}")
            return ticker

    # Priority 2b: Keyword match (geopolitical)
    for keyword, ticker in GEOPOLITICAL_KEYWORDS.items():
        if ticker.startswith("_"):
            continue  # Skip meta-event markers
        if keyword.upper() in text:
            logger.info(f"Found geo ticker via keyword '{keyword}': {ticker}")
            return ticker

    # Priority 3: Company name match
    for ticker, name in PHARMA_WATCHLIST.items():
        if name.upper() in text:
            logger.info(f"Found ticker via company name '{name}': {ticker}")
            return ticker

    for ticker, name in GEOPOLITICAL_ALL_WATCHLIST.items():
        if name.upper() in text:
            logger.info(f"Found geo ticker via company name '{name}': {ticker}")
            return ticker

    return None


class TickerExtractor:
    """Extract stock ticker from news text"""
    
    def extract_ticker(self, title: str, summary: str = "") -> Optional[str]:
        """
        Extract stock ticker from news text using pharma watchlist
        """
        return extract_ticker_from_news(title, summary)


class NewsService:
    """Main news service orchestrating fetch, filter, and storage"""
    
    def __init__(self):
        self.fetcher = RSSFetcher()
        self.filter = KeywordFilter()
        self.ticker_extractor = TickerExtractor()
        self.db_service = EventService()
    
    async def fetch_and_process_all(self) -> dict:
        """
        Fetch and process all configured RSS feeds
        Returns summary of processed news
        """
        results = {
            "total_fetched": 0,
            "total_filtered": 0,
            "total_stored": 0,
            "errors": []
        }
        
        # Define feeds
        feeds = [
            # Pharma specific
            {
                "url": "https://www.biopharmadive.com/feeds/news/",
                "source": "biopharmadive"
            },
            {
                "url": "https://www.statnews.com/feed/",
                "source": "statnews"
            },
            {
                "url": "https://www.fiercepharma.com/rss/xml",
                "source": "fiercepharma"
            },
            # FDA official (keep but lower priority)
            {
                "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
                "source": "fda_press"
            },
            # === Geopolitical / Energy / Commodities ===
            {
                "url": "https://www.ogj.com/rss",
                "source": "oil_gas_journal"
            },
            {
                "url": "https://oilprice.com/rss/main",
                "source": "oilprice"
            },
            {
                "url": "https://feeds.reuters.com/reuters/businessNews",
                "source": "reuters_business"
            },
        ]
        
        for feed_config in feeds:
            try:
                feed_results = await self._process_feed(
                    feed_config["url"],
                    feed_config["source"]
                )
                results["total_fetched"] += feed_results["fetched"]
                results["total_filtered"] += feed_results["filtered"]
                results["total_stored"] += feed_results["stored"]
                
            except Exception as e:
                error_msg = f"Error processing {feed_config['source']}: {str(e)}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        logger.info(
            f"News processing complete: {results['total_stored']} new events stored"
        )
        return results
    
    async def _process_feed(self, url: str, source: str) -> dict:
        """Process a single RSS feed"""
        results = {"fetched": 0, "filtered": 0, "stored": 0}
        
        # Fetch feed
        feed = await self.fetcher.fetch_feed(url)
        if not feed:
            return results
        
        results["fetched"] = len(feed.entries)
        
        # Process each entry
        for entry in feed.entries:
            try:
                # Check for duplicates
                existing = await self.db_service.get_event_by_url(entry.link)
                if existing:
                    logger.debug(f"Duplicate news skipped: {entry.title[:50]}...")
                    continue
                
                # Extract data
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                published = self._parse_date(entry.get("published", entry.get("updated")))
                
                # Keyword filter
                if not self.filter.filter_news(title, summary):
                    continue
                
                results["filtered"] += 1
                
                # Extract ticker
                ticker = self.ticker_extractor.extract_ticker(title, summary)
                
                # Create event
                event = NewsEventCreate(
                    title=title,
                    summary=summary[:500] if summary else None,  # Limit summary length
                    url=entry.link,
                    source=source,
                    published_at=published or datetime.utcnow(),
                    ticker=ticker
                )
                
                # Store in database
                stored = await self.db_service.create_event(event)
                if stored:
                    results["stored"] += 1
                    logger.info(f"Stored event: {title[:60]}... (ticker: {ticker})")
                
            except Exception as e:
                logger.error(f"Error processing entry: {e}")
                continue
        
        return results
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string to datetime"""
        if not date_str:
            return None
        
        try:
            return date_parser.parse(date_str)
        except Exception as e:
            logger.warning(f"Could not parse date: {date_str}, error: {e}")
            return None


# Convenience function for scheduled tasks
async def run_news_fetcher() -> dict:
    """Run news fetcher (for scheduled execution)"""
    service = NewsService()
    return await service.fetch_and_process_all()
