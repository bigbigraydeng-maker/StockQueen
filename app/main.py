"""
StockQueen V1 - Main Application
FastAPI application entry point
"""

import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from contextlib import asynccontextmanager
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging
import sys
import os

from app.config import settings
from app.middleware.auth import require_api_key
from app.database import Database
from app.scheduler import scheduler
from app.services.websocket_service import start_websocket_client, stop_websocket_client
from app.services.feishu_event_service import start_feishu_event_client, stop_feishu_event_client

# Configure logging
def setup_logging():
    """Configure application logging with daily rotation and separate audit log."""
    from logging.handlers import TimedRotatingFileHandler

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = getattr(logging, settings.log_level.upper())

    # Force UTF-8 for console output on Windows (GBK can't handle emoji)
    stdout_handler = logging.StreamHandler(sys.stdout)
    if sys.platform == "win32":
        import io
        stdout_handler = logging.StreamHandler(
            io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        )
    stdout_handler.setFormatter(logging.Formatter(log_format))

    # Application log — daily rotation, keep 30 days
    os.makedirs("logs", exist_ok=True)
    app_handler = TimedRotatingFileHandler(
        "logs/stockqueen.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    app_handler.setFormatter(logging.Formatter(log_format))

    logging.basicConfig(level=log_level, handlers=[stdout_handler, app_handler])

    # Audit log — separate file for request traces, keep 90 days
    audit_logger = logging.getLogger("audit")
    audit_logger.propagate = False  # don't duplicate to root
    audit_handler = TimedRotatingFileHandler(
        "logs/audit.log", when="midnight", backupCount=90, encoding="utf-8"
    )
    audit_handler.setFormatter(logging.Formatter(log_format))
    audit_logger.addHandler(audit_handler)
    audit_logger.setLevel(logging.INFO)


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

# --- Rate limiter ---
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
    )


# --- CORS middleware (restricted origins) ---
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# --- Security headers middleware ---
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# --- Dashboard auth guard middleware ---
# Redirects unauthenticated browser requests to /login for dashboard pages.
_PUBLIC_PATHS = {"/", "/login", "/health", "/api/auth/login", "/api/auth/refresh", "/logout"}
_PUBLIC_PREFIXES = ("/static/", "/api/public/")


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip public paths
        if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # API endpoints handle their own auth via Depends(require_admin)
        if path.startswith("/api/"):
            return await call_next(request)

        # Dashboard pages — check for valid session cookie
        from app.middleware.auth import COOKIE_ACCESS_TOKEN, COOKIE_REFRESH_TOKEN, _verify_supabase_jwt, COOKIE_API_KEY, _verify_api_key
        token = request.cookies.get(COOKIE_ACCESS_TOKEN)
        api_key = request.cookies.get(COOKIE_API_KEY)

        # If API key cookie is valid, allow
        if _verify_api_key(api_key):
            return await call_next(request)

        # If JWT is valid, allow
        if _verify_supabase_jwt(token):
            return await call_next(request)

        # If no ADMIN_API_KEY configured (dev mode), allow
        if not settings.admin_api_key:
            return await call_next(request)

        # Try auto-refresh with refresh token
        refresh_token = request.cookies.get(COOKIE_REFRESH_TOKEN)
        if refresh_token:
            try:
                from app.database import get_db
                db = get_db()
                auth_response = db.auth.refresh_session(refresh_token)
                if auth_response and auth_response.session:
                    # Proceed and set new cookies on response
                    response: Response = await call_next(request)
                    session = auth_response.session
                    is_prod = settings.app_env == "production"
                    response.set_cookie(
                        key=COOKIE_ACCESS_TOKEN, value=session.access_token,
                        httponly=True, secure=is_prod, samesite="lax",
                        max_age=session.expires_in or 3600,
                    )
                    response.set_cookie(
                        key=COOKIE_REFRESH_TOKEN, value=session.refresh_token,
                        httponly=True, secure=is_prod, samesite="lax",
                        max_age=86400 * 30,
                    )
                    return response
            except Exception:
                pass

        # Not authenticated → redirect to login
        return RedirectResponse(url="/login")


app.add_middleware(DashboardAuthMiddleware)


# --- Request logging middleware ---
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response: Response = await call_next(request)
        duration_ms = (time.time() - start) * 1000
        # Skip noisy health checks and static files
        path = request.url.path
        if path not in ("/health",) and not path.startswith("/static"):
            req_logger = logging.getLogger("audit")
            req_logger.info(
                f"{request.method} {path} → {response.status_code} ({duration_ms:.0f}ms)"
            )
        return response


app.add_middleware(RequestLoggingMiddleware)


# Global exception handler — hide internal details in production
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    logger.error(f"Unhandled exception on {request.url.path}: {exc}\n{traceback.format_exc()}")
    from fastapi.responses import PlainTextResponse
    if settings.app_env == "production":
        return PlainTextResponse("Internal Server Error", status_code=500)
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


