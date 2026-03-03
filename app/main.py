"""
StockQueen V1 - Main Application
FastAPI application entry point
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import sys
import os

from app.config import settings
from app.database import Database
from app.scheduler import scheduler
from app.services.websocket_service import start_websocket_client, stop_websocket_client
from app.services.feishu_event_service import start_feishu_event_client, stop_feishu_event_client

# Configure logging
def setup_logging():
    """Configure application logging"""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("stockqueen.log", encoding="utf-8")
        ]
    )


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"Starting {settings.app_name} in {settings.app_env} mode")
    
    # Initialize database connection
    try:
        db = Database.get_client()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise
    
    # Start scheduler
    try:
        scheduler.start()
        logger.info("Task scheduler started")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
    
    # Start WebSocket client for real-time market data
    try:
        ws_success = await start_websocket_client()
        if ws_success:
            logger.info("✅ WebSocket client started - Real-time market data streaming active")
        else:
            logger.warning("⚠️ WebSocket client failed to start - Falling back to HTTP polling")
    except Exception as e:
        logger.error(f"Failed to start WebSocket client: {e}")
    
    # Start Feishu Platform event client (long connection)
    try:
        feishu_success = await start_feishu_event_client()
        if feishu_success:
            logger.info("✅ Feishu Platform event client started - Event subscription active")
        else:
            logger.warning("⚠️ Feishu event client not started - Check FEISHU_APP_ID and FEISHU_APP_SECRET")
    except Exception as e:
        logger.error(f"Failed to start Feishu event client: {e}")
    
    yield
    
    # Shutdown
    try:
        await stop_feishu_event_client()
        logger.info("Feishu event client stopped")
    except Exception as e:
        logger.error(f"Failed to stop Feishu event client: {e}")
    
    try:
        await stop_websocket_client()
        logger.info("WebSocket client stopped")
    except Exception as e:
        logger.error(f"Failed to stop WebSocket client: {e}")
    
    try:
        scheduler.shutdown()
        logger.info("Task scheduler shutdown")
    except Exception as e:
        logger.error(f"Failed to shutdown scheduler: {e}")
    
    logger.info(f"Shutting down {settings.app_name}")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="AI-driven event-driven trading system for biotech stocks",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": "1.0.0",
        "environment": settings.app_env
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "app": settings.app_name,
        "version": "1.0.0",
        "description": "AI-driven event-driven trading system",
        "docs": "/docs",
        "health": "/health"
    }


# Manual trigger endpoint for market data + signal pipeline
@app.post("/api/trigger/market-pipeline")
async def trigger_market_pipeline():
    """Manually trigger market data fetch + signal generation"""
    from app.services.market_service import run_market_data_fetch
    from app.services.signal_service import run_signal_generation

    market_result = await run_market_data_fetch()
    signals = await run_signal_generation()

    return {
        "market_data": market_result,
        "signals_generated": len(signals) if signals else 0,
        "signals": [s.dict() if hasattr(s, 'dict') else str(s) for s in (signals or [])]
    }


# Diagnostic endpoint to test data source connectivity
@app.get("/api/diag/data-sources")
async def diagnose_data_sources():
    """Test Tiger API and Yahoo Finance connectivity with a single ticker"""
    import asyncio
    from app.services.market_service import TigerAPIClient, YahooFinanceClient

    results = {"tiger": {}, "yahoo": {}}
    test_ticker = "AAPL"

    # Test Tiger
    try:
        tiger = TigerAPIClient()
        quote = await tiger.get_stock_quote(test_ticker)
        if quote:
            results["tiger"] = {"status": "ok", "data": quote}
        else:
            results["tiger"] = {"status": "failed", "reason": "no data returned (likely permission denied)"}
    except Exception as e:
        results["tiger"] = {"status": "error", "reason": str(e)}

    # Test Yahoo
    try:
        yahoo = YahooFinanceClient()
        quote = await yahoo.get_stock_quote(test_ticker)
        if quote:
            results["yahoo"] = {"status": "ok", "data": quote}
        else:
            results["yahoo"] = {"status": "failed", "reason": "no data returned (likely IP banned)"}
    except Exception as e:
        results["yahoo"] = {"status": "error", "reason": str(e)}

    return results


# Import and include routers
from app.routers import signals, risk, websocket
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
app.include_router(websocket.router, prefix="/api/websocket", tags=["websocket"])


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.app_env == "development"
    )
