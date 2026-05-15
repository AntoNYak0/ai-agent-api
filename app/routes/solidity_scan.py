"""Solidity scanner route — 36 SWC checks + DeFi exploit patterns."""
from fastapi import APIRouter, Request
from app.models import SolidityScanRequest, ServiceResponse
from app.services.deepseek import deepseek_completion
from app.services import credits, analytics
from app.prompts.solidity_scan import SOLIDITY_SCAN_PROMPT

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 40000


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


@router.post("/api/solidity-scan")
async def solidity_scan_endpoint(request: Request, body: SolidityScanRequest):
    result, tokens = await deepseek_completion(SOLIDITY_SCAN_PROMPT, body.code, body.context, json_mode=True)
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = BASE_MICROUNITS + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("solidity-scan", "api_key", True, tokens, cost_cents / 100)
    else:
        analytics.track("solidity-scan", "x402", True, tokens, microunits / 1e6)
    return ServiceResponse(result=result, payment_network=_get_network(request), payment_tx=_get_tx(request))
