"""Docs route — generate technical documentation."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.models import DocsRequest, ServiceResponse
from app.services.deepseek import deepseek_completion
from app.services import credits, analytics
from app.prompts.docs import DOCS_SYSTEM_PROMPT
from app.x402_setup import settle_actual_usage, validate_min_price

MIN_PRICE_MICROUNITS = 5_000

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


@router.post("/api/docs")
async def docs_endpoint(request: Request, body: DocsRequest):
    ok, err = validate_min_price(request, MIN_PRICE_MICROUNITS)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})

    result, tokens = await deepseek_completion(DOCS_SYSTEM_PROMPT, body.code, body.context, json_mode=True)
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = BASE_MICROUNITS + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = max(1, round((microunits / 10000) * CREDIT_MULTIPLIER))
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("docs", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("docs", "x402", True, tokens, microunits / 1e6)
    return ServiceResponse(result=result, payment_network=_get_network(request), payment_tx=_get_tx(request))
