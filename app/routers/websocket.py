"""
StockQueen V1 - WebSocket Management Router
API endpoints for managing WebSocket connections and real-time subscriptions
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import logging

from app.services.websocket_service import (
    get_realtime_service,
    subscribe_ticker,
    unsubscribe_ticker
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SubscriptionRequest(BaseModel):
    """Request model for subscription operations"""
    ticker: str


class SubscriptionResponse(BaseModel):
    """Response model for subscription operations"""
    success: bool
    message: str
    ticker: str


class WatchlistResponse(BaseModel):
    """Response model for watchlist"""
    tickers: List[str]
    count: int


class PriceData(BaseModel):
    """Real-time price data model"""
    ticker: str
    price: float
    change: float
    change_percent: float
    volume: int
    timestamp: str


class PricesResponse(BaseModel):
    """Response model for prices"""
    prices: dict
    count: int


@router.post("/subscribe", response_model=SubscriptionResponse)
async def subscribe_to_ticker(request: SubscriptionRequest):
    """
    Subscribe to real-time market data for a ticker
    
    - **ticker**: Stock symbol (e.g., "AAPL", "TSLA")
    
    Returns subscription confirmation
    """
    try:
        ticker = request.ticker.upper()
        await subscribe_ticker(ticker)
        
        return SubscriptionResponse(
            success=True,
            message=f"Successfully subscribed to {ticker}",
            ticker=ticker
        )
    except Exception as e:
        logger.error(f"Failed to subscribe {request.ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unsubscribe", response_model=SubscriptionResponse)
async def unsubscribe_from_ticker(request: SubscriptionRequest):
    """
    Unsubscribe from real-time market data for a ticker
    
    - **ticker**: Stock symbol (e.g., "AAPL", "TSLA")
    
    Returns unsubscription confirmation
    """
    try:
        ticker = request.ticker.upper()
        await unsubscribe_ticker(ticker)
        
        return SubscriptionResponse(
            success=True,
            message=f"Successfully unsubscribed from {ticker}",
            ticker=ticker
        )
    except Exception as e:
        logger.error(f"Failed to unsubscribe {request.ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist():
    """Get list of currently subscribed tickers"""
    try:
        service = get_realtime_service()
        tickers = list(service.watchlist)
        
        return WatchlistResponse(
            tickers=tickers,
            count=len(tickers)
        )
    except Exception as e:
        logger.error(f"Failed to get watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prices", response_model=PricesResponse)
async def get_cached_prices():
    """
    Get cached real-time prices for all subscribed tickers
    
    Returns current price data from WebSocket stream
    """
    try:
        service = get_realtime_service()
        prices = service.get_watchlist_prices()
        
        return PricesResponse(
            prices=prices,
            count=len(prices)
        )
    except Exception as e:
        logger.error(f"Failed to get prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prices/{ticker}", response_model=Optional[PriceData])
async def get_ticker_price(ticker: str):
    """
    Get cached real-time price for a specific ticker
    
    - **ticker**: Stock symbol (e.g., "AAPL", "TSLA")
    
    Returns price data if ticker is subscribed
    """
    try:
        service = get_realtime_service()
        price_data = service.get_current_price(ticker)
        
        if price_data:
            return PriceData(
                ticker=ticker.upper(),
                price=price_data.get("price", 0),
                change=price_data.get("change", 0),
                change_percent=price_data.get("change_percent", 0),
                volume=price_data.get("volume", 0),
                timestamp=price_data.get("timestamp", "")
            )
        else:
            return None
            
    except Exception as e:
        logger.error(f"Failed to get price for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/watchlist/batch-subscribe")
async def batch_subscribe(tickers: List[str]):
    """
    Subscribe to multiple tickers at once
    
    - **tickers**: List of stock symbols (e.g., ["AAPL", "TSLA", "MSFT"])
    
    Returns batch subscription results
    """
    results = []
    
    for ticker in tickers:
        try:
            await subscribe_ticker(ticker.upper())
            results.append({"ticker": ticker.upper(), "success": True})
        except Exception as e:
            results.append({"ticker": ticker.upper(), "success": False, "error": str(e)})
    
    successful = sum(1 for r in results if r["success"])
    
    return {
        "total": len(tickers),
        "successful": successful,
        "failed": len(tickers) - successful,
        "results": results
    }


@router.delete("/watchlist/clear")
async def clear_watchlist():
    """Remove all tickers from watchlist and unsubscribe"""
    try:
        service = get_realtime_service()
        tickers = list(service.watchlist)
        
        for ticker in tickers:
            await unsubscribe_ticker(ticker)
        
        return {
            "success": True,
            "message": f"Cleared {len(tickers)} tickers from watchlist",
            "removed": tickers
        }
    except Exception as e:
        logger.error(f"Failed to clear watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_websocket_status():
    """Get WebSocket connection status"""
    try:
        service = get_realtime_service()
        ws_client = service.ws_client
        
        return {
            "connected": ws_client.is_connected,
            "running": ws_client.is_running,
            "reconnect_attempts": ws_client.reconnect_attempts,
            "subscribed_tickers": list(ws_client.subscribed_tickers),
            "watchlist_count": len(service.watchlist),
            "cached_prices_count": len(service.price_cache),
            "websocket_url": ws_client.ws_url
        }
    except Exception as e:
        logger.error(f"Failed to get WebSocket status: {e}")
        raise HTTPException(status_code=500, detail=str(e))