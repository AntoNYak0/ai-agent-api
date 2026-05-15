"""Trading signal route — qualitative crypto analysis."""
from fastapi import APIRouter, Request
from app.models import TradingSignalRequest, ServiceResponse
from app.services.deepseek import deepseek_completion
from app.services import credits, analytics
from app.prompts.trading import TRADING_SYSTEM_PROMPT

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 10000


def _get_network(request: Request) -> str:
    try:
        return request.state.payment_requirements.network
    except AttributeError:
        return "unknown"


def _get_tx(request: Request) -> str:
    try:
        return request.state.payment_payload.transaction
    except AttributeError:
        return "unknown"


@router.post("/api/trading-signal")
async def trading_signal_endpoint(request: Request, body: TradingSignalRequest):
    user_content = f"Asset: {body.asset}\nTimeframe: {body.timeframe}"
    if body.additional_info:
        user_content += f"\n\nAdditional info: {body.additional_info}"
    result, tokens = await deepseek_completion(TRADING_SYSTEM_PROMPT, user_content, json_mode=True)
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = BASE_MICROUNITS + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("trading", "api_key", True, tokens, cost_cents / 100)
    else:
        analytics.track("trading", "x402", True, tokens, microunits / 1e6)
    return ServiceResponse(result=result, payment_network=_get_network(request), payment_tx=_get_tx(request))
