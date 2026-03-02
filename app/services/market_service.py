"""
StockQueen V1 - Market Data Service
Tiger Open API integration with yfinance fallback
"""

import httpx
import logging
import yfinance as yf
import pandas as pd
from typing import Optional, List
from datetime import datetime

from app.config import settings, RiskConfig
from app.models import MarketSnapshotCreate
from app.services.db_service import AIEventService, MarketDataService

logger = logging.getLogger(__name__)


class TigerAPIClient:
    """Tiger Open API client"""
    
    def __init__(self):
        self.access_token = settings.tiger_access_token
        self.tiger_id = settings.tiger_tiger_id
        self.account = settings.tiger_account
        self.base_url = settings.tiger_base_url
        self.timeout = 30.0
        self.max_retries = 3
    
    async def get_stock_quote(self, ticker: str) -> Optional[dict]:
        """Get stock quote from Tiger API"""
        # Note: This is a simplified implementation
        # Actual Tiger API implementation requires specific SDK or API endpoints
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "ticker": ticker,
            "account": self.account
        }
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Fetching quote for {ticker} from Tiger API")
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    # Note: Replace with actual Tiger API endpoint
                    # This is a placeholder implementation
                    response = await client.post(
                        f"{self.base_url}/v1/quote",
                        headers=headers,
                        json=payload
                    )
                    response.raise_for_status()
                    
                    data = response.json()
                    logger.info(f"Successfully fetched quote for {ticker}")
                    return data
                    
            except httpx.HTTPStatusError as e:
                logger.error(f"Tiger API HTTP error: {e.response.status_code}")
                if attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    return None
                    
            except Exception as e:
                logger.error(f"Error fetching quote: {e}")
                if attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    return None
        
        return None
    
    async def _exponential_backoff(self, attempt: int):
        """Exponential backoff"""
        import asyncio
        wait_time = 2 ** attempt
        await asyncio.sleep(wait_time)