# --- Admin login (Supabase Auth — email/password) ---
@app.get("/login")
async def login_page():
    """Login page with Supabase email/password auth"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>StockQueen Login</title>
<style>
body{font-family:system-ui;display:flex;justify-content:center;align-items:center;
height:100vh;background:#0a0a0f;color:#e0e0e0;margin:0}
.card{background:#1a1a2e;padding:2rem;border-radius:12px;width:340px}
input{width:100%;padding:10px;margin:8px 0;box-sizing:border-box;background:#252545;
border:1px solid #333;color:#e0e0e0;border-radius:6px}
button{width:100%;padding:10px;background:#6c5ce7;color:#fff;border:none;
border-radius:6px;cursor:pointer;font-size:14px;margin-top:8px}
button:hover{background:#5a4bd1}
.err{color:#ff6b6b;font-size:13px;display:none;margin-top:6px}
h2{text-align:center;margin-bottom:1rem}
.sub{text-align:center;color:#888;font-size:12px;margin-top:12px}
</style></head>
<body><div class="card"><h2>StockQueen Admin</h2>
<form id="f">
  <input type="email" name="email" placeholder="Email" autocomplete="email" autofocus>
  <input type="password" name="password" placeholder="Password" autocomplete="current-password">
  <div class="err" id="e"></div>
  <button type="submit">Login</button>
</form>
<div class="sub">Authorized users only</div>
<script>
document.getElementById('f').onsubmit=async(ev)=>{
  ev.preventDefault();
  const e=document.getElementById('e');
  e.style.display='none';
  const fd=new FormData(ev.target);
  const r=await fetch('/api/auth/login',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email:fd.get('email'),password:fd.get('password')})});
  const d=await r.json();
  if(r.ok)window.location='/dashboard';
  else{e.textContent=d.detail||'Login failed';e.style.display='block'}
};
</script></div></body></html>""")


@app.post("/api/auth/login")
async def api_login(request: Request):
    """Authenticate via Supabase email/password and set session cookies."""
    from fastapi.responses import JSONResponse
    from app.middleware.auth import COOKIE_ACCESS_TOKEN, COOKIE_REFRESH_TOKEN

    body = await request.json()
    email = body.get("email", "").strip()
    password = body.get("password", "")

    if not email or not password:
        return JSONResponse({"detail": "Email and password required"}, status_code=400)

    try:
        from app.database import get_db
        db = get_db()
        auth_response = db.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if not auth_response or not auth_response.session:
            return JSONResponse({"detail": "Invalid email or password"}, status_code=401)

        session = auth_response.session
        is_prod = settings.app_env == "production"

        response = JSONResponse({
            "success": True,
            "email": auth_response.user.email,
        })
        response.set_cookie(
            key=COOKIE_ACCESS_TOKEN,
            value=session.access_token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=session.expires_in or 3600,
        )
        response.set_cookie(
            key=COOKIE_REFRESH_TOKEN,
            value=session.refresh_token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=86400 * 30,  # 30 days
        )
        logger.info(f"User logged in: {auth_response.user.email}")
        return response

    except Exception as e:
        error_msg = str(e)
        if "Invalid login" in error_msg or "invalid" in error_msg.lower():
            return JSONResponse({"detail": "Invalid email or password"}, status_code=401)
        logger.error(f"Login error: {e}")
        return JSONResponse({"detail": "Login service error"}, status_code=500)


@app.post("/api/auth/refresh")
async def api_refresh(request: Request):
    """Refresh access token using refresh token cookie."""
    from fastapi.responses import JSONResponse
    from app.middleware.auth import COOKIE_ACCESS_TOKEN, COOKIE_REFRESH_TOKEN

    refresh_token = request.cookies.get(COOKIE_REFRESH_TOKEN)
    if not refresh_token:
        return JSONResponse({"detail": "No refresh token"}, status_code=401)

    try:
        from app.database import get_db
        db = get_db()
        auth_response = db.auth.refresh_session(refresh_token)

        if not auth_response or not auth_response.session:
            return JSONResponse({"detail": "Refresh failed"}, status_code=401)

        session = auth_response.session
        is_prod = settings.app_env == "production"

        response = JSONResponse({"success": True})
        response.set_cookie(
            key=COOKIE_ACCESS_TOKEN,
            value=session.access_token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=session.expires_in or 3600,
        )
        response.set_cookie(
            key=COOKIE_REFRESH_TOKEN,
            value=session.refresh_token,
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=86400 * 30,
        )
        return response
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        return JSONResponse({"detail": "Refresh failed"}, status_code=401)


@app.get("/logout")
async def logout():
    """Clear auth cookies and redirect to login"""
    from app.middleware.auth import COOKIE_ACCESS_TOKEN, COOKIE_REFRESH_TOKEN, COOKIE_API_KEY
    response = RedirectResponse(url="/login")
    response.delete_cookie(key=COOKIE_ACCESS_TOKEN)
    response.delete_cookie(key=COOKIE_REFRESH_TOKEN)
    response.delete_cookie(key=COOKIE_API_KEY)
    return response


# Root endpoint → redirect to dashboard
@app.get("/")
async def root():
    """Redirect to dashboard"""
    return RedirectResponse(url="/dashboard")


# Manual trigger endpoint for market data + signal pipeline
@app.post("/api/trigger/market-pipeline")
async def trigger_market_pipeline(_key: str = Depends(require_api_key)):
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
async def diagnose_data_sources(_key: str = Depends(require_api_key)):
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
async def trigger_geopolitical_scan(_key: str = Depends(require_api_key)):
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
async def trigger_geopolitical_backtest(date: str = "2026-02-28", limit: int = 0, _key: str = Depends(require_api_key)):
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
async def trigger_knowledge_collect(_key: str = Depends(require_api_key)):
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
