"""Trading signal route — qualitative crypto analysis."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx
from app.models import TradingSignalRequest, ServiceResponse
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.trading import TRADING_SYSTEM_PROMPT
from app.pricing import round_up_cents, get_max_tokens, PER_1K_TOKENS_MICROUNITS
from app.x402_setup import settle_actual_usage, validate_min_price

MIN_PRICE_MICROUNITS = 5_000

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 10000


@router.post("/api/trading-signal")
async def trading_signal_endpoint(request: Request, body: TradingSignalRequest):
    ok, err = validate_min_price(request, MIN_PRICE_MICROUNITS)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")
    if is_api_key:
        cost_cents = round_up_cents((BASE_MICROUNITS / 10000) * CREDIT_MULTIPLIER)
        balance = credits.get_balance(request.state.human_api_key)
        if not balance or (balance["credits"] / 10) < cost_cents:
            analytics.track("trading", "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})

    user_content = f"Asset: {body.asset}\nTimeframe: {body.timeframe}"
    if body.additional_info:
        user_content += f"\n\nAdditional info: {body.additional_info}"
    result, tokens = await cached_completion("trading", user_content, TRADING_SYSTEM_PROMPT, None, json_mode=True, max_tokens=get_max_tokens("trading"))
    microunits = BASE_MICROUNITS + int((tokens / 1000) * PER_1K_TOKENS_MICROUNITS)
    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("trading", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("trading", "x402", True, tokens, microunits / 1e6)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
