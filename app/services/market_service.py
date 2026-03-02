"""
StockQueen V1 - Market Data Service
Tiger Open API (official SDK) with yfinance fallback
"""

import asyncio
import logging
import os
import tempfile
import yfinance as yf
import pandas as pd
from typing import Optional, List
from datetime import datetime

from app.config import settings, RiskConfig
from app.models import MarketSnapshotCreate
from app.services.db_service import AIEventService, MarketDataService

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


class YahooFinanceClient:
    """Yahoo Finance client using yfinance with batch download to avoid 429 rate limiting"""

    def __init__(self):
        self.timeout = 30.0

    def _batch_fetch_yahoo_data(self, tickers: list) -> dict:
        """
        Download stock data in small batches with delays to avoid Yahoo 429 rate limiting.
        yf.download() still makes per-ticker requests internally, so we split into chunks.
        """
        if not tickers:
            return {}

        BATCH_SIZE = 10
        BATCH_DELAY = 3  # seconds between batches

        all_results = {}
        chunks = [tickers[i:i + BATCH_SIZE] for i in range(0, len(tickers), BATCH_SIZE)]

        for chunk_idx, chunk in enumerate(chunks):
            try:
                logger.info(f"Yahoo Finance batch {chunk_idx + 1}/{len(chunks)}: downloading {len(chunk)} tickers")

                data = yf.download(
                    chunk,
                    period="5d",
                    group_by="ticker" if len(chunk) > 1 else None,
                    threads=False
                )

                if data.empty:
                    logger.warning(f"Yahoo batch {chunk_idx + 1} returned empty data")
                else:
                    for ticker in chunk:
                        try:
                            if len(chunk) == 1:
                                df = data
                            else:
                                if ticker not in data.columns.get_level_values(0):
                                    continue
                                df = data[ticker]

                            df = df.dropna(subset=['Close'])
                            if len(df) < 1:
                                continue

                            latest = df.iloc[-1]
                            prev = df.iloc[-2] if len(df) > 1 else latest

                            day_change_pct = ((float(latest['Close']) - float(prev['Close'])) / float(prev['Close']) * 100) if len(df) > 1 else 0.0
                            avg_volume = int(df['Volume'].mean()) if not df['Volume'].isna().all() else 0

                            all_results[ticker] = {
                                "ticker": ticker,
                                "prev_close": float(prev['Close']),
                                "open": float(latest['Open']),
                                "high": float(latest['High']),
                                "low": float(latest['Low']),
                                "latest_price": float(latest['Close']),
                                "change_percent": float(day_change_pct),
                                "volume": int(latest['Volume']) if not pd.isna(latest['Volume']) else 0,
                                "avg_volume_30d": avg_volume,
                                "market_cap": 0,
                                "data_source": "yahoo_finance"
                            }
                        except Exception as e:
                            logger.error(f"Error parsing batch data for {ticker}: {e}")

            except Exception as e:
                logger.error(f"Yahoo batch {chunk_idx + 1} download error: {e}")

            # Delay between batches to avoid rate limiting
            if chunk_idx < len(chunks) - 1:
                import time
                time.sleep(BATCH_DELAY)

        logger.info(f"Yahoo Finance total: {len(all_results)}/{len(tickers)} tickers successful")
        return all_results

    async def batch_get_stock_quotes(self, tickers: list) -> dict:
        """Async wrapper for batch Yahoo Finance download"""
        if not tickers:
            return {}
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._batch_fetch_yahoo_data, tickers)

    async def get_stock_quote(self, ticker: str) -> Optional[dict]:
        """Get single stock quote (uses batch internally)"""
        results = await self.batch_get_stock_quotes([ticker])
        return results.get(ticker)

    async def get_premarket_data(self, ticker: str) -> Optional[dict]:
        """Get premarket data - uses batch history data"""
        results = await self.batch_get_stock_quotes([ticker])
        quote = results.get(ticker)
        if quote:
            return {
                "ticker": ticker,
                "premarket_price": quote["latest_price"],
                "previous_close": quote["prev_close"],
                "premarket_change_pct": quote["change_percent"],
                "has_premarket": True
            }
        return None


class MarketDataFetcher:
    """Market data service with Tiger API primary and Yahoo Finance fallback"""
    
    def __init__(self):
        self.tiger_client = TigerAPIClient()
        self.yahoo_client = YahooFinanceClient()
        self.ai_service = AIEventService()
        self.db_service = MarketDataService()
    
    async def fetch_market_data_for_valid_events(self) -> dict:
        """Fetch market data for all valid AI events with Tiger primary + Yahoo batch fallback"""
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

        # Step 2: Batch download from Yahoo for tickers Tiger couldn't handle
        yahoo_needed = [t for t in unique_tickers if t not in tiger_quotes]
        yahoo_quotes = {}
        if yahoo_needed:
            logger.info(f"Batch downloading {len(yahoo_needed)} tickers from Yahoo Finance")
            yahoo_quotes = await self.yahoo_client.batch_get_stock_quotes(yahoo_needed)

        # Step 3: Process and store all events
        for ticker, event in ticker_events:
            try:
                quote = tiger_quotes.get(ticker)
                data_source = "tiger"

                if not quote:
                    quote = yahoo_quotes.get(ticker)
                    data_source = "yahoo"

                if quote:
                    snapshot = self._parse_quote_to_snapshot(event, quote)
                    if snapshot:
                        stored = await self.db_service.create_snapshot(snapshot)
                        if stored:
                            results["total_fetched"] += 1
                            if data_source == "tiger":
                                results["tiger_success"] += 1
                            else:
                                results["yahoo_fallback"] += 1
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
