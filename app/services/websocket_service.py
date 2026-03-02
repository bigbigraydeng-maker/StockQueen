"""
StockQueen V1 - WebSocket Market Data Service
Tiger Open API WebSocket integration for real-time market data streaming
"""

import asyncio
import json
import logging
import websockets
from typing import Optional, Dict, List, Callable, Set
from dataclasses import dataclass
from datetime import datetime
import threading
import time

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WebSocketConfig:
    """WebSocket connection configuration"""
    # Tiger Open API WebSocket endpoints
    WS_URL_GLOBAL = "wss://openapi-sandbox.itiger.com:443/ws"  # Sandbox
    WS_URL_PROD = "wss://openapi.itiger.com:443/ws"  # Production
    
    # Connection settings
    PING_INTERVAL = 30  # seconds
    RECONNECT_DELAY = 5  # seconds
    MAX_RECONNECT_ATTEMPTS = 10
    CONNECTION_TIMEOUT = 30  # seconds


class TigerWebSocketClient:
    """
    Tiger Open API WebSocket Client
    
    Handles real-time market data streaming with automatic reconnection,
    heartbeat/ping-pong, and subscription management.
    """
    
    def __init__(self):
        self.access_token = settings.tiger_access_token
        self.tiger_id = settings.tiger_tiger_id
        self.account = settings.tiger_account
        
        # Use sandbox for development, production for live trading
        self.ws_url = (
            WebSocketConfig.WS_URL_GLOBAL 
            if settings.app_env == "development" 
            else WebSocketConfig.WS_URL_PROD
        )
        
        # Connection state
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.is_running = False
        self.reconnect_attempts = 0
        
        # Subscriptions
        self.subscribed_tickers: Set[str] = set()
        self.price_callbacks: Dict[str, List[Callable]] = {}
        self.quote_callbacks: Dict[str, List[Callable]] = {}
        
        # Background tasks
        self.receive_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.reconnect_task: Optional[asyncio.Task] = None
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
        
        logger.info(f"TigerWebSocketClient initialized. URL: {self.ws_url}")
    
    async def connect(self) -> bool:
        """
        Establish WebSocket connection to Tiger API
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to Tiger WebSocket: {self.ws_url}")
            
            # Connection headers with authentication
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "X-Tiger-ID": self.tiger_id
            }
            
            # Establish connection with timeout
            self.websocket = await asyncio.wait_for(
                websockets.connect(
                    self.ws_url,
                    extra_headers=headers,
                    ping_interval=None,  # We'll handle ping manually
                    ping_timeout=None
                ),
                timeout=WebSocketConfig.CONNECTION_TIMEOUT
            )
            
            self.is_connected = True
            self.reconnect_attempts = 0
            logger.info("✅ WebSocket connection established successfully")
            
            # Start background tasks
            self.receive_task = asyncio.create_task(self._receive_loop())
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            # Resubscribe to previous tickers
            if self.subscribed_tickers:
                await self._resubscribe_all()
            
            return True
            
        except asyncio.TimeoutError:
            logger.error("❌ WebSocket connection timeout")
            return False
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Close WebSocket connection gracefully"""
        logger.info("Disconnecting WebSocket...")
        self.is_running = False
        
        # Cancel background tasks
        tasks = [self.receive_task, self.heartbeat_task, self.reconnect_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Close websocket
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        
        self.is_connected = False
        logger.info("✅ WebSocket disconnected")
    
    async def _receive_loop(self):
        """Main receive loop for WebSocket messages"""
        logger.info("Starting WebSocket receive loop...")
        
        while self.is_running and self.websocket:
            try:
                message = await self.websocket.recv()
                await self._handle_message(message)
                
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                self.is_connected = False
                await self._schedule_reconnect()
                break
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                await asyncio.sleep(1)
    
    async def _handle_message(self, message):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "").upper()
            
            # Handle different message types
            if msg_type == "PONG":
                logger.debug("Received PONG")
                
            elif msg_type == "QUOTE":
                await self._handle_quote_update(data)
                
            elif msg_type == "TRADE":
                await self._handle_trade_update(data)
                
            elif msg_type == "HEARTBEAT":
                logger.debug("Received heartbeat")
                
            elif msg_type == "ERROR":
                logger.error(f"Tiger API error: {data}")
                
            elif msg_type == "SUBSCRIBED":
                logger.info(f"Subscription confirmed: {data.get('ticker')}")
                
            elif msg_type == "UNSUBSCRIBED":
                logger.info(f"Unsubscription confirmed: {data.get('ticker')}")
                
            else:
                logger.debug(f"Received message: {data}")
                
        except json.JSONDecodeError:
            logger.warning(f"Received non-JSON message: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _handle_quote_update(self, data: dict):
        """Handle real-time quote updates"""
        try:
            ticker = data.get("ticker")
            if not ticker:
                return
            
            # Log the update
            price = data.get("price", 0)
            change = data.get("change", 0)
            volume = data.get("volume", 0)
            
            logger.info(f"📊 {ticker}: ${price:,.2f} ({change:+.2f}%) Vol: {volume:,}")
            
            # Execute callbacks
            if ticker in self.quote_callbacks:
                for callback in self.quote_callbacks[ticker]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            asyncio.create_task(callback(data))
                        else:
                            callback(data)
                    except Exception as e:
                        logger.error(f"Callback error for {ticker}: {e}")
            
        except Exception as e:
            logger.error(f"Error handling quote update: {e}")
    
    async def _handle_trade_update(self, data: dict):
        """Handle real-time trade updates"""
        try:
            ticker = data.get("ticker")
            price = data.get("price", 0)
            size = data.get("size", 0)
            
            logger.debug(f"💰 Trade: {ticker} ${price} x {size}")
            
            # Execute price callbacks
            if ticker in self.price_callbacks:
                for callback in self.price_callbacks[ticker]:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            asyncio.create_task(callback(price, size))
                        else:
                            callback(price, size)
                    except Exception as e:
                        logger.error(f"Price callback error for {ticker}: {e}")
                        
        except Exception as e:
            logger.error(f"Error handling trade update: {e}")
    
    async def _heartbeat_loop(self):
        """Send periodic ping messages to keep connection alive"""
        logger.info("Starting heartbeat loop...")
        
        while self.is_running and self.websocket:
            try:
                if self.is_connected:
                    ping_msg = {
                        "type": "PING",
                        "timestamp": int(time.time() * 1000)
                    }
                    await self.websocket.send(json.dumps(ping_msg))
                    logger.debug("📡 Ping sent")
                
                await asyncio.sleep(WebSocketConfig.PING_INTERVAL)
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)
    
    async def _schedule_reconnect(self):
        """Schedule reconnection with exponential backoff"""
        if self.reconnect_task and not self.reconnect_task.done():
            return
        
        self.reconnect_task = asyncio.create_task(self._reconnect_loop())
    
    async def _reconnect_loop(self):
        """Attempt to reconnect with exponential backoff"""
        while self.reconnect_attempts < WebSocketConfig.MAX_RECONNECT_ATTEMPTS:
            self.reconnect_attempts += 1
            delay = min(
                WebSocketConfig.RECONNECT_DELAY * (2 ** (self.reconnect_attempts - 1)),
                300  # Max 5 minutes
            )
            
            logger.info(f"🔄 Reconnect attempt {self.reconnect_attempts}/{WebSocketConfig.MAX_RECONNECT_ATTEMPTS} in {delay}s...")
            await asyncio.sleep(delay)
            
            if await self.connect():
                logger.info("✅ Reconnection successful!")
                return
        
        logger.error("❌ Max reconnection attempts reached. Giving up.")
    
    async def _resubscribe_all(self):
        """Resubscribe to all previously subscribed tickers after reconnection"""
        logger.info(f"Resubscribing to {len(self.subscribed_tickers)} tickers...")
        
        for ticker in list(self.subscribed_tickers):
            await self.subscribe_quote(ticker)
            await asyncio.sleep(0.1)  # Rate limiting
    
    # ============== Public API Methods ==============
    
    async def subscribe_quote(self, ticker: str) -> bool:
        """
        Subscribe to real-time quotes for a ticker
        
        Args:
            ticker: Stock symbol (e.g., "AAPL", "TSLA")
            
        Returns:
            bool: True if subscription request sent successfully
        """
        async with self._lock:
            if not self.is_connected:
                logger.warning(f"Cannot subscribe {ticker}: Not connected")
                return False
            
            try:
                subscribe_msg = {
                    "type": "SUBSCRIBE",
                    "channel": "QUOTE",
                    "ticker": ticker.upper(),
                    "account": self.account
                }
                
                await self.websocket.send(json.dumps(subscribe_msg))
                self.subscribed_tickers.add(ticker.upper())
                
                logger.info(f"📈 Subscribed to {ticker} quotes")
                return True
                
            except Exception as e:
                logger.error(f"Failed to subscribe {ticker}: {e}")
                return False
    
    async def unsubscribe_quote(self, ticker: str) -> bool:
        """
        Unsubscribe from real-time quotes for a ticker
        
        Args:
            ticker: Stock symbol (e.g., "AAPL", "TSLA")
            
        Returns:
            bool: True if unsubscription request sent successfully
        """
        async with self._lock:
            if not self.is_connected:
                logger.warning(f"Cannot unsubscribe {ticker}: Not connected")
                return False
            
            try:
                unsubscribe_msg = {
                    "type": "UNSUBSCRIBE",
                    "channel": "QUOTE",
                    "ticker": ticker.upper()
                }
                
                await self.websocket.send(json.dumps(unsubscribe_msg))
                self.subscribed_tickers.discard(ticker.upper())
                
                logger.info(f"📉 Unsubscribed from {ticker} quotes")
                return True
                
            except Exception as e:
                logger.error(f"Failed to unsubscribe {ticker}: {e}")
                return False
    
    def on_quote_update(self, ticker: str, callback: Callable):
        """
        Register a callback for quote updates
        
        Args:
            ticker: Stock symbol
            callback: Function to call when quote updates (can be sync or async)
        """
        ticker = ticker.upper()
        if ticker not in self.quote_callbacks:
            self.quote_callbacks[ticker] = []
        self.quote_callbacks[ticker].append(callback)
        logger.info(f"✅ Registered quote callback for {ticker}")
    
    def on_price_update(self, ticker: str, callback: Callable):
        """
        Register a callback for price/trade updates
        
        Args:
            ticker: Stock symbol
            callback: Function to call when price updates
        """
        ticker = ticker.upper()
        if ticker not in self.price_callbacks:
            self.price_callbacks[ticker] = []
        self.price_callbacks[ticker].append(callback)
        logger.info(f"✅ Registered price callback for {ticker}")
    
    async def start(self):
        """Start the WebSocket client"""
        self.is_running = True
        return await self.connect()
    
    async def stop(self):
        """Stop the WebSocket client"""
        await self.disconnect()


