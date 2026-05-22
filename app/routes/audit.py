"""Audit route — OWASP Top 10 + SWC Registry security scan."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.routes import get_network, get_tx
from app.models import AuditRequest, ServiceResponse
from app.services.deepseek import deepseek_completion
from app.services.cache import cached_completion
from app.services import credits, analytics
from app.prompts.audit import AUDIT_SYSTEM_PROMPT
from app.pricing import round_up_cents
from app.x402_setup import settle_actual_usage, validate_min_price

MIN_PRICE_MICROUNITS = 10_000

router = APIRouter()

CREDIT_MULTIPLIER = 1.5
BASE_MICROUNITS = 20000


@router.post("/api/audit")
async def audit_endpoint(request: Request, body: AuditRequest):
    ok, err = validate_min_price(request, MIN_PRICE_MICROUNITS)
    if not ok:
        return JSONResponse(status_code=402, content=err,
            headers={"PAYMENT-REQUIRED": "true"})

    is_api_key = hasattr(request.state, "human_api_key")
    if is_api_key:
        cost_cents = round_up_cents((BASE_MICROUNITS / 10000) * CREDIT_MULTIPLIER)
        balance = credits.get_balance(request.state.human_api_key)
        if not balance or (balance["credits"] / 10) < cost_cents:
            analytics.track("audit", "api_key", False, 0, 0)
            return JSONResponse(status_code=402, content={"error": "insufficient_credits"})

    result, tokens = await cached_completion("audit", body.code, AUDIT_SYSTEM_PROMPT, body.context, json_mode=True)
    microunits = BASE_MICROUNITS + int((tokens / 1000) * 3000)

    if is_api_key:
        cost_cents = round_up_cents((microunits / 10000) * CREDIT_MULTIPLIER)
        credits.spend_credits(request.state.human_api_key, cost_cents)
        analytics.track("audit", "api_key", True, tokens, cost_cents / 100)
    else:
        await settle_actual_usage(request, microunits)
        analytics.track("audit", "x402", True, tokens, microunits / 1e6)

    return ServiceResponse(result=result, payment_network=get_network(request), payment_tx=get_tx(request))
