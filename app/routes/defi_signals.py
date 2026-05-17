"""DeFi signal routes — AI-powered on-chain analysis: whale tracker, smart money, price feed."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx
from app.models import BaseModel, Field, ServiceResponse
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.defi_signals import WHALE_TRACKER_PROMPT, SMART_MONEY_PROMPT, PRICE_FEED_PROMPT
from app.x402_setup import settle_actual_usage, validate_min_price

router = APIRouter()

CREDIT_MULTIPLIER = 1.5

# Pricing: upto with base + per-token
WHALE_BASE = 15_000     # $0.015 base
SMART_BASE = 25_000     # $0.025 base
PRICE_BASE = 10_000     # $0.010 base
WHALE_MIN = 7_500       # min authorized
SMART_MIN = 12_500
PRICE_MIN = 5_000


class WhaleTrackerRequest(BaseModel):
    asset: str = Field(max_length=200)
    wallet_address: str | None = Field(default=None, max_length=500)
    timeframe: str | None = Field(default=None, max_length=100)


class SmartMoneyRequest(BaseModel):
    wallet_address: str = Field(max_length=500)
    chain: str | None = Field(default=None, max_length=100)


class PriceFeedRequest(BaseModel):
    token: str = Field(max_length=200)


@router.post("/api/whale-tracker")
async def whale_tracker(request: Request, body: WhaleTrackerRequest):
    ok, err = validate_min_price(request, WHALE_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    content = f"Asset: {body.asset}\nWallet: {body.wallet_address or 'auto-detect'}\nTimeframe: {body.timeframe or '24h'}"
    result, tokens = await cached_completion("whale-tracker", content, WHALE_TRACKER_PROMPT, None, json_mode=True)

    is_api_key = hasattr(request.state, "human_api_key")
    microunits = WHALE_BASE + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("whale-tracker", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("whale-tracker", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/smart-money")
async def smart_money(request: Request, body: SmartMoneyRequest):
    ok, err = validate_min_price(request, SMART_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    content = f"Wallet: {body.wallet_address}\nChain: {body.chain or 'ethereum'}"
    result, tokens = await cached_completion("smart-money", content, SMART_MONEY_PROMPT, None, json_mode=True)

    is_api_key = hasattr(request.state, "human_api_key")
    microunits = SMART_BASE + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("smart-money", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("smart-money", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))


@router.post("/api/price-feed")
async def price_feed(request: Request, body: PriceFeedRequest):
    ok, err = validate_min_price(request, PRICE_MIN)
    if not ok:
        return JSONResponse(status_code=402, content=err, headers={"PAYMENT-REQUIRED": "true"})

    content = f"Token: {body.token}"
    result, tokens = await cached_completion("price-feed", content, PRICE_FEED_PROMPT, None, json_mode=True)

    is_api_key = hasattr(request.state, "human_api_key")
    microunits = PRICE_BASE + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("price-feed", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("price-feed", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
