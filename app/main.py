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


logger = logging.getLogger(__name__)


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
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
height:100vh;background:#0a0a0f;color:#e0e0e0;overflow:hidden;
display:flex;justify-content:center;align-items:center}
.bg-overlay{position:fixed;top:0;left:0;width:100%;height:100%;
background:linear-gradient(135deg,rgba(108,92,231,0.08) 0%,rgba(10,10,15,0.95) 50%,rgba(108,92,231,0.05) 100%);
z-index:0}
.founders{position:fixed;bottom:0;left:0;right:0;display:flex;justify-content:center;
gap:60px;z-index:1;pointer-events:none;opacity:0.12}
.founders img{height:420px;object-fit:cover;object-position:top;
filter:grayscale(0.5) brightness(0.8);mask-image:linear-gradient(to top,transparent 0%,black 40%)}
.quote-bar{position:fixed;top:40px;left:0;right:0;text-align:center;z-index:2;
padding:0 20px;animation:fadeIn 2s ease-in}
.quote-text{font-size:18px;font-style:italic;color:rgba(255,255,255,0.6);
letter-spacing:0.5px;line-height:1.6;max-width:700px;margin:0 auto}
.quote-author{font-size:13px;color:rgba(108,92,231,0.7);margin-top:8px}
@keyframes fadeIn{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:translateY(0)}}
.card{position:relative;z-index:10;background:rgba(26,26,46,0.92);
padding:2.5rem;border-radius:16px;width:380px;
backdrop-filter:blur(20px);border:1px solid rgba(108,92,231,0.15);
box-shadow:0 20px 60px rgba(0,0,0,0.5)}
.logo{text-align:center;margin-bottom:1.5rem}
.logo h2{font-size:24px;font-weight:700;background:linear-gradient(135deg,#6c5ce7,#a29bfe);
-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.logo .crown{font-size:32px;display:block;margin-bottom:4px}
input{width:100%;padding:12px 14px;margin:8px 0;background:rgba(37,37,69,0.8);
border:1px solid rgba(108,92,231,0.2);color:#e0e0e0;border-radius:8px;
font-size:14px;transition:border-color 0.3s}
input:focus{outline:none;border-color:#6c5ce7;box-shadow:0 0 0 3px rgba(108,92,231,0.1)}
button{width:100%;padding:12px;background:linear-gradient(135deg,#6c5ce7,#5a4bd1);color:#fff;border:none;
border-radius:8px;cursor:pointer;font-size:15px;font-weight:600;margin-top:12px;
transition:all 0.3s;letter-spacing:0.5px}
button:hover{background:linear-gradient(135deg,#7c6cf7,#6c5ce7);transform:translateY(-1px);
box-shadow:0 4px 15px rgba(108,92,231,0.3)}
button:disabled{background:#333;cursor:not-allowed;transform:none;box-shadow:none}
.err{color:#ff6b6b;font-size:13px;display:none;margin-top:8px;text-align:center}
.links{text-align:center;margin-top:16px;font-size:13px}
.links a{color:#6c5ce7;text-decoration:none;transition:color 0.2s}
.links a:hover{color:#a29bfe}
.sub{text-align:center;color:rgba(255,255,255,0.3);font-size:11px;margin-top:16px}
</style></head>
<body>
<div class="bg-overlay"></div>
<div class="founders">
  <img src="/static/images/richardhu.jpg" alt="">
  <img src="/static/images/raydeng.jpg" alt="">
</div>
<div class="quote-bar">
  <div class="quote-text" id="qt"></div>
  <div class="quote-author" id="qa"></div>
</div>
<div class="card">
  <div class="logo"><span class="crown">&#9813;</span><h2>StockQueen</h2></div>
  <form id="f">
    <input type="email" name="email" placeholder="Email" autocomplete="email" required autofocus>
    <input type="password" name="password" placeholder="Password" autocomplete="current-password" required>
    <div class="err" id="e"></div>
    <button type="submit" id="btn">Sign In</button>
  </form>
  <div class="links"><a href="/change-password">Change Password</a></div>
  <div class="sub">Authorized access only</div>
</div>
<script>
const quotes=[
  ['"The stock market is a device for transferring money from the impatient to the patient."','— Warren Buffett'],
  ['"In investing, what is comfortable is rarely profitable."','— Robert Arnott'],
  ['"The best investment you can make is in yourself."','— Warren Buffett'],
  ['"Risk comes from not knowing what you are doing."','— Warren Buffett'],
  ['"Price is what you pay. Value is what you get."','— Warren Buffett'],
  ['"The four most dangerous words in investing are: This time it\\'s different."','— Sir John Templeton'],
  ['"Know what you own, and know why you own it."','— Peter Lynch'],
  ['"Be fearful when others are greedy, and greedy when others are fearful."','— Warren Buffett'],
];
const q=quotes[Math.floor(Math.random()*quotes.length)];
document.getElementById('qt').textContent=q[0];
document.getElementById('qa').textContent=q[1];
document.getElementById('f').onsubmit=async(ev)=>{
  ev.preventDefault();
  const e=document.getElementById('e');
  const btn=document.getElementById('btn');
  e.style.display='none';
  btn.disabled=true;
  btn.textContent='Signing in...';
  try{
    const fd=new FormData(ev.target);
    const r=await fetch('/api/auth/login',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email:fd.get('email'),password:fd.get('password')})});
    let d;
    try{d=await r.json()}catch{d={detail:'Server error ('+r.status+')'}}
    if(r.ok){window.location='/dashboard'}
    else{e.textContent=d.detail||'Login failed';e.style.display='block'}
  }catch(err){
    e.textContent='Network error: '+err.message;e.style.display='block';
  }finally{
    btn.disabled=false;btn.textContent='Sign In';
  }
};
</script>
</body></html>""")


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
        import httpx
        # Use Supabase REST API directly (more reliable than SDK create_client per-request)
        api_key = settings.supabase_anon_key or settings.supabase_service_key
        async with httpx.AsyncClient(timeout=10) as client:
            auth_resp = await client.post(
                f"{settings.supabase_url}/auth/v1/token?grant_type=password",
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"email": email, "password": password},
            )

        if auth_resp.status_code != 200:
            detail = "Invalid email or password"
            try:
                err_data = auth_resp.json()
                detail = err_data.get("error_description") or err_data.get("msg") or detail
            except Exception:
                pass
            return JSONResponse({"detail": detail}, status_code=401)

        auth_data = auth_resp.json()
        access_token = auth_data.get("access_token")
        refresh_token = auth_data.get("refresh_token", "")
        expires_in = int(auth_data.get("expires_in", 3600))
        user_email = auth_data.get("user", {}).get("email", email)

        if not access_token:
            logger.error(f"Login: no access_token in response keys={list(auth_data.keys())}")
            return JSONResponse({"detail": "Login failed: no token received"}, status_code=401)

        is_prod = settings.app_env == "production"
        logger.info(f"Login success for {user_email}, setting cookies (prod={is_prod})")

        response = JSONResponse({
            "success": True,
            "email": user_email,
        })
        response.set_cookie(
            key=COOKIE_ACCESS_TOKEN,
            value=str(access_token),
            httponly=True,
            secure=is_prod,
            samesite="lax",
            max_age=expires_in,
        )
        if refresh_token:
            response.set_cookie(
                key=COOKIE_REFRESH_TOKEN,
                value=str(refresh_token),
                httponly=True,
                secure=is_prod,
                samesite="lax",
                max_age=86400 * 30,  # 30 days
            )
        logger.info(f"User logged in: {user_email}")
        return response

    except Exception as e:
        import traceback
        error_msg = str(e)
        logger.error(f"Login error: {error_msg}\n{traceback.format_exc()}")
        if "Invalid login" in error_msg or "invalid" in error_msg.lower():
            return JSONResponse({"detail": "Invalid email or password"}, status_code=401)
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


@app.get("/change-password")
async def change_password_page():
    """Change password page — requires login first to get access token"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Change Password - StockQueen</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;height:100vh;
background:#0a0a0f;color:#e0e0e0;display:flex;justify-content:center;align-items:center}
.card{background:rgba(26,26,46,0.95);padding:2.5rem;border-radius:16px;width:400px;
border:1px solid rgba(108,92,231,0.15);box-shadow:0 20px 60px rgba(0,0,0,0.5)}
h2{text-align:center;margin-bottom:0.5rem;font-size:22px;
background:linear-gradient(135deg,#6c5ce7,#a29bfe);
-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.desc{text-align:center;color:#888;font-size:13px;margin-bottom:1.5rem}
label{display:block;font-size:13px;color:#aaa;margin-top:14px;margin-bottom:4px}
input{width:100%;padding:12px 14px;background:rgba(37,37,69,0.8);
border:1px solid rgba(108,92,231,0.2);color:#e0e0e0;border-radius:8px;font-size:14px}
input:focus{outline:none;border-color:#6c5ce7;box-shadow:0 0 0 3px rgba(108,92,231,0.1)}
button{width:100%;padding:12px;background:linear-gradient(135deg,#6c5ce7,#5a4bd1);color:#fff;
border:none;border-radius:8px;cursor:pointer;font-size:15px;font-weight:600;margin-top:20px;
transition:all 0.3s}
button:hover{background:linear-gradient(135deg,#7c6cf7,#6c5ce7);transform:translateY(-1px)}
button:disabled{background:#333;cursor:not-allowed;transform:none}
.msg{font-size:13px;margin-top:10px;text-align:center;display:none}
.msg.err{color:#ff6b6b}
.msg.ok{color:#00b894}
.links{text-align:center;margin-top:16px;font-size:13px}
.links a{color:#6c5ce7;text-decoration:none}
.links a:hover{color:#a29bfe}
</style></head>
<body><div class="card">
<h2>Change Password</h2>
<p class="desc">Enter your email and current password to verify, then set a new password.</p>
<form id="f">
  <label>Email</label>
  <input type="email" name="email" autocomplete="email" required>
  <label>Current Password</label>
  <input type="password" name="current_password" autocomplete="current-password" required>
  <label>New Password</label>
  <input type="password" name="new_password" minlength="6" required>
  <label>Confirm New Password</label>
  <input type="password" name="confirm_password" minlength="6" required>
  <div class="msg" id="m"></div>
  <button type="submit" id="btn">Update Password</button>
</form>
<div class="links"><a href="/login">&larr; Back to Login</a></div>
</div>
<script>
document.getElementById('f').onsubmit=async(ev)=>{
  ev.preventDefault();
  const m=document.getElementById('m');
  const btn=document.getElementById('btn');
  m.style.display='none';
  const fd=new FormData(ev.target);
  const np=fd.get('new_password'), cp=fd.get('confirm_password');
  if(np!==cp){m.textContent='New passwords do not match';m.className='msg err';m.style.display='block';return}
  if(np.length<6){m.textContent='Password must be at least 6 characters';m.className='msg err';m.style.display='block';return}
  btn.disabled=true;btn.textContent='Updating...';
  try{
    const r=await fetch('/api/auth/change-password',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({email:fd.get('email'),current_password:fd.get('current_password'),new_password:np})});
    let d;
    try{d=await r.json()}catch{d={detail:'Server error'}}
    if(r.ok){m.textContent='Password updated successfully! Redirecting...';m.className='msg ok';m.style.display='block';
      setTimeout(()=>window.location='/login',2000)}
    else{m.textContent=d.detail||'Failed to update password';m.className='msg err';m.style.display='block'}
  }catch(err){m.textContent='Network error';m.className='msg err';m.style.display='block'}
  finally{btn.disabled=false;btn.textContent='Update Password'}
};
</script></div></body></html>""")


@app.post("/api/auth/change-password")
async def api_change_password(request: Request):
    """Change password: verify current credentials then update via Supabase REST API."""
    from fastapi.responses import JSONResponse

    body = await request.json()
    email = body.get("email", "").strip()
    current_password = body.get("current_password", "")
    new_password = body.get("new_password", "")

    if not email or not current_password or not new_password:
        return JSONResponse({"detail": "All fields are required"}, status_code=400)
    if len(new_password) < 6:
        return JSONResponse({"detail": "New password must be at least 6 characters"}, status_code=400)

    try:
        import httpx
        api_key = settings.supabase_anon_key or settings.supabase_service_key

        # Step 1: verify current credentials by signing in
        async with httpx.AsyncClient(timeout=10) as client:
            auth_resp = await client.post(
                f"{settings.supabase_url}/auth/v1/token?grant_type=password",
                headers={"apikey": api_key, "Content-Type": "application/json"},
                json={"email": email, "password": current_password},
            )
        if auth_resp.status_code != 200:
            return JSONResponse({"detail": "Current password is incorrect"}, status_code=401)

        auth_data = auth_resp.json()
        access_token = auth_data.get("access_token")

        # Step 2: update password using the user's access token
        async with httpx.AsyncClient(timeout=10) as client:
            update_resp = await client.put(
                f"{settings.supabase_url}/auth/v1/user",
                headers={
                    "apikey": api_key,
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={"password": new_password},
            )
        if update_resp.status_code != 200:
            detail = "Failed to update password"
            try:
                err = update_resp.json()
                detail = err.get("msg") or err.get("error_description") or detail
            except Exception:
                pass
            return JSONResponse({"detail": detail}, status_code=400)

        logger.info(f"Password changed for {email}")
        return JSONResponse({"success": True, "detail": "Password updated successfully"})

    except Exception as e:
        logger.error(f"Change password error: {e}")
        return JSONResponse({"detail": "Service error"}, status_code=500)


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
