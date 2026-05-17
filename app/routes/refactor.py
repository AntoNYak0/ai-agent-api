"""Refactor route — DRY, SOLID, modern patterns."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx
from app.models import RefactorRequest, ServiceResponse
from app.services.deepseek import deepseek_completion
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.refactor import REFACTOR_SYSTEM_PROMPT
from app.pricing import round_up_cents
from app.x402_setup import settle_actual_usage, validate_min_price

MIN_PRICE_MICROUNITS = 10_000

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 30000


@router.post("/api/refactor")
async def refactor_endpoint(request: Request, body: RefactorRequest):
    ok, err = validate_min_price(request, MIN_PRICE_MICROUNITS)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})

    user_content = f"Instructions: {body.instructions}\n\nCode:\n{body.code}" if body.instructions else body.code
    result, tokens = await cached_completion("refactor", user_content, REFACTOR_SYSTEM_PROMPT, body.context, json_mode=True)
    is_api_key = hasattr(request.state, "human_api_key")
    microunits = BASE_MICROUNITS + int((tokens / 1000) * 3000)
    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        ok = credits.spend_credits(request.state.human_api_key, cost_cents)
        if not ok:
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})
        analytics.track("refactor", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("refactor", "x402", True, tokens, microunits / 1e6)
    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