class YahooFinanceClient:
    """Yahoo Finance client using yfinance (fallback data source)"""
    
    def __init__(self):
        self.timeout = 30.0
    
    async def get_stock_quote(self, ticker: str) -> Optional[dict]:
        """
        Get stock quote from Yahoo Finance
        Returns dict with quote data, or None if failed
        """
        try:
            logger.info(f"Fetching quote for {ticker} from Yahoo Finance")
            
            # Use yfinance synchronously, wrapped in async executor
            import asyncio
            loop = asyncio.get_event_loop()
            
            quote = await loop.run_in_executor(
                None,
                self._fetch_yahoo_data,
                ticker
            )
            
            if quote:
                logger.info(f"Successfully fetched quote for {ticker} from Yahoo Finance")
                return quote
            else:
                logger.warning(f"No data returned for {ticker} from Yahoo Finance")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching from Yahoo Finance for {ticker}: {e}")
            return None
    
    async def get_premarket_data(self, ticker: str) -> Optional[dict]:
        """
        Get premarket data from Yahoo Finance
        Returns dict with premarket price and change, or None if not available
        """
        try:
            logger.info(f"Fetching premarket data for {ticker}")
            
            import asyncio
            loop = asyncio.get_event_loop()
            
            premarket = await loop.run_in_executor(
                None,
                self._fetch_premarket_data,
                ticker
            )
            
            if premarket:
                logger.info(f"Premarket data for {ticker}: {premarket}")
                return premarket
            else:
                logger.warning(f"No premarket data available for {ticker}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching premarket data for {ticker}: {e}")
            return None
    
    def _fetch_yahoo_data(self, ticker: str) -> Optional[dict]:
        """
        Synchronous Yahoo Finance data fetching
        """
        try:
            # Get ticker object
            stock = yf.Ticker(ticker)
            
            # Get current info
            info = stock.info
            
            # Get latest price data
            hist = stock.history(period="5d")
            
            if hist.empty:
                logger.warning(f"No historical data for {ticker}")
                return None
            
            latest = hist.iloc[-1]
            prev = hist.iloc[-2] if len(hist) > 1 else latest
            
            # Calculate change percentage
            if len(hist) > 1:
                day_change_pct = (latest['Close'] - prev['Close']) / prev['Close']
            else:
                day_change_pct = 0.0
            
            # Get 30-day average volume
            avg_volume_30d = int(hist['Volume'].mean())
            
            quote_data = {
                "ticker": ticker,
                "prev_close": float(prev['Close']),
                "open": float(latest['Open']),
                "high": float(latest['High']),
                "low": float(latest['Low']),
                "latest_price": float(latest['Close']),
                "change_percent": day_change_pct * 100,
                "volume": int(latest['Volume']),
                "avg_volume_30d": avg_volume_30d,
                "market_cap": float(info.get('marketCap', 0)),
                "data_source": "yahoo_finance"
            }
            
            return quote_data
            
        except Exception as e:
            logger.error(f"Error in Yahoo Finance data fetch: {e}")
            return None
    
    def _fetch_premarket_data(self, ticker: str) -> Optional[dict]:
        """
        Synchronous premarket data fetching from Yahoo Finance
        Uses stock.info to get premarket price if available
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Try to get premarket price from info
            premarket_price = info.get('preMarketPrice')
            previous_close = info.get('previousClose')
            
            if premarket_price and previous_close:
                premarket_change_pct = (premarket_price - previous_close) / previous_close
                
                return {
                    "ticker": ticker,
                    "premarket_price": float(premarket_price),
                    "previous_close": float(previous_close),
                    "premarket_change_pct": round(premarket_change_pct * 100, 2),
                    "has_premarket": True
                }
            else:
                # No premarket data available (market is open or no premarket trading)
                return {
                    "ticker": ticker,
                    "has_premarket": False,
                    "message": "No premarket data available"
                }
                
        except Exception as e:
            logger.error(f"Error fetching premarket data: {e}")
            return None


class MarketDataFetcher:
    """Market data service with Tiger API primary and Yahoo Finance fallback"""
    
    def __init__(self):
        self.tiger_client = TigerAPIClient()
        self.yahoo_client = YahooFinanceClient()
        self.ai_service = AIEventService()
        self.db_service = MarketDataService()
    
    async def fetch_market_data_for_valid_events(self) -> dict:
        """Fetch market data for all valid AI events with fallback"""
        results = {
            "total_valid_events": 0,
            "total_fetched": 0,
            "tiger_success": 0,
            "yahoo_fallback": 0,
            "errors": []
        }
        
        # Get valid events
        valid_events = await self.ai_service.get_valid_events()
        results["total_valid_events"] = len(valid_events)
        
        logger.info(f"Fetching market data for {len(valid_events)} valid events")
        
        for event in valid_events:
            try:
                if not event.ticker:
                    logger.warning(f"Event {event.id} has no ticker, skipping")
                    continue
                
                # Try Tiger API first
                quote = await self.tiger_client.get_stock_quote(event.ticker)
                data_source = "tiger"
                
                # Fallback to Yahoo Finance if Tiger API fails
                if not quote:
                    logger.warning(f"Tiger API failed for {event.ticker}, falling back to Yahoo Finance")
                    quote = await self.yahoo_client.get_stock_quote(event.ticker)
                    data_source = "yahoo"
                
                if quote:
                    # Parse and store snapshot
                    snapshot = self._parse_quote_to_snapshot(event, quote)
                    
                    if snapshot:
                        stored = await self.db_service.create_snapshot(snapshot)
                        if stored:
                            results["total_fetched"] += 1
                            if data_source == "tiger":
                                results["tiger_success"] += 1
                            else:
                                results["yahoo_fallback"] += 1
                            logger.info(f"Stored market snapshot for {event.ticker} (source: {data_source})")
                else:
                    results["errors"].append(f"Failed to fetch quote for {event.ticker} from all sources")
                    
            except Exception as e:
                logger.error(f"Error fetching market data for {event.ticker}: {e}")
                results["errors"].append(f"Error for {event.ticker}: {str(e)}")
        
        return results
    
    def _parse_quote_to_snapshot(
        self,
        event,
        quote: dict
    ) -> Optional[MarketSnapshotCreate]:
        """Parse Tiger API quote to market snapshot"""
        try:
            # Note: Adjust field names based on actual Tiger API response
            return MarketSnapshotCreate(
                ticker=event.ticker,
                event_id=event.id,
                prev_close=float(quote.get("prev_close", 0)),
                day_open=float(quote.get("open", 0)),
                day_high=float(quote.get("high", 0)),
                day_low=float(quote.get("low", 0)),
                current_price=float(quote.get("latest_price", 0)),
                day_change_pct=float(quote.get("change_percent", 0)) / 100,
                volume=int(quote.get("volume", 0)),
                avg_volume_30d=int(quote.get("avg_volume_30d", 0)),
                market_cap=float(quote.get("market_cap", 0))
            )
        except Exception as e:
            logger.error(f"Error parsing quote: {e}")
            return None


# Convenience function
async def run_market_data_fetch() -> dict:
    """Run market data fetch (for scheduled execution)"""
    service = MarketDataFetcher()
    return await service.fetch_market_data_for_valid_events()
