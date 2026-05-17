"""Solidity scanner route — 36 SWC checks + DeFi exploit patterns."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx
from app.models import SolidityScanRequest, ServiceResponse
from app.services.deepseek import deepseek_completion
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.solidity_scan import SOLIDITY_SCAN_PROMPT
from app.x402_setup import settle_actual_usage, validate_min_price

MIN_PRICE_MICROUNITS = 20_000

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 40000


@router.post("/api/solidity-scan")
async def solidity_scan_endpoint(request: Request, body: SolidityScanRequest):
    ok, err = validate_min_price(request, MIN_PRICE_MICROUNITS)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})

    result, tokens = await cached_completion("solidity-scan", body.code, SOLIDITY_SCAN_PROMPT, body.context, json_mode=True)
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = BASE_MICROUNITS + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("solidity-scan", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("solidity-scan", "x402", True, tokens, microunits / 1e6)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
