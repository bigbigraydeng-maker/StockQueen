"""
StockQueen V2.4 - Market Data Service
Alpha Vantage as sole market data source. Tiger used only for trading (TradeClient).
"""

import logging
from typing import Optional, List

from app.config import settings, RiskConfig
from app.models import MarketSnapshotCreate
from app.services.db_service import AIEventService, MarketDataService
from app.services.alphavantage_client import get_av_client

logger = logging.getLogger(__name__)


class AlphaVantageFinanceClient:
    """Alpha Vantage client for market data"""

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
    """Market data service using Alpha Vantage"""

    def __init__(self):
        self.av_client = AlphaVantageFinanceClient()
        self.ai_service = AIEventService()
        self.db_service = MarketDataService()

    async def fetch_market_data_for_valid_events(self) -> dict:
        """Fetch market data for all valid AI events via Alpha Vantage"""
        results = {
            "total_valid_events": 0,
            "total_fetched": 0,
            "av_success": 0,
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

        # Batch fetch from Alpha Vantage
        av_quotes = await self.av_client.batch_get_stock_quotes(unique_tickers)

        # Process and store all events
        for ticker, event in ticker_events:
            try:
                quote = av_quotes.get(ticker)

                if quote:
                    snapshot = self._parse_quote_to_snapshot(event, quote)
                    if snapshot:
                        stored = await self.db_service.create_snapshot(snapshot)
                        if stored:
                            results["total_fetched"] += 1
                            results["av_success"] += 1
                            logger.info(f"Stored snapshot for {ticker} (alpha_vantage)")
                else:
                    results["errors"].append(f"No data for {ticker} from Alpha Vantage")
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
                results["errors"].append(f"Error for {ticker}: {str(e)}")

        return results

    def _parse_quote_to_snapshot(
        self,
        event,
        quote: dict
    ) -> Optional[MarketSnapshotCreate]:
        """Parse quote to market snapshot"""
        try:
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
