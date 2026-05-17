"""Billing routes — API key management, credits, and analytics."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.services import credits, analytics
from app.services.blockchain_listener import register_wallet

router = APIRouter(prefix="/billing", tags=["billing"])

class RegisterWalletRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=200)
    wallet: str = Field(min_length=42, max_length=44)  # 0x + 40 hex


@router.post("/create-key")
async def create_key():
    """Generate a new API key. Top it up with credits to start using the API."""
    key = credits.generate_api_key()
    return {
        "api_key": key,
        "message": (
            "Save this key — it won't be shown again. "
            "Top up credits to start: POST /billing/top-up with your key and amount."
        ),
    }


@router.get("/balance")
async def check_balance(key: str = Query(..., description="Your API key")):
    """Check credit balance for an API key."""
    balance = credits.get_balance(key)
    if not balance:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"api_key_prefix": key[:10] + "...", **balance}


@router.post("/top-up")
async def top_up(key: str = Query(...), amount_cents: int = Query(..., ge=100, le=100_000)):
    """Add credits with bulk bonus:
    - $10 (1000c) → +10% bonus
    - $50 (5000c) → +20% bonus
    - $100 (10000c) → +30% bonus
    """
    try:
        bonus_pct, _ = credits.get_bonus_rate(amount_cents)
        new_credits = credits.add_credits(key, amount_cents)
        return {
            "status": "ok",
            "added_usd": amount_cents / 100,
            "bonus_percent": bonus_pct,
            "new_balance_credits": new_credits,
            "new_balance_usd": new_credits / 10 / 100,
        }
    except ValueError:
        raise HTTPException(status_code=404, detail="API key not found")


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
    """Usage analytics: top tools, daily revenue, conversion rate."""
    balance = credits.get_balance(key)
    if not balance:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return analytics.get_stats(days)


@router.post("/register-wallet")
async def register_wallet_endpoint(body: RegisterWalletRequest):
    """Link your wallet address to API key for auto-top-up.
    When you send USDC to our wallet from this address, credits are added automatically.
    """
    balance = credits.get_balance(body.api_key)
    if not balance:
        raise HTTPException(status_code=404, detail="API key not found")
    register_wallet(body.api_key, body.wallet)
    return {
        "status": "ok",
        "message": f"Wallet {body.wallet[:10]}... linked to API key. "
                   f"Send USDC on Base/Arbitrum/Optimism to auto-top-up. "
                   f"Funds are detected within 60 seconds.",
        "wallet": body.wallet,
        "topup_wallet": "0xdE7eb04faE758055642f67f30D246CcB7136C95E",
    }
