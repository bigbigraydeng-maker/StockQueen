"""
StockQueen V1 - Main Application
FastAPI application entry point
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
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
    # Force UTF-8 for console output on Windows (GBK can't handle emoji)
    stdout_handler = logging.StreamHandler(sys.stdout)
    if sys.platform == "win32":
        import io
        stdout_handler = logging.StreamHandler(
            io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        )
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            stdout_handler,
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
    
    # Start Feishu Platform event client (long connection) with timeout
    try:
        import asyncio
        feishu_success = await asyncio.wait_for(start_feishu_event_client(), timeout=10.0)
        if feishu_success:
            logger.info("✅ Feishu Platform event client started - Event subscription active")
        else:
            logger.warning("⚠️ Feishu event client not started - Check FEISHU_APP_ID and FEISHU_APP_SECRET")
    except asyncio.TimeoutError:
        logger.warning("⚠️ Feishu event client startup timed out (10s) - skipping, will retry later")
    except Exception as e:
        logger.error(f"Failed to start Feishu event client: {e}")

    # Load prefetched backtest data from disk (if available from previous run).
    # Backtest results (25 preset combos) are persisted in Supabase cache_store (L3).
    # For custom date ranges we still need OHLCV data in memory (_PREFETCHED_FULL).
    try:
        from app.services.rotation_service import _load_prefetched_from_disk, _PREFETCHED_FULL
        _load_prefetched_from_disk()
        if not _PREFETCHED_FULL or "histories" not in _PREFETCHED_FULL:
            # Check if Supabase already has cached backtest results (lightweight query)
            from app.routers.web import _cache_exists
            sample_key = "bt_v2:2022-07-01:2026-03-15:3:1.0"
            has_cached_results = _cache_exists(sample_key)

            if has_cached_results:
                # Preset combos served from Supabase. Still need OHLCV data for
                # custom date ranges — do a lightweight data-only prefetch (no
                # fundamentals, no 25-combo computation) after a short delay.
                logger.info("Backtest results in Supabase. Scheduling OHLCV-only prefetch for custom ranges...")

                async def _delayed_ohlcv_prefetch():
                    await asyncio.sleep(60)
                    logger.info("Starting OHLCV-only prefetch (skip fundamentals + combos)...")
                    from app.services.rotation_service import (
                        _fetch_backtest_ohlcv_only, set_prefetched_full,
                    )
                    data = await _fetch_backtest_ohlcv_only("2021-07-01", "2026-03-15")
                    if "error" not in data:
                        # Restore bt_fundamentals from Supabase cache (saved by weekly scheduler)
                        from app.routers.web import _cache_get
                        cached_fund = _cache_get("bt_fund:latest")
                        if cached_fund:
                            data["bt_fundamentals"] = cached_fund
                            logger.info(f"Restored bt_fundamentals from Supabase ({len(cached_fund)} tickers)")
                        else:
                            logger.warning("No cached bt_fundamentals — custom ranges will use price-only factors")
                        set_prefetched_full(data, "2021-07-01", "2026-03-15")
                        logger.info("OHLCV-only prefetch complete — custom date ranges ready")
                    else:
                        logger.warning(f"OHLCV-only prefetch failed: {data['error']}")

                asyncio.create_task(_delayed_ohlcv_prefetch())
            else:
                logger.info("No cached backtest data anywhere — will pre-compute after 5min delay")

                async def _delayed_precompute():
                    await asyncio.sleep(300)  # 5min delay, let server stabilize
                    logger.info("Starting delayed backtest pre-compute...")
                    await scheduler._run_backtest_precompute()

                asyncio.create_task(_delayed_precompute())
        else:
            logger.info("Backtest data restored from disk cache")
    except Exception as e:
        logger.warning(f"Failed to load/schedule backtest data: {e}")

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


# Global exception handler for debugging
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    logger.error(f"Unhandled exception on {request.url.path}: {exc}\n{traceback.format_exc()}")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(f"Internal Server Error: {exc}", status_code=500)


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


# Root endpoint → redirect to dashboard
@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/dashboard")


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
    """Test Alpha Vantage connectivity with a single ticker"""
    from app.services.market_service import AlphaVantageFinanceClient

    results = {"alpha_vantage": {}}
    test_ticker = "AAPL"

    try:
        av = AlphaVantageFinanceClient()
        quote = await av.get_stock_quote(test_ticker)
        if quote:
            results["alpha_vantage"] = {"status": "ok", "data": quote}
        else:
            results["alpha_vantage"] = {"status": "failed", "reason": "no data returned"}
    except Exception as e:
        results["alpha_vantage"] = {"status": "error", "reason": str(e)}

    return results


# Geopolitical crisis scan endpoint (Hormuz crisis)
@app.post("/api/trigger/geopolitical-scan")
async def trigger_geopolitical_scan():
    """
    Manually trigger geopolitical crisis scan.
    Scans oil/gas, shipping, gold, defense (long) and airlines/cruise (short).
    """
    from app.services.signal_service import run_geopolitical_scan
    from app.services.notification_service import notify_geopolitical_signals

    signals = await run_geopolitical_scan()

    if signals:
        await notify_geopolitical_signals(signals)

    return {
        "crisis": "hormuz_strait",
        "signals_generated": len(signals) if signals else 0,
        "signals": [s.dict() if hasattr(s, 'dict') else str(s) for s in (signals or [])],
    }


# Geopolitical backtest endpoint (free historical data via akshare)
@app.post("/api/trigger/geopolitical-backtest")
async def trigger_geopolitical_backtest(date: str = "2026-02-28", limit: int = 0):
    """
    Backtest geopolitical scan against a historical date.
    Uses akshare (free) for full historical data - no cost.

    - date: Target date (YYYY-MM-DD), default=2026-02-28 (Hormuz crisis day)
    - limit: Max tickers to scan (0=all ~92 tickers)
    """
    from app.services.signal_service import run_geopolitical_backtest

    result = await run_geopolitical_backtest(
        target_date=date,
        ticker_limit=limit if limit > 0 else None,
    )
    return result


# Import and include routers
from app.routers import signals, risk, websocket, knowledge, rotation, web
app.include_router(web.router)  # Web dashboard (no prefix, pages at / /dashboard /knowledge)
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(risk.router, prefix="/api/risk", tags=["risk"])
app.include_router(websocket.router, prefix="/api/websocket", tags=["websocket"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(rotation.router, prefix="/api/rotation", tags=["rotation"])


# Manual trigger for RAG knowledge collectors
@app.post("/api/trigger/knowledge-collect")
async def trigger_knowledge_collect():
    """Manually trigger all 4 knowledge collectors"""
    from app.services.knowledge_collectors import run_all_collectors
    result = await run_all_collectors()
    return {"success": True, "collectors": result}


# Mount static files (MUST be after all route registrations to avoid catch-all)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.app_env == "development"
    )
