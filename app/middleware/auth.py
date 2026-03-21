"""
StockQueen - Authentication Middleware

Two auth mechanisms (checked in order):
  1. API Key   — for scheduler/scripts (X-API-Key header or ?api_key= query)
  2. Supabase JWT — for browser dashboard (sb-access-token cookie or Authorization header)

Either one passing is sufficient for admin access.
"""

import secrets
import time
import logging
from typing import Optional, Dict, Tuple

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, APIKeyQuery

from app.config import settings

logger = logging.getLogger(__name__)

# --- JWT verification cache ---
# Avoids a remote Supabase HTTP call on every single request.
# Cache stores token -> (expire_ts, user_payload). TTL = 5 minutes.
_JWT_CACHE: Dict[str, Tuple[float, dict]] = {}
_JWT_CACHE_TTL = 300  # 5 minutes
_JWT_CACHE_MAX_SIZE = 200  # evict oldest when exceeded

# --- API Key auth ---
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_api_key_query = APIKeyQuery(name="api_key", auto_error=False)

# Cookie names
COOKIE_API_KEY = "sq_api_key"
COOKIE_ACCESS_TOKEN = "sb-access-token"
COOKIE_REFRESH_TOKEN = "sb-refresh-token"
COOKIE_GUEST = "sq_guest"


def _verify_api_key(key: Optional[str]) -> bool:
    """Return True if key matches ADMIN_API_KEY."""
    if not settings.admin_api_key or not key:
        return False
    return secrets.compare_digest(key, settings.admin_api_key)


def _verify_supabase_jwt(token: Optional[str]) -> Optional[dict]:
    """Verify a Supabase JWT and return user payload, or None on failure.

    Uses an in-memory cache (5-min TTL) to avoid a remote Supabase HTTP
    round-trip on every request.  Cache miss → call db.auth.get_user().
    """
    if not token:
        return None

    now = time.time()

    # L1: Check in-memory cache
    cached = _JWT_CACHE.get(token)
    if cached and cached[0] > now:
        return cached[1]
    if cached:
        del _JWT_CACHE[token]

    # L2: Remote verification
    try:
        from app.database import get_db
        db = get_db()
        user_response = db.auth.get_user(token)
        if user_response and user_response.user:
            user_payload = {
                "id": user_response.user.id,
                "email": user_response.user.email,
            }
            # Evict oldest entries if cache is full
            if len(_JWT_CACHE) >= _JWT_CACHE_MAX_SIZE:
                oldest_key = min(_JWT_CACHE, key=lambda k: _JWT_CACHE[k][0])
                del _JWT_CACHE[oldest_key]
            _JWT_CACHE[token] = (now + _JWT_CACHE_TTL, user_payload)
            return user_payload
    except Exception as e:
        logger.debug(f"Supabase JWT verification failed: {e}")
    return None


async def require_admin(
    request: Request,
    header_key: str = Security(_api_key_header),
    query_key: str = Security(_api_key_query),
) -> dict:
    """Dependency that requires admin access via API key OR Supabase JWT.

    Returns:
        dict with auth info: {"method": "api_key"} or {"method": "jwt", "user": {...}}

    Raises:
        HTTPException 403 if neither mechanism passes.
    """
    # 1) API Key check (header → query → cookie)
    api_key = header_key or query_key or request.cookies.get(COOKIE_API_KEY)
    if _verify_api_key(api_key):
        return {"method": "api_key"}

    # 2) Supabase JWT check (Authorization header → cookie)
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        token = request.cookies.get(COOKIE_ACCESS_TOKEN)

    user = _verify_supabase_jwt(token)
    if user:
        return {"method": "jwt", "user": user}

    # 3) Fallback: if ADMIN_API_KEY not configured, allow (dev mode warning)
    if not settings.admin_api_key:
        logger.warning("ADMIN_API_KEY not configured — admin endpoints are UNPROTECTED")
        return {"method": "unconfigured"}

    logger.warning(f"Unauthenticated admin access: {request.method} {request.url.path}")
    raise HTTPException(status_code=403, detail="Authentication required")


# Backward-compatible alias
require_api_key = require_admin
