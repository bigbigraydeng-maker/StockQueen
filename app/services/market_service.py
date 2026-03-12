"""
StockQueen V2.3 - Market Data Service
Tiger Open API (official SDK) with Alpha Vantage fallback
"""

import asyncio
import logging
import os
import tempfile
import pandas as pd
from typing import Optional, List
from datetime import datetime

from app.config import settings, RiskConfig
from app.models import MarketSnapshotCreate
from app.services.db_service import AIEventService, MarketDataService
from app.services.alphavantage_client import get_av_client

logger = logging.getLogger(__name__)


class TigerPermissionError(Exception):
    """Raised when Tiger API returns permission denied - should not retry"""
    pass


class TigerAPIClient:
    """Tiger Open API client using official tigeropen SDK"""

    def __init__(self):
        self.tiger_id = settings.tiger_id
        self.account = settings.tiger_account
        self.private_key_str = settings.tiger_private_key
        self.max_retries = 3
        self._quote_client = None
        self._pk_file = None
        self._permission_denied = False  # Cache permission denied state

    def _get_quote_client(self):
        """Lazy-init the QuoteClient (synchronous, call inside executor)"""
        if self._quote_client is not None:
            return self._quote_client

        if not self.tiger_id or not self.private_key_str or not self.account:
            logger.warning("Tiger API credentials not configured, skipping")
            return None

        try:
            from tigeropen.tiger_open_config import TigerOpenClientConfig
            from tigeropen.common.util.signature_utils import read_private_key
            from tigeropen.common.consts import Language
            from tigeropen.quote.quote_client import QuoteClient

            # Write private key to a temp file (SDK reads from file path)
            self._pk_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.pem', delete=False
            )
            self._pk_file.write(self.private_key_str)
            self._pk_file.close()

            client_config = TigerOpenClientConfig()
            client_config.private_key = read_private_key(self._pk_file.name)
            client_config.tiger_id = self.tiger_id
            client_config.account = self.account
            client_config.language = Language.en_US

            self._quote_client = QuoteClient(client_config)
            logger.info("Tiger QuoteClient initialized successfully")
            return self._quote_client

        except Exception as e:
            logger.error(f"Failed to initialize Tiger QuoteClient: {e}")
            return None

    def _fetch_stock_brief(self, ticker: str) -> Optional[dict]:
        """Synchronous: fetch stock brief via Tiger SDK"""
        try:
            client = self._get_quote_client()
            if client is None:
                return None

            briefs = client.get_stock_briefs([ticker], include_hour_trading=True)

            if briefs is None or briefs.empty:
                logger.warning(f"No Tiger data returned for {ticker}")
                return None

            row = briefs.iloc[0]

            pre_close = float(row.get('pre_close', 0))
            latest_price = float(row.get('latest_price', 0))
            change_percent = ((latest_price - pre_close) / pre_close * 100) if pre_close else 0.0

            return {
                "ticker": ticker,
                "prev_close": pre_close,
                "open": float(row.get('open', 0)),
                "high": float(row.get('high', 0)),
                "low": float(row.get('low', 0)),
                "latest_price": latest_price,
                "change_percent": change_percent,
                "volume": int(row.get('volume', 0)),
                "avg_volume_30d": 0,  # not available in briefs, will be supplemented
                "market_cap": 0,      # not available in briefs
                "data_source": "tiger"
            }

        except Exception as e:
            error_msg = str(e).lower()
            if 'permission denied' in error_msg or 'do not have permissions' in error_msg:
                raise TigerPermissionError(f"Tiger API permission denied for {ticker}: {e}")
            logger.error(f"Tiger SDK error for {ticker}: {e}")
            return None

    async def get_stock_quote(self, ticker: str) -> Optional[dict]:
        """Get stock quote from Tiger API with retry (skips on permission denied)"""
        # If we already know permission is denied, skip immediately
        if self._permission_denied:
            logger.info(f"Skipping Tiger API for {ticker} (permission denied cached)")
            return None

        for attempt in range(self.max_retries):
            try:
                logger.info(f"Fetching quote for {ticker} from Tiger API (attempt {attempt + 1}/{self.max_retries})")

                loop = asyncio.get_event_loop()
                quote = await loop.run_in_executor(
                    None, self._fetch_stock_brief, ticker
                )

                if quote:
                    logger.info(f"Successfully fetched quote for {ticker} from Tiger API")
                    return quote
                else:
                    logger.warning(f"No data for {ticker} from Tiger API (attempt {attempt + 1})")

            except TigerPermissionError as e:
                logger.warning(f"Tiger API permission denied - skipping all further Tiger requests: {e}")
                self._permission_denied = True
                return None

            except Exception as e:
                logger.error(f"Tiger API error for {ticker} (attempt {attempt + 1}): {e}")

            if attempt < self.max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying Tiger API for {ticker} in {wait_time}s...")
                await asyncio.sleep(wait_time)

        logger.error(f"All {self.max_retries} Tiger API attempts failed for {ticker}")
        return None

    def __del__(self):
        """Cleanup temp private key file"""
        if self._pk_file and os.path.exists(self._pk_file.name):
            try:
                os.unlink(self._pk_file.name)
            except Exception:
                pass