class RealtimeMarketDataService:
    """
    High-level service for real-time market data
    Manages WebSocket connections and provides easy-to-use interface
    """
    
    def __init__(self):
        self.ws_client = TigerWebSocketClient()
        self.watchlist: Set[str] = set()
        self.price_cache: Dict[str, dict] = {}
        self._initialized = False
    
    async def initialize(self):
        """Initialize the service and start WebSocket connection"""
        if self._initialized:
            return
        
        logger.info("🚀 Initializing RealtimeMarketDataService...")
        
        # Start WebSocket connection
        success = await self.ws_client.start()
        if not success:
            raise ConnectionError("Failed to establish WebSocket connection")
        
        self._initialized = True
        logger.info("✅ RealtimeMarketDataService initialized")
    
    async def shutdown(self):
        """Shutdown the service"""
        logger.info("🛑 Shutting down RealtimeMarketDataService...")
        await self.ws_client.stop()
        self._initialized = False
        logger.info("✅ RealtimeMarketDataService shutdown complete")
    
    async def add_to_watchlist(self, ticker: str):
        """Add a ticker to watchlist and subscribe to updates"""
        ticker = ticker.upper()
        if ticker in self.watchlist:
            return
        
        self.watchlist.add(ticker)
        
        # Subscribe to real-time updates
        await self.ws_client.subscribe_quote(ticker)
        
        # Register callback to cache prices
        self.ws_client.on_quote_update(ticker, self._update_price_cache)
        
        logger.info(f"👀 Added {ticker} to watchlist")
    
    async def remove_from_watchlist(self, ticker: str):
        """Remove a ticker from watchlist"""
        ticker = ticker.upper()
        if ticker not in self.watchlist:
            return
        
        self.watchlist.discard(ticker)
        await self.ws_client.unsubscribe_quote(ticker)
        
        if ticker in self.price_cache:
            del self.price_cache[ticker]
        
        logger.info(f"🗑️ Removed {ticker} from watchlist")
    
    async def _update_price_cache(self, data: dict):
        """Update price cache with real-time data"""
        ticker = data.get("ticker")
        if ticker:
            self.price_cache[ticker] = {
                "price": data.get("price", 0),
                "change": data.get("change", 0),
                "change_percent": data.get("change_percent", 0),
                "volume": data.get("volume", 0),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_current_price(self, ticker: str) -> Optional[dict]:
        """Get cached current price for a ticker"""
        return self.price_cache.get(ticker.upper())
    
    def get_watchlist_prices(self) -> Dict[str, dict]:
        """Get all cached prices for watchlist"""
        return self.price_cache.copy()
    
    def on_price_change(self, ticker: str, callback: Callable):
        """Register callback for price changes"""
        self.ws_client.on_quote_update(ticker.upper(), callback)


# Singleton instance
_realtime_service: Optional[RealtimeMarketDataService] = None


def get_realtime_service() -> RealtimeMarketDataService:
    """Get or create singleton instance of RealtimeMarketDataService"""
    global _realtime_service
    if _realtime_service is None:
        _realtime_service = RealtimeMarketDataService()
    return _realtime_service


# Convenience functions
async def start_websocket_client() -> bool:
    """Start WebSocket client globally"""
    service = get_realtime_service()
    try:
        await service.initialize()
        return True
    except Exception as e:
        logger.error(f"Failed to start WebSocket client: {e}")
        return False


async def stop_websocket_client():
    """Stop WebSocket client globally"""
    service = get_realtime_service()
    await service.shutdown()


async def subscribe_ticker(ticker: str):
    """Subscribe to a ticker for real-time updates"""
    service = get_realtime_service()
    await service.add_to_watchlist(ticker)


async def unsubscribe_ticker(ticker: str):
    """Unsubscribe from a ticker"""
    service = get_realtime_service()
    await service.remove_from_watchlist(ticker)