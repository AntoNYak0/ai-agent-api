"""Docs route — generate technical documentation."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx, build_upto_response
from app.models import DocsRequest, ServiceResponse
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.docs import DOCS_SYSTEM_PROMPT
from app.pricing import round_up_cents, get_max_tokens, calc_upto_cost
from app.x402_setup import settle_actual_usage, validate_min_price

MIN_PRICE_MICROUNITS = 5_000
MAX_MICROUNITS = 30_000   # $0.03 cap

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 10000


@router.post("/api/docs")
async def docs_endpoint(request: Request, body: DocsRequest):
    ok, err = validate_min_price(request, MIN_PRICE_MICROUNITS)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")
    if is_api_key:
        if not credits.pre_deduct_max(request.state.human_api_key, MAX_MICROUNITS):
            analytics.track("docs", "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})

    result, tokens, _ = await cached_completion("docs", body.code, DOCS_SYSTEM_PROMPT, body.context, json_mode=True, max_tokens=get_max_tokens("docs"))
    microunits, multiplier, tier = calc_upto_cost(BASE_MICROUNITS, tokens, MAX_MICROUNITS)
    if is_api_key:
        credits.finalize_deduction(request.state.human_api_key, MAX_MICROUNITS, microunits)
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        analytics.track("docs", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("docs", "x402", True, tokens, microunits / 1e6)
    return build_upto_response(result, request, microunits, multiplier, tier, tokens)
