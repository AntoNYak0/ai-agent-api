"""Reusable FastAPI dependencies — API key, rate limiting, auth.

Pattern adapted from ECC fastapi-patterns:
  - Dependencies are standalone async functions, never created inline
  - Each Depends() is composable: they can depend on each other
  - Testing: override via app.dependency_overrides[dep] instead of middleware
  - No sessions/clients/credentials created inside dependencies

Usage in routes:
    @router.post("/some-endpoint")
    async def endpoint(
        request: Request,
        api_key: str = Depends(require_api_key),       # 401 if missing
        _rate: None = Depends(check_rate_limit),        # 429 if exceeded
    ):
        ...
"""

from fastapi import Depends, Request

from app.services import credits, rate_limiter
from app.errors import Unauthorized, RateLimitExceeded


# ── API Key dependencies ────────────────────────────────────────────

async def get_api_key(request: Request) -> str | None:
    """Extract API key from Authorization header (no validation).

    Returns the raw API key string or None. Use this when auth is OPTIONAL.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ak-"):
        return auth[7:]
    return None


async def require_api_key(request: Request) -> str:
    """Require and validate API key — raises 401 if missing/invalid.

    Use this as a route dependency when auth is REQUIRED.
    """
    api_key = await get_api_key(request)
    if not api_key:
        raise Unauthorized("API key required. Use Authorization: Bearer ak-...")
    return api_key


async def require_valid_api_key(request: Request) -> str:
    """Require API key AND verify it has credits.

    Raises 401 if missing/invalid, does NOT check balance (that's the route's job).
    """
    api_key = await require_api_key(request)
    balance = credits.get_balance(api_key)
    if not balance:
        raise Unauthorized("Invalid API key")
    return api_key


async def require_admin_key(request: Request) -> str:
    """Require admin API key for admin-only endpoints.

    Reads X-Admin-Key header (non-bearer, to avoid conflict with user keys).
    Raises 403 if missing or wrong.
    """
    from app.config import settings
    from app.errors import Forbidden

    admin_key = request.headers.get("X-Admin-Key", "")
    if not settings.admin_api_key:
        raise Forbidden("Admin access is not configured on this server")
    if admin_key != settings.admin_api_key:
        raise Forbidden("Invalid admin key")
    return admin_key


# ── Rate limit dependencies ─────────────────────────────────────────

# Paths exempt from rate limiting
_RATE_LIMIT_SKIP_PREFIXES = ("/health", "/.well-known", "/billing", "/favicon")


async def check_rate_limit(request: Request) -> None:
    """Rate limit: 10 req/min per IP. Raises RateLimitExceeded (429) if exceeded.

    Skips health, well-known, billing, and favicon paths.
    Use as: _rate: None = Depends(check_rate_limit)
    """
    path = request.url.path
    for prefix in _RATE_LIMIT_SKIP_PREFIXES:
        if path.startswith(prefix):
            return

    ip = request.headers.get(
        "x-forwarded-for",
        request.client.host if request.client else "unknown",
    )
    ip = ip.split(",")[0].strip()

    if not rate_limiter.is_allowed(ip):
        raise RateLimitExceeded(
            f"Rate limit exceeded for {ip}",
            retry_after_seconds=60,
        )


# ── Named dependency for payment context (optional, for routes) ────

async def get_payment_context(request: Request) -> dict:
    """Extract payment metadata from request state (set by x402 middleware).

    Returns dict with api_key (if present), payment_network, payment_tx.
    """
    return {
        "api_key": getattr(request.state, "human_api_key", None),
        "payment_network": getattr(request.state, "payment_network", None),
        "payment_tx": getattr(request.state, "payment_tx", None),
    }
