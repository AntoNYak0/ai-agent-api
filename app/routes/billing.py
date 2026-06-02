"""Billing routes — API key management, credits, and analytics."""
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from app.services import credits, analytics, rate_limiter
from app.services.blockchain_listener import register_wallet
from app.config import settings
from app.errors import NotFound, Forbidden, RateLimitExceeded
from app.dependencies import check_rate_limit

router = APIRouter(prefix="/billing", tags=["billing"])

class RegisterWalletRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=200)
    wallet: str = Field(min_length=42, max_length=44)  # 0x + 40 hex


@router.post("/create-key")
async def create_key(request: Request):
    """Generate a new API key. Rate limited to prevent key spray."""
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    ip = ip.split(",")[0].strip()
    if not rate_limiter.is_allowed(ip):
        raise RateLimitExceeded("Too many key requests. Please wait.")
    key = credits.generate_api_key()
    return {
        "api_key": key,
        "welcome_credits": 50,
        "welcome_usd": 0.05,
        "message": (
            "🎉 50 free credits ($0.05) added — enough for 10-50 test API calls. "
            "Save this key — it won't be shown again. "
            "To top up: register your wallet (POST /billing/register-wallet) "
            "then send USDC to 0xdE7eb... — credits appear automatically within 60 seconds."
        ),
    }


@router.get("/balance")
async def check_balance(key: str = Query(..., description="Your API key")):
    """Check credit balance for an API key."""
    balance = credits.get_balance(key)
    if not balance:
        raise NotFound("API key not found")
    return {"api_key_prefix": key[:10] + "...", **balance}


@router.post("/top-up")
async def top_up(key: str = Query(...), amount_cents: int | None = Query(None, ge=100, le=100_000)):
    """Crypto top-up guide — self-service USDC deposit instructions.

    NO payment simulation — this is a PURE guide. Credits are added ONLY
    when the blockchain listener detects a real USDC transfer from your
    registered wallet. No fake balances, no manual top-ups.

    Flow:
    1. Register your wallet: POST /billing/register-wallet {api_key, wallet}
    2. Send USDC from that wallet to our receiving address
    3. Credits appear automatically within 60 seconds (blockchain listener)
    """
    # Validate key exists
    balance = credits.get_balance(key)
    if not balance:
        raise NotFound("API key not found")

    # Build response — optional amount_cents for "if you send $X, you get Y credits"
    estimate = None
    if amount_cents is not None:
        bonus_pct, _ = credits.get_bonus_rate(amount_cents)
        bonus_credits = int(amount_cents * credits.CREDITS_PER_CENT * (1 + bonus_pct / 100))
        estimate = {
            "amount_usd": amount_cents / 100,
            "estimated_credits": bonus_credits,
            "bonus_percent": bonus_pct,
        }

    result = {
        "method": "crypto_self_serve",
        "wallet": "0xdE7eb04faE758055642f67f30D246CcB7136C95E",
        "wallet_tron": "TADavZEHddjYMQcL2cnaFadFVKAUmP9wMw",
        "token": {"evm": "USDC", "tron": "USDT (TRC-20)"},
        "networks": [
            {"name": "Base", "caip2": "eip155:8453", "token": "USDC"},
            {"name": "Arbitrum", "caip2": "eip155:42161", "token": "USDC"},
            {"name": "Optimism", "caip2": "eip155:10", "token": "USDC"},
            {"name": "BNB Chain", "caip2": "eip155:56", "token": "USDC"},
            {"name": "Tron", "caip2": "tron:0x2b6653dc", "token": "USDT"},
        ],
        "conversion": {
            "rate": "1 USDC = $1.00 = 1,000 credits",
            "1_credit": "$0.001 USD",
            "min_deposit": "$1.00 (1,000 credits)",
        },
        "bonus_tiers": [
            {"amount_usd": 1, "bonus": "0%", "credits": 1000},
            {"amount_usd": 10, "bonus": "10%", "credits": 11000},
            {"amount_usd": 50, "bonus": "20%", "credits": 60000},
            {"amount_usd": 100, "bonus": "30%", "credits": 130000},
        ],
        "steps": [
            "1. POST /billing/register-wallet — link your EVM or Tron wallet to this API key",
            f"2. Send USDC (EVM chains) or USDT (Tron) from your registered wallet to the receiving address",
            "3. Blockchain listener detects the transfer within 60 seconds — credits appear automatically",
            "4. GET /billing/balance?key=YOUR_KEY — verify your new balance",
        ],
        "warnings": [
            "Send ONLY from your REGISTERED wallet. Transfers from unknown addresses are ignored.",
            "Minimum deposit: $1.00. Smaller amounts may not cover gas fees on all networks.",
            "DO NOT send from exchanges (Coinbase, Binance, etc.) — use a self-custody wallet only.",
            "Credits never expire. No refunds for crypto deposits.",
        ],
    }

    if estimate is not None:
        result["estimate"] = estimate

    return result


@router.get("/tiers")
async def bulk_tiers():
    """Show bulk discount tiers."""
    return {
        "tiers": [
            {"amount_usd": 1, "amount_cents": 100, "bonus": "0%", "credits": 1000},
            {"amount_usd": 10, "amount_cents": 1000, "bonus": "10%", "credits": 11000},
            {"amount_usd": 50, "amount_cents": 5000, "bonus": "20%", "credits": 60000},
            {"amount_usd": 100, "amount_cents": 10000, "bonus": "30%", "credits": 130000},
        ],
        "note": "Credits never expire. Use with any of the 16 AI services.",
    }


@router.get("/stats")
async def billing_stats():
    """Global billing statistics."""
    return credits.get_stats()


@router.get("/analytics")
async def analytics_dashboard(key: str = Query(..., description="Admin API key"), days: int = Query(7, ge=1, le=30)):
    """Usage analytics: top tools, daily revenue, conversion rate. Admin-only."""
    if not settings.admin_api_key:
        raise Forbidden("Analytics is not configured on this server")
    if key != settings.admin_api_key:
        raise Forbidden("Invalid admin key")
    return analytics.get_stats(days)


@router.post("/register-wallet")
async def register_wallet_endpoint(body: RegisterWalletRequest):
    """Link your wallet address to API key for auto-top-up.
    When you send USDC to our wallet from this address, credits are added automatically.
    """
    balance = credits.get_balance(body.api_key)
    if not balance:
        raise NotFound("API key not found")
    register_wallet(body.api_key, body.wallet)
    return {
        "status": "ok",
        "message": f"Wallet {body.wallet[:10]}... linked to API key. "
                   f"Send USDC on Base/Arbitrum/Optimism to auto-top-up. "
                   f"Funds are detected within 60 seconds.",
        "wallet": body.wallet,
        "topup_wallet": "0xdE7eb04faE758055642f67f30D246CcB7136C95E",
    }