class AlphaVantageFinanceClient:
    """Alpha Vantage client — replaces YahooFinanceClient"""

    def __init__(self):
        self._av = get_av_client()

    async def batch_get_stock_quotes(self, tickers: list) -> dict:
        """Get quotes for multiple tickers via Alpha Vantage."""
        if not tickers:
            return {}
        return await self._av.batch_get_quotes(tickers)

    async def get_stock_quote(self, ticker: str) -> Optional[dict]:
        """Get single stock quote."""
        return await self._av.get_quote(ticker)

    async def get_premarket_data(self, ticker: str) -> Optional[dict]:
        """Get latest data (Alpha Vantage doesn't have premarket, returns latest)."""
        quote = await self._av.get_quote(ticker)
        if quote:
            return {
                "ticker": ticker,
                "premarket_price": quote["latest_price"],
                "previous_close": quote["prev_close"],
                "premarket_change_pct": quote["change_percent"],
                "has_premarket": False,
            }
        return None


class MarketDataFetcher:
    """Market data service with Tiger API primary and Alpha Vantage fallback"""

    def __init__(self):
        self.tiger_client = TigerAPIClient()
        self.av_client = AlphaVantageFinanceClient()
        self.ai_service = AIEventService()
        self.db_service = MarketDataService()
    
    async def fetch_market_data_for_valid_events(self) -> dict:
        """Fetch market data for all valid AI events with Tiger primary + Yahoo batch fallback"""
        results = {
            "total_valid_events": 0,
            "total_fetched": 0,
            "tiger_success": 0,
            "av_fallback": 0,
            "errors": []
        }

        # Get valid events
        valid_events = await self.ai_service.get_valid_events()
        results["total_valid_events"] = len(valid_events)

        logger.info(f"Fetching market data for {len(valid_events)} valid events")

        # Collect events with tickers
        ticker_events = []
        for event in valid_events:
            if not event.ticker:
                logger.warning(f"Event {event.id} has no ticker, skipping")
                continue
            ticker_events.append((event.ticker, event))

        if not ticker_events:
            logger.info("No tickers to fetch")
            return results

        unique_tickers = list(set(t for t, _ in ticker_events))
        logger.info(f"Unique tickers to fetch: {unique_tickers}")

        # Step 1: Try Tiger API for each unique ticker
        tiger_quotes = {}
        for ticker in unique_tickers:
            quote = await self.tiger_client.get_stock_quote(ticker)
            if quote:
                tiger_quotes[ticker] = quote

        # Step 2: Fetch from Alpha Vantage for tickers Tiger couldn't handle
        av_needed = [t for t in unique_tickers if t not in tiger_quotes]
        av_quotes = {}
        if av_needed:
            logger.info(f"Fetching {len(av_needed)} tickers from Alpha Vantage")
            av_quotes = await self.av_client.batch_get_stock_quotes(av_needed)

        # Step 3: Process and store all events
        for ticker, event in ticker_events:
            try:
                quote = tiger_quotes.get(ticker)
                data_source = "tiger"

                if not quote:
                    quote = av_quotes.get(ticker)
                    data_source = "alpha_vantage"

                if quote:
                    snapshot = self._parse_quote_to_snapshot(event, quote)
                    if snapshot:
                        stored = await self.db_service.create_snapshot(snapshot)
                        if stored:
                            results["total_fetched"] += 1
                            if data_source == "tiger":
                                results["tiger_success"] += 1
                            else:
                                results["av_fallback"] += 1
                            logger.info(f"Stored snapshot for {ticker} ({data_source})")
                else:
                    results["errors"].append(f"No data for {ticker} from any source")
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
                results["errors"].append(f"Error for {ticker}: {str(e)}")

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
